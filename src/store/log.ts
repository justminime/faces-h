import { create } from "zustand";

export type LogKind = "info" | "success" | "warn" | "progress" | "debug";

export interface LogEntry {
  id: number;
  ts: number;       // Date.now()
  message: string;
  kind: LogKind;
}

interface LogStore {
  entries: LogEntry[];
  /** Append a new entry (capped at 200). */
  push: (message: string, kind?: LogKind) => void;
  /** Replace the last entry if it has the given kind, otherwise push. */
  upsertLast: (message: string, kind: LogKind) => void;
  clear: () => void;
}

let _id = 1;
const MAX = 200;

export const useLogStore = create<LogStore>((set) => ({
  entries: [],

  push: (message, kind = "info") =>
    set((s) => ({
      entries: [
        ...s.entries.slice(-(MAX - 1)),
        { id: _id++, ts: Date.now(), message, kind },
      ],
    })),

  upsertLast: (message, kind) =>
    set((s) => {
      const last = s.entries[s.entries.length - 1];
      if (last?.kind === kind) {
        return {
          entries: [
            ...s.entries.slice(0, -1),
            { ...last, ts: Date.now(), message },
          ],
        };
      }
      return {
        entries: [
          ...s.entries.slice(-(MAX - 1)),
          { id: _id++, ts: Date.now(), message, kind },
        ],
      };
    }),

  clear: () => set({ entries: [] }),
}));
