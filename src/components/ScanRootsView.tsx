import { useCallback, useEffect, useState } from "react";
import { fetchScanRoots, deleteScanRoot, type ScanRoot } from "../api/client";
import { useToastStore } from "../store/toast";
import { useUIStore } from "../store/ui";
import "./ScanRootsView.css";

function fmtLastSeen(ts: number | null): string {
  if (ts === null) return "never scanned";
  const diffMs = Date.now() - ts * 1000;
  const days = Math.floor(diffMs / 86_400_000);
  if (days <= 0) return "scanned today";
  if (days === 1) return "scanned 1 day ago";
  if (days < 30) return `scanned ${days} days ago`;
  const months = Math.floor(days / 30);
  if (months < 12) return `scanned ${months} month${months === 1 ? "" : "s"} ago`;
  const years = Math.floor(months / 12);
  return `scanned ${years} year${years === 1 ? "" : "s"} ago`;
}

interface ScanRootsViewProps {
  /** Reuses the app's existing add-folder flow (native picker + /scan/start) —
   *  this view never re-implements folder selection or scanning. */
  onAddFolder: () => void;
}

/** Lists every configured scan root so the user can see and edit what
 *  folders are being scanned (#186). Removing a root only stops future
 *  scanning of that folder — it never deletes already-indexed photos,
 *  faces, or people, per the app's "never silently delete user data" rule. */
export function ScanRootsView({ onAddFolder }: ScanRootsViewProps) {
  const [roots, setRoots] = useState<ScanRoot[]>([]);
  const [loading, setLoading] = useState(true);
  const [confirmingId, setConfirmingId] = useState<number | null>(null);
  const [removingId, setRemovingId] = useState<number | null>(null);
  const scanVersion = useUIStore((s) => s.scanVersion);

  const load = useCallback(() => {
    setLoading(true);
    fetchScanRoots()
      .then((rows) => setRoots(rows))
      .catch(() => setRoots([]))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // Newly added roots (and rescans) surface here too — a scan completing
  // bumps scanVersion elsewhere in the app already, so reuse that signal
  // rather than adding a new polling path.
  useEffect(() => {
    if (scanVersion === 0) return;
    load();
  }, [scanVersion, load]);

  async function doRemove(root: ScanRoot) {
    if (confirmingId !== root.id) {
      setConfirmingId(root.id);
      return;
    }
    setRemovingId(root.id);
    try {
      await deleteScanRoot(root.id);
      setRoots((prev) => prev.filter((r) => r.id !== root.id));
      useToastStore.getState().addToast(`Stopped scanning "${root.path}"`);
    } catch {
      useToastStore.getState().addToast("Could not remove this folder");
    } finally {
      setRemovingId(null);
      setConfirmingId(null);
    }
  }

  return (
    <div className="scan-roots-view">
      <header className="scan-roots-view__header">
        <div>
          <h2 className="scan-roots-view__title">Scan folders</h2>
          <p className="scan-roots-view__subtitle">
            {loading
              ? "Loading…"
              : roots.length === 0
                ? "No folders configured yet"
                : `${roots.length} folder${roots.length === 1 ? "" : "s"} being scanned`}
          </p>
        </div>
        <button
          type="button"
          className="scan-roots-view__add-btn"
          onClick={onAddFolder}
        >
          + Add Folder…
        </button>
      </header>

      {!loading && roots.length === 0 ? (
        <div className="scan-roots-view__empty">
          <p>No folders yet.</p>
          <p className="scan-roots-view__hint">
            Add a local or network folder to start building your library. You
            can add as many folders as you like — local and network folders
            can be scanned together.
          </p>
        </div>
      ) : (
        <ul className="scan-roots-view__list">
          {roots.map((root) => (
            <li key={root.id} className="scan-roots-view__row">
              <span className="scan-roots-view__pathinfo">
                <span className="scan-roots-view__path" title={root.path}>
                  {root.path}
                </span>
                <span className="scan-roots-view__meta">
                  {fmtLastSeen(root.last_seen_at)}
                  {!root.reachable && (
                    <span className="scan-roots-view__offline-tag">
                      unreachable
                    </span>
                  )}
                </span>
              </span>
              <span
                className={`scan-roots-view__type-tag${root.is_network ? " scan-roots-view__type-tag--network" : ""}`}
              >
                {root.is_network ? "network" : "local"}
              </span>
              {confirmingId === root.id ? (
                <span className="scan-roots-view__confirm">
                  <span className="scan-roots-view__confirm-text">
                    Remove this folder from scanning?
                  </span>
                  <button
                    type="button"
                    className="scan-roots-view__btn scan-roots-view__btn--ghost"
                    onClick={() => setConfirmingId(null)}
                    disabled={removingId === root.id}
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    className="scan-roots-view__btn scan-roots-view__btn--danger"
                    onClick={() => void doRemove(root)}
                    disabled={removingId === root.id}
                  >
                    {removingId === root.id ? "Removing…" : "Confirm"}
                  </button>
                </span>
              ) : (
                <button
                  type="button"
                  className="scan-roots-view__remove-btn"
                  onClick={() => void doRemove(root)}
                >
                  Remove
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
