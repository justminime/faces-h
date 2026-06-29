import { create } from "zustand";

const SIZE_KEY = "faces-h:thumbnailSize";
const DEFAULT_SIZE = 160;

function loadSize(): number {
  const raw = localStorage.getItem(SIZE_KEY);
  const n = raw !== null ? parseInt(raw, 10) : NaN;
  return isNaN(n) ? DEFAULT_SIZE : n;
}

interface UIStore {
  selectedPersonId: number | null;
  selectedPhotoId: number | null;
  thumbnailSize: number;
  setSelectedPerson: (id: number | null) => void;
  setSelectedPhoto: (id: number | null) => void;
  setThumbnailSize: (size: number) => void;
}

export const useUIStore = create<UIStore>((set) => ({
  selectedPersonId: null,
  selectedPhotoId: null,
  thumbnailSize: loadSize(),
  setSelectedPerson: (id) => set({ selectedPersonId: id, selectedPhotoId: null }),
  setSelectedPhoto: (id) => set({ selectedPhotoId: id }),
  setThumbnailSize: (size) => {
    localStorage.setItem(SIZE_KEY, String(size));
    set({ thumbnailSize: size });
  },
}));
