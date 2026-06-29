import { create } from "zustand";
import { MOCK_PEOPLE } from "../mocks/data";
import type { Person } from "../mocks/data";

const SIZE_KEY = "faces-h:thumbnailSize";
const DEFAULT_SIZE = 160;

function loadSize(): number {
  const raw = localStorage.getItem(SIZE_KEY);
  const n = raw !== null ? parseInt(raw, 10) : NaN;
  return isNaN(n) ? DEFAULT_SIZE : n;
}

interface UIStore {
  people: Person[];
  selectedPersonId: number | null;
  selectedPhotoId: number | null;
  thumbnailSize: number;
  scanProgress: number | null;
  setPeople: (people: Person[]) => void;
  setSelectedPerson: (id: number | null) => void;
  setSelectedPhoto: (id: number | null) => void;
  setThumbnailSize: (size: number) => void;
  setScanProgress: (progress: number | null) => void;
}

export const useUIStore = create<UIStore>((set) => ({
  people: MOCK_PEOPLE,
  selectedPersonId: null,
  selectedPhotoId: null,
  thumbnailSize: loadSize(),
  scanProgress: null,
  setPeople: (people) => set({ people }),
  setSelectedPerson: (id) => set({ selectedPersonId: id, selectedPhotoId: null }),
  setSelectedPhoto: (id) => set({ selectedPhotoId: id }),
  setThumbnailSize: (size) => {
    localStorage.setItem(SIZE_KEY, String(size));
    set({ thumbnailSize: size });
  },
  setScanProgress: (scanProgress) => set({ scanProgress }),
}));
