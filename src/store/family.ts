import { create } from "zustand";
import { fetchFamily, type FamilyMember } from "../api/client";

/** The library's family list (#198). While one is loaded, people are named
 *  only by picking a member — never by free text. */
interface FamilyStore {
  loaded: boolean;
  members: FamilyMember[];
  refresh: () => Promise<void>;
}

export const useFamilyStore = create<FamilyStore>((set) => ({
  loaded: false,
  members: [],
  refresh: async () => {
    try {
      const f = await fetchFamily();
      set({ loaded: f.loaded, members: f.members });
    } catch {
      // sidecar not reachable — keep what we had
    }
  },
}));
