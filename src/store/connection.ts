import { create } from "zustand";

/**
 * Startup / connection state machine (#118).
 *
 * Phases, in the order they normally occur:
 *
 *   engine-starting  → from app start until the `sidecar-ready` Tauri event
 *                      (or the first successful fetch, whichever comes first)
 *   connecting       → sidecar process is up but HTTP fetches are still being
 *                      retried (withRetry loop in App.tsx)
 *   loading-library  → engine reachable, waiting for the first people fetch
 *   connected        → first data load complete; banner hidden
 *   lost             → WebSocket dropped mid-session and stayed closed for
 *                      more than LOST_DEBOUNCE_MS (brief reconnects don't flash)
 *   failed           → `sidecar-error` Tauri event; persistent error state
 *
 * Model download is not a phase here: the banner derives "downloading" from
 * `modelDownloadProgress` in the UI store while in a startup phase.
 */
export type ConnectionPhase =
  | "engine-starting"
  | "connecting"
  | "loading-library"
  | "connected"
  | "lost"
  | "failed";

export const LOST_DEBOUNCE_MS = 3_000;

interface ConnectionStore {
  phase: ConnectionPhase;
  /** 1-based retry attempt of the initial data load. */
  attempt: number;
  /** `sidecar-ready` Tauri event received — the engine process is up. */
  engineReady: () => void;
  /** A withRetry attempt of the initial load is starting (1-based). */
  retryAttempt: (n: number) => void;
  /** First fetch succeeded — engine reachable, people fetch still pending. */
  loadingLibrary: () => void;
  /** Initial people fetch resolved — hide the banner. */
  connected: () => void;
  /** WebSocket opened — cancels a pending "lost" transition, recovers from lost. */
  wsOpened: () => void;
  /** WebSocket closed. Debounced: only shows "lost" if still down after 3 s. */
  wsClosed: () => void;
  /** `sidecar-error` Tauri event — persistent failure state. */
  failed: () => void;
  /** Reset to the initial state (used by tests). */
  reset: () => void;
}

let _lostTimer: ReturnType<typeof setTimeout> | null = null;
let _wsDown = false;

function clearLostTimer(): void {
  if (_lostTimer !== null) {
    clearTimeout(_lostTimer);
    _lostTimer = null;
  }
}

export const useConnectionStore = create<ConnectionStore>((set, get) => ({
  phase: "engine-starting",
  attempt: 0,

  engineReady: () => {
    if (get().phase === "engine-starting") set({ phase: "connecting" });
  },

  retryAttempt: (n) => {
    const { phase } = get();
    // While the engine is still starting, keep the more informative
    // engine-starting message and just record the attempt count. Once past
    // startup, a retrying load means we are (re-)connecting — this also
    // downgrades loading-library if a fetch succeeded once and then failed.
    if (phase === "connecting" || phase === "loading-library") {
      set({ attempt: n, phase: "connecting" });
    } else {
      set({ attempt: n });
    }
  },

  loadingLibrary: () => {
    const { phase } = get();
    if (phase === "engine-starting" || phase === "connecting") {
      set({ phase: "loading-library" });
    }
  },

  connected: () => {
    if (get().phase !== "failed") set({ phase: "connected" });
  },

  wsOpened: () => {
    _wsDown = false;
    clearLostTimer();
    if (get().phase === "lost") set({ phase: "connected" });
  },

  wsClosed: () => {
    _wsDown = true;
    if (_lostTimer !== null) return; // debounce already pending
    _lostTimer = setTimeout(() => {
      _lostTimer = null;
      // Only a mid-session drop shows "lost" — during startup the banner
      // already explains what is happening.
      if (_wsDown && get().phase === "connected") set({ phase: "lost" });
    }, LOST_DEBOUNCE_MS);
  },

  failed: () => {
    clearLostTimer();
    set({ phase: "failed" });
  },

  reset: () => {
    clearLostTimer();
    _wsDown = false;
    set({ phase: "engine-starting", attempt: 0 });
  },
}));
