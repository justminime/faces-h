import { create } from "zustand";

interface Toast {
  id: number;
  message: string;
}

interface ToastStore {
  toasts: Toast[];
  addToast: (message: string) => void;
  removeToast: (id: number) => void;
}

let _nextId = 1;

export const useToastStore = create<ToastStore>((set) => ({
  toasts: [],
  addToast: (message) =>
    set((s) => ({ toasts: [...s.toasts, { id: _nextId++, message }] })),
  removeToast: (id) =>
    set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
}));
