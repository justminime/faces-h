import { useEffect, useMemo, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
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
import { initClient, fetchPeople, fetchPersonPhotos, fetchQueueCount, fetchModelsStatus, startScan, rescan, photoThumbUrl, faceCropUrl } from "./api/client";
import { initWs } from "./api/ws";
import { withRetry } from "./api/retry";
import type { ApiPerson, ApiPhoto } from "./api/types";
import { useQueueStore } from "./store/queue";
import { useToastStore } from "./store/toast";

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
  const [view, setView] = useState<"gallery" | "search">("gallery");
  const [onboardingDone, setOnboardingDone] = useState(
    () => localStorage.getItem(ONBOARDING_KEY) !== null,
  );
  const [correctionTarget, setCorrectionTarget] = useState<{
    faceId: number;
    photoId: number;
  } | null>(null);
  const [namingPersonId, setNamingPersonId] = useState<number | null>(null);

  // Resolve a face's person_id to a display name for the detail panel.
  const nameByPersonId = useMemo(() => {
    const m = new Map<number, string>();
    for (const p of people) m.set(p.id, p.name ?? "Unnamed");
    return m;
  }, [people]);
  const resolvePersonName = (personId: number | null): string =>
    personId !== null ? (nameByPersonId.get(personId) ?? "Unknown") : "Unknown";

  useEffect(() => {
    let cancelled = false;

    // One attempt at the initial load. Throws on any connectivity error so the
    // caller retries; only a *successful* models/status with ready:false is
    // treated as "needs onboarding" (never a network error — see #78).
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
      setPeople(apiPeople.map(mapPerson));
      setQueueCount(queueResp.count);
    }

    // The sidecar URL is available immediately, but the sidecar itself may take
    // up to ~100s to start on a fresh install while Windows Defender scans the
    // new binary. Retry until it responds instead of leaving an empty gallery.
    const loadWithRetry = () =>
      withRetry(loadOnce, { signal: () => cancelled });

    invoke<string>("get_sidecar_url")
      .then((url) => {
        initClient(url);
        initWs(url);
        void loadWithRetry();
      })
      .catch(() => {
        // Not running inside Tauri (browser dev mode). Use the dev sidecar URL
        // from the env var set in .env.development so the UI is fully testable
        // without a packaged build.
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

  // Refresh sidebar when a scan completes (ws.ts bumps scanVersion on scan_complete).
  useEffect(() => {
    if (scanVersion === 0) return;
    Promise.all([fetchPeople(), fetchQueueCount()])
      .then(([apiPeople, queueResp]) => {
        setPeople(apiPeople.map(mapPerson));
        setQueueCount(queueResp.count);
      })
      .catch(() => {});
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scanVersion]);

  useEffect(() => {
    if (selectedPersonId === null) {
      setPhotos([]);
      return;
    }
    fetchPersonPhotos(selectedPersonId)
      .then((apiPhotos) => setPhotos(apiPhotos.map(mapPhoto)))
      .catch(() => setPhotos([]));
  }, [selectedPersonId]);

  const selectedPhoto = photos.find((p) => p.id === selectedPhotoId) ?? null;
  const selectedPerson = people.find((p) => p.id === selectedPersonId) ?? null;
  const selectedPersonIsNamed =
    selectedPerson !== null && selectedPerson.name !== "Unnamed";

  // Face crops of the selected person, shown as samples in the naming modal.
  const namingSampleSrcs = photos
    .flatMap((p) => p.faces)
    .filter((f) => f.personId === namingPersonId)
    .slice(0, 6)
    .map((f) => f.faceSrc);

  function refreshPeople() {
    Promise.all([fetchPeople(), fetchQueueCount()])
      .then(([apiPeople, queueResp]) => {
        setPeople(apiPeople.map(mapPerson));
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
