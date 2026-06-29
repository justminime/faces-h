import "./App.css";
import { Sidebar } from "./components/Sidebar";
import { PhotoGrid } from "./components/PhotoGrid";
import { DetailPanel } from "./components/DetailPanel";
import { useUIStore } from "./store/ui";
import { MOCK_PEOPLE, MOCK_PHOTOS, MOCK_UNNAMED_COUNT } from "./mocks/data";

function App() {
  const {
    selectedPersonId,
    selectedPhotoId,
    thumbnailSize,
    setSelectedPerson,
    setSelectedPhoto,
    setThumbnailSize,
  } = useUIStore();

  const selectedPhoto = MOCK_PHOTOS.find((p) => p.id === selectedPhotoId) ?? null;

  return (
    <div className="app-shell">
      <Sidebar
        people={MOCK_PEOPLE}
        selectedPersonId={selectedPersonId}
        onPersonSelect={setSelectedPerson}
        unnamedCount={MOCK_UNNAMED_COUNT}
      />
      <PhotoGrid
        photos={MOCK_PHOTOS}
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
