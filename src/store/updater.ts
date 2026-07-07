import { create } from "zustand";
import { check, type Update } from "@tauri-apps/plugin-updater";
import { relaunch } from "@tauri-apps/plugin-process";
import { useToastStore } from "./toast";

interface UpdaterState {
  available: Update | null;
  checking: boolean;
  installing: boolean;
  /** -1 = unknown/indeterminate, 0-100 = percent downloaded. */
  progress: number;
  /** manual=true (menu click) always reports a result; manual=false (startup
   *  check) stays silent unless an update is actually found. */
  checkForUpdates: (manual: boolean) => Promise<void>;
  installUpdate: () => Promise<void>;
  dismiss: () => void;
}

export const useUpdaterStore = create<UpdaterState>((set, get) => ({
  available: null,
  checking: false,
  installing: false,
  progress: -1,

  checkForUpdates: async (manual: boolean) => {
    if (get().checking) return;
    set({ checking: true });
    try {
      const update = await check();
      set({ available: update ?? null });
      if (!update && manual) {
        useToastStore.getState().addToast("You're on the latest version");
      }
    } catch {
      if (manual) {
        useToastStore.getState().addToast("Could not check for updates");
      }
    } finally {
      set({ checking: false });
    }
  },

  installUpdate: async () => {
    const update = get().available;
    if (!update || get().installing) return;
    set({ installing: true, progress: -1 });
    let contentLength = 0;
    let downloaded = 0;
    try {
      await update.downloadAndInstall((event) => {
        if (event.event === "Started") {
          contentLength = event.data.contentLength ?? 0;
          set({ progress: contentLength > 0 ? 0 : -1 });
        } else if (event.event === "Progress") {
          downloaded += event.data.chunkLength;
          if (contentLength > 0) {
            set({ progress: Math.round((downloaded / contentLength) * 100) });
          }
        } else if (event.event === "Finished") {
          set({ progress: 100 });
        }
      });
      // The NSIS installer runs in passive mode (no "uninstall previous
      // version?" prompt) and relaunch() restarts into the new version.
      await relaunch();
    } catch {
      set({ installing: false, progress: -1 });
      useToastStore.getState().addToast("Update failed to install — try again later");
    }
  },

  dismiss: () => set({ available: null }),
}));
