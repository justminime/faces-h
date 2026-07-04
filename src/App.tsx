import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { open } from "@tauri-apps/plugin-dialog";
import "./App.css";
import { Sidebar } from "./components/Sidebar";
import { PhotoGrid } from "./components/PhotoGrid";
import { DetailPanel } from "./components/DetailPanel";
import { SearchView } from "./components/SearchView";
import { CorrectionModal } from "./components/CorrectionModal";
import { NamingModal } from "./components/NamingModal";
import { ToastContainer } from "./components/Toast";
import { Onboarding, ONBOARDING_KEY } from "./components/Onboarding";
import { useUIStore } from "./store/ui";
import { MOCK_UNNAMED_COUNT } from "./mocks/data";
import type { Person, Photo } from "./mocks/data";
import {
  initClient,
  fetchPeople,
  fetchPersonPhotos,
  fetchQueueCount,
  fetchModelsStatus,
  startScan,
  rescan,
  photoThumbUrl,
  faceCropUrl,
  exportLibrary,
  importLibrary,
} from "./api/client";
import { initWs } from "./api/ws";
import { withRetry } from "./api/retry";
import type { ApiPerson, ApiPhoto } from "./api/types";
import { useQueueStore } from "./store/queue";
import { useToastStore } from "./store/toast";

const PAGE_SIZE = 50;
const PEOPLE_CACHE_KEY = "faces_h_people_cache";

function mapPerson(p: ApiPerson): Person {
  return {
    id: p.id,
    name: (p.name ?? "").trim() !== "" ? (p.name as string) : "Unnamed",
    avatarSrc: p.medallion_face_id !== null ? faceCropUrl(p.medallion_face_id) : "",
    photoCount: p.photo_count,
  };
}

function mapPhoto(p: ApiPhoto): Photo {
  return {
    id: p.id,
    src: photoThumbUrl(p.id),
    path: p.path,
    takenAt: p.taken_at !== null ? String(p.taken_at) : "",
    faces: p.faces.map((f) => ({
      faceId: f.face_id,
      personId: f.person_id,
      personName: null,
      faceSrc: faceCropUrl(f.face_id),
    })),
  };
}

function loadCachedPeople(): Person[] {
  try {
    const raw = localStorage.getItem(PEOPLE_CACHE_KEY);
    if (!raw) return [];
    return JSON.parse(raw) as Person[];
  } catch {
    return [];
  }
}

function savePeopleCache(people: Person[]) {
  try {
    localStorage.setItem(PEOPLE_CACHE_KEY, JSON.stringify(people));
  } catch {
    // storage quota exceeded — ignore
  }
}

