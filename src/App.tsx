import { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import "./App.css";
import { Sidebar } from "./components/Sidebar";
import { PhotoGrid } from "./components/PhotoGrid";
import { DetailPanel } from "./components/DetailPanel";
import { useUIStore } from "./store/ui";
import { MOCK_PHOTOS, MOCK_UNNAMED_COUNT } from "./mocks/data";
import type { Person, Photo } from "./mocks/data";
import { initClient, fetchPeople, fetchPersonPhotos, fetchQueueCount } from "./api/client";
import { initWs } from "./api/ws";
import type { ApiPerson, ApiPhoto } from "./api/types";
import { useQueueStore } from "./store/queue";

function mapPerson(p: ApiPerson): Person {
  return {
    id: p.id,
    name: p.name,
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
  const [photos, setPhotos] = useState<Photo[]>(MOCK_PHOTOS);

  useEffect(() => {
    invoke<string>("get_sidecar_url")
      .then((url) => {
        initClient(url);
        initWs(url);
        return Promise.all([fetchPeople(), fetchQueueCount()]);
      })
      .then(([apiPeople, queueResp]) => {
        setPeople(apiPeople.map(mapPerson));
        setQueueCount(queueResp.count);
      })
      .catch(() => {
        // not running in Tauri — keep mock data
      });
  }, [setPeople, setQueueCount]);

  useEffect(() => {
    if (selectedPersonId === null) {
      setPhotos(MOCK_PHOTOS);
      return;
    }
    fetchPersonPhotos(selectedPersonId)
      .then((apiPhotos) => setPhotos(apiPhotos.map(mapPhoto)))
      .catch(() => setPhotos([]));
  }, [selectedPersonId]);

  const selectedPhoto = photos.find((p) => p.id === selectedPhotoId) ?? null;

  return (
    <div className="app-shell">
      <Sidebar
        people={people}
        selectedPersonId={selectedPersonId}
        onPersonSelect={setSelectedPerson}
        unnamedCount={MOCK_UNNAMED_COUNT}
        scanProgress={scanProgress}
      />
      <PhotoGrid
        photos={photos}
        thumbnailSize={thumbnailSize}
        onSizeChange={setThumbnailSize}
        onSelect={setSelectedPhoto}
        selectedPhotoId={selectedPhotoId}
      />
      <DetailPanel photo={selectedPhoto} />
    </div>
  );
}

export default App;
