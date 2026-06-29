import { create } from "zustand";

interface QueueStore {
  queueCount: number;
  setQueueCount: (count: number) => void;
}

export const useQueueStore = create<QueueStore>((set) => ({
  queueCount: 0,
  setQueueCount: (count) => set({ queueCount: count }),
}));
