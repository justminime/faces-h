import { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { open } from "@tauri-apps/plugin-dialog";
import "./App.css";
import { Sidebar } from "./components/Sidebar";
import { PhotoGrid } from "./components/PhotoGrid";
import { DetailPanel } from "./components/DetailPanel";
import { SearchView } from "./components/SearchView";
import { CorrectionModal } from "./components/CorrectionModal";
import { ToastContainer } from "./components/Toast";
import { Onboarding, ONBOARDING_KEY } from "./components/Onboarding";
import { useUIStore } from "./store/ui";
import { MOCK_UNNAMED_COUNT } from "./mocks/data";
import type { Person, Photo } from "./mocks/data";
import { initClient, fetchPeople, fetchPersonPhotos, fetchQueueCount, fetchModelsStatus, startScan, rescan } from "./api/client";
import { initWs } from "./api/ws";
import type { ApiPerson, ApiPhoto } from "./api/types";
import { useQueueStore } from "./store/queue";
import { useToastStore } from "./store/toast";

function mapPerson(p: ApiPerson): Person {
  return {
    id: p.id,
    name: (p.name ?? "").trim() !== "" ? (p.name as string) : "Unnamed",
    avatarSrc: "",
    photoCount: p.photo_count,
  };
}

function mapPhoto(p: ApiPhoto): Photo {
  return {
    id: p.id,
    src: "",
    path: p.path,
    takenAt: p.taken_at !== null ? String(p.taken_at) : "",
    faces: p.faces.map((f) => ({
      faceId: f.face_id,
      personId: f.person_id,
      personName: null,
      faceSrc: "",
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

  useEffect(() => {
    invoke<string>("get_sidecar_url")
      .then(async (url) => {
        initClient(url);
        initWs(url);
        // If onboarding was previously marked done but the model never downloaded,
        // reset onboarding so the user goes through setup properly.
        if (onboardingDone) {
          try {
            const modelStatus = await fetchModelsStatus();
            if (!modelStatus.ready) {
              localStorage.removeItem(ONBOARDING_KEY);
              setOnboardingDone(false);
              return;
            }
          } catch {
            // sidecar still starting — leave onboarding state as-is
          }
        }
        const [apiPeople, queueResp] = await Promise.all([fetchPeople(), fetchQueueCount()]);
        setPeople(apiPeople.map(mapPerson));
        setQueueCount(queueResp.count);
      })
      .catch(() => {
        // Not running inside Tauri (browser dev mode). Use the dev sidecar URL
        // from the env var set in .env.development so the UI is fully testable
        // without a packaged build.
        const devUrl = import.meta.env.VITE_DEV_SIDECAR_URL as string | undefined;
        if (devUrl) {
          initClient(devUrl);
          initWs(devUrl);
          Promise.all([fetchPeople(), fetchQueueCount()])
            .then(([apiPeople, queueResp]) => {
              setPeople(apiPeople.map(mapPerson));
              setQueueCount(queueResp.count);
            })
            .catch(() => {});
        }
      });
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
          />
          <DetailPanel
            photo={selectedPhoto}
            onCorrectionRequest={handleCorrectionRequest}
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
      <ToastContainer />
    </div>
  );
}

export default App;
