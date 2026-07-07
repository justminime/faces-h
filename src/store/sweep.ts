import { create } from "zustand";

/**
 * Tracks whether a background "sweep" (re-evaluation of a person's cluster
 * against the rest of the library, triggered by naming/confirming/merging —
 * see `sidecar/services/reeval.py`'s `sweep_for_person`) is currently in
 * progress (#184).
 *
 * This exists purely to make an already-happening background action visible:
 * the sweep itself is unchanged, threshold-gated background work. Only the
 * most recent sweep is tracked — if two sweeps overlap (e.g. naming two
 * people in quick succession) this deliberately does not queue or list them,
 * it just shows whichever started most recently, and `finish` only clears
 * the banner if the completing sweep is the one currently shown (so a slow
 * earlier sweep completing after a newer one has started doesn't clear the
 * newer sweep's banner early).
 */
export interface SweepInfo {
  personId: number;
  personName: string | null;
}

interface SweepStore {
  sweeping: SweepInfo | null;
  /** A `sweep_started` event arrived — show the banner for this person. */
  start: (personId: number, personName: string | null) => void;
  /** A `sweep_complete` event arrived — clear the banner if it's still
   *  showing this same person's sweep. */
  finish: (personId: number) => void;
  /** Reset to the initial state (used by tests). */
  reset: () => void;
}

export const useSweepStore = create<SweepStore>((set, get) => ({
  sweeping: null,

  start: (personId, personName) => set({ sweeping: { personId, personName } }),

  finish: (personId) => {
    if (get().sweeping?.personId === personId) {
      set({ sweeping: null });
    }
  },

  reset: () => set({ sweeping: null }),
}));