function App() {
  const {
    people,
    selectedPersonId,
    selectedPhotoId,
    thumbnailSize,
    scanProgress,
    setPeople,
    setSelectedPerson,
    setSelectedPhoto,
    setThumbnailSize,
  } = useUIStore();

  const setQueueCount = useQueueStore((s) => s.setQueueCount);
  const scanVersion = useUIStore((s) => s.scanVersion);

  const [photos, setPhotos] = useState<Photo[]>([]);
  const [hasMorePhotos, setHasMorePhotos] = useState(false);
  const [isLoadingPhotos, setIsLoadingPhotos] = useState(false);
  const photoOffsetRef = useRef(0);
  const personGenRef = useRef(0);   // incremented on each person switch to cancel stale loads
  const pageLoadingRef = useRef(false); // guards against concurrent page fetches

  const [view, setView] = useState<"gallery" | "search">("gallery");
  const [onboardingDone, setOnboardingDone] = useState(
    () => localStorage.getItem(ONBOARDING_KEY) !== null,
  );
  const [correctionTarget, setCorrectionTarget] = useState<{
    faceId: number;
    photoId: number;
  } | null>(null);
  const [namingPersonId, setNamingPersonId] = useState<number | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const nameByPersonId = useMemo(() => {
    const m = new Map<number, string>();
    for (const p of people) m.set(p.id, p.name ?? "Unnamed");
    return m;
  }, [people]);
  const resolvePersonName = (personId: number | null): string =>
    personId !== null ? (nameByPersonId.get(personId) ?? "Unknown") : "Unknown";

  // ── Startup: show cached people immediately, refresh once sidecar is ready ──
  useEffect(() => {
    const cached = loadCachedPeople();
    if (cached.length > 0) setPeople(cached);

    let cancelled = false;

    async function loadOnce(): Promise<void> {
      if (onboardingDone) {
        const modelStatus = await fetchModelsStatus();
        if (!modelStatus.ready) {
          localStorage.removeItem(ONBOARDING_KEY);
          setOnboardingDone(false);
          return;
        }
      }
      const [apiPeople, queueResp] = await Promise.all([fetchPeople(), fetchQueueCount()]);
      if (cancelled) return;
      const mapped = apiPeople.map(mapPerson);
      setPeople(mapped);
      savePeopleCache(mapped);
      setQueueCount(queueResp.count);
    }

    const loadWithRetry = () => withRetry(loadOnce, { signal: () => cancelled });

    invoke<string>("get_sidecar_url")
      .then((url) => {
        initClient(url);
        initWs(url);
        void loadWithRetry();
      })
      .catch(() => {
        const devUrl = import.meta.env.VITE_DEV_SIDECAR_URL as string | undefined;
        if (devUrl) {
          initClient(devUrl);
          initWs(devUrl);
          void loadWithRetry();
        }
      });

    return () => {
      cancelled = true;
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [setPeople, setQueueCount]);

  // Refresh sidebar when a scan completes.
  useEffect(() => {
    if (scanVersion === 0) return;
    Promise.all([fetchPeople(), fetchQueueCount()])
      .then(([apiPeople, queueResp]) => {
        const mapped = apiPeople.map(mapPerson);
        setPeople(mapped);
        savePeopleCache(mapped);
        setQueueCount(queueResp.count);
      })
      .catch(() => {});
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scanVersion]);

  // ── Incremental photo loading ─────────────────────────────────────────────
  useEffect(() => {
    if (selectedPersonId === null) {
      setPhotos([]);
      setHasMorePhotos(false);
      setIsLoadingPhotos(false);
      photoOffsetRef.current = 0;
      pageLoadingRef.current = false;
      return;
    }
    const gen = ++personGenRef.current;
    setPhotos([]);
    setHasMorePhotos(false);
    setIsLoadingPhotos(true);
    photoOffsetRef.current = 0;
    pageLoadingRef.current = true;

    // Use order=random so SQLite samples from the full pool — each visit
    // surfaces a different mix of old and new photos, not always the first 50.
    fetchPersonPhotos(selectedPersonId, 0, PAGE_SIZE, "random")
      .then((apiPhotos) => {
        if (personGenRef.current !== gen) return;
        const mapped = apiPhotos.map(mapPhoto);
        setPhotos(mapped);
        setHasMorePhotos(mapped.length === PAGE_SIZE);
        photoOffsetRef.current = mapped.length;
      })
      .catch(() => {
        if (personGenRef.current === gen) setPhotos([]);
      })
      .finally(() => {
        if (personGenRef.current === gen) {
          setIsLoadingPhotos(false);
          pageLoadingRef.current = false;
        }
      });
  }, [selectedPersonId]);

  const loadMorePhotos = useCallback(() => {
    if (!selectedPersonId || pageLoadingRef.current || !hasMorePhotos) return;
    const gen = personGenRef.current;
    pageLoadingRef.current = true;
    setIsLoadingPhotos(true);

    fetchPersonPhotos(selectedPersonId, photoOffsetRef.current, PAGE_SIZE)
      .then((apiPhotos) => {
        if (personGenRef.current !== gen) return;
        const mapped = apiPhotos.map(mapPhoto);
        setPhotos((prev) => [...prev, ...mapped]);
        setHasMorePhotos(mapped.length === PAGE_SIZE);
        photoOffsetRef.current += mapped.length;
      })
      .catch(() => {})
      .finally(() => {
        if (personGenRef.current === gen) {
          setIsLoadingPhotos(false);
          pageLoadingRef.current = false;
        }
      });
  }, [selectedPersonId, hasMorePhotos]);

  // ── Native menu event handler ─────────────────────────────────────────────
  useEffect(() => {
    let unlisten: (() => void) | undefined;
    listen<string>("menu-action", (event) => {
      switch (event.payload) {
        case "add-folder":   void handleAddFolder();       break;
        case "rescan":       void handleRescan();           break;
        case "export":       void handleExport();           break;
        case "import":       fileInputRef.current?.click(); break;
        case "view-gallery": setView("gallery");            break;
        case "view-search":  setView("search");             break;
      }
    })
      .then((fn) => { unlisten = fn; })
      .catch(() => {});
    return () => unlisten?.();
  }, []);

  const selectedPhoto = photos.find((p) => p.id === selectedPhotoId) ?? null;
  const selectedPerson = people.find((p) => p.id === selectedPersonId) ?? null;
  const selectedPersonIsNamed =
    selectedPerson !== null && selectedPerson.name !== "Unnamed";

  const namingSampleSrcs = photos
    .flatMap((p) => p.faces)
    .filter((f) => f.personId === namingPersonId)
    .slice(0, 6)
    .map((f) => f.faceSrc);

  function refreshPeople() {
    Promise.all([fetchPeople(), fetchQueueCount()])
      .then(([apiPeople, queueResp]) => {
        const mapped = apiPeople.map(mapPerson);
        setPeople(mapped);
        savePeopleCache(mapped);
        setQueueCount(queueResp.count);
      })
      .catch(() => {});
  }

  if (!onboardingDone) {
    return <Onboarding onComplete={() => setOnboardingDone(true)} />;
  }

  async function handleAddFolder() {
    try {
      const selected = await open({ directory: true, multiple: false });
      if (typeof selected === "string" && selected.length > 0) {
        await startScan(selected);
        const folderName = selected.replace(/\\/g, "/").split("/").pop() ?? selected;
        useToastStore.getState().addToast(`Scanning "${folderName}"…`);
      }
    } catch {
      // not in Tauri or user cancelled
    }
  }

  async function handleRescan() {
    try {
      await rescan();
    } catch {
      // sidecar not reachable
    }
  }

  async function handleExport() {
    try {
      const bundle = await exportLibrary();
      const blob = new Blob([JSON.stringify(bundle, null, 2)], {
        type: "application/json",
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "faces-h-library.json";
      a.click();
      URL.revokeObjectURL(url);
      const n = bundle.people.length;
      useToastStore.getState().addToast(`Exported ${n} named ${n === 1 ? "person" : "people"}`);
    } catch {
      useToastStore.getState().addToast("Export failed");
    }
  }

  async function handleImportFile(file: File) {
    try {
      const bundle = JSON.parse(await file.text());
      const summary = await importLibrary(bundle);
      refreshPeople();
      const extra = summary.unmatched.length
        ? `, ${summary.unmatched.length} unmatched`
        : "";
      useToastStore
        .getState()
        .addToast(`Imported ${summary.applied} name${summary.applied === 1 ? "" : "s"}${extra}`);
    } catch {
      useToastStore.getState().addToast("Import failed — invalid file");
    }
  }

  function handleCorrectionRequest(faceId: number) {
    if (!selectedPhoto) return;
    setCorrectionTarget({ faceId, photoId: selectedPhoto.id });
  }

  return (
    <div className="app-shell">
      <Sidebar
        people={people}
        selectedPersonId={selectedPersonId}
        onPersonSelect={(id) => { setSelectedPerson(id); setView("gallery"); }}
        unnamedCount={MOCK_UNNAMED_COUNT}
        scanProgress={scanProgress}
        onQueueClick={() => setView("gallery")}
        onSearchClick={() => setView("search")}
        onAddFolder={() => void handleAddFolder()}
        onRescan={() => void handleRescan()}
        onExport={() => void handleExport()}
        onImport={() => fileInputRef.current?.click()}
      />
      <input
        ref={fileInputRef}
        type="file"
        accept="application/json"
        style={{ display: "none" }}
        aria-hidden="true"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) void handleImportFile(f);
          e.target.value = "";
        }}
      />
      {view === "search" ? (
        <SearchView people={people} />
      ) : (
        <>
          <PhotoGrid
            photos={photos}
            thumbnailSize={thumbnailSize}
            onSizeChange={setThumbnailSize}
            onSelect={setSelectedPhoto}
            selectedPhotoId={selectedPhotoId}
            personName={selectedPerson?.name ?? null}
            personAvatarSrc={selectedPerson?.avatarSrc}
            isNamed={selectedPersonIsNamed}
            onRenamePerson={
              selectedPersonId !== null
                ? () => setNamingPersonId(selectedPersonId)
                : undefined
            }
            hasMore={hasMorePhotos}
            isLoading={isLoadingPhotos}
            onLoadMore={loadMorePhotos}
          />
          <DetailPanel
            photo={selectedPhoto}
            onCorrectionRequest={handleCorrectionRequest}
            resolvePersonName={resolvePersonName}
            highlightPersonId={selectedPersonId}
          />
        </>
      )}
      {correctionTarget && (
        <CorrectionModal
          faceId={correctionTarget.faceId}
          photoId={correctionTarget.photoId}
          people={people}
          onCorrected={() => setCorrectionTarget(null)}
          onClose={() => setCorrectionTarget(null)}
        />
      )}
      {namingPersonId !== null && (
        <div
          className="naming-modal-overlay"
          onClick={() => setNamingPersonId(null)}
        >
          <div onClick={(e) => e.stopPropagation()}>
            <NamingModal
              personId={namingPersonId}
              sampleFaceSrcs={namingSampleSrcs}
              existingNames={people
                .map((p) => p.name)
                .filter((n): n is string => n !== null && n !== "Unnamed")}
              onSaved={() => {
                setNamingPersonId(null);
                refreshPeople();
              }}
              onSkip={() => setNamingPersonId(null)}
            />
          </div>
        </div>
      )}
      <ToastContainer />
    </div>
  );
}

export default App;
