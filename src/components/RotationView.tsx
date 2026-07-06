import { useCallback, useEffect, useState } from "react";
import {
  fetchRotationSuggestions,
  startRotationScan,
  rotatePhotos,
  photoThumbUrl,
  type RotationSuggestion,
} from "../api/client";
import { useToastStore } from "../store/toast";
import { useUIStore } from "../store/ui";
import "./RotationView.css";

function fmtSize(bytes: number | null): string {
  if (bytes === null) return "";
  if (bytes >= 1_048_576) return `${(bytes / 1_048_576).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

/** Rotation-suggestion review (#160): each card previews the photo as-is and
 *  rotated so the user sees the exact result before anything is written;
 *  applying rewrites the ORIGINAL file (undoably — Recycle Bin / backup). */
export function RotationView() {
  const [items, setItems] = useState<RotationSuggestion[]>([]);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [loading, setLoading] = useState(true);
  const [scanning, setScanning] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    fetchRotationSuggestions()
      .then((rows) => {
        setItems(rows);
        setSelected(new Set(rows.filter((r) => r.rotatable).map((r) => r.id)));
      })
      .catch(() => setItems([]))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function runScan() {
    if (scanning) return;
    setScanning(true);
    try {
      await startRotationScan();
      useToastStore
        .getState()
        .addToast("Scanning for sideways photos… check the activity log for progress");
    } catch {
      useToastStore.getState().addToast("Could not start the rotation scan");
    } finally {
      setScanning(false);
    }
  }

  function toggle(id: number) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function confirmRotate() {
    if (busy || selected.size === 0) return;
    setBusy(true);
    try {
      const toRotate = items.filter((i) => selected.has(i.id));
      const result = await rotatePhotos(
        toRotate.map((i) => ({ photo_id: i.id, degrees: i.degrees })),
      );
      const parts = [`Rotated ${result.rotated} photo${result.rotated === 1 ? "" : "s"}`];
      if (result.permanent > 0) {
        // "permanent" = Recycle Bin unavailable for that file; it's still
        // backed up in the app for 7 days either way (#164).
        parts.push(`${result.permanent} backed up in-app (no Recycle Bin available)`);
      }
      if (result.failed.length > 0) parts.push(`${result.failed.length} failed`);
      useToastStore.getState().addToast(parts.join(" — "));
      setSelected(new Set());
      setConfirming(false);
      load();
      useUIStore.getState().bumpScanVersion();
    } catch {
      useToastStore.getState().addToast("Could not rotate the selected photos");
    } finally {
      setBusy(false);
    }
  }

  const rotatableSelected = items.filter((i) => selected.has(i.id) && i.rotatable);
  const networkSelected = rotatableSelected.filter((i) => i.is_network);

  return (
    <div className="rotation-view">
      <header className="rotation-view__header">
        <div>
          <h2 className="rotation-view__title">Rotate sideways photos</h2>
          <p className="rotation-view__subtitle">
            {loading
              ? "Loading suggestions…"
              : items.length === 0
                ? "No rotation suggestions yet"
                : `${items.length} suggestion${items.length === 1 ? "" : "s"} — preview before/after, then apply`}
          </p>
        </div>
        <div className="rotation-view__controls">
          <button
            type="button"
            className="rotation-view__btn rotation-view__btn--ghost"
            onClick={() => void runScan()}
            disabled={scanning}
          >
            {scanning ? "Starting…" : "Scan for sideways photos"}
          </button>
          <button
            type="button"
            className="rotation-view__btn rotation-view__btn--primary"
            onClick={() => setConfirming(true)}
            disabled={rotatableSelected.length === 0}
          >
            Rotate {rotatableSelected.length > 0 ? rotatableSelected.length : ""} selected…
          </button>
        </div>
      </header>

      {!loading && items.length === 0 ? (
        <div className="rotation-view__empty">
          <p>No sideways photos found.</p>
          <p className="rotation-view__hint">
            Click &ldquo;Scan for sideways photos&rdquo; to probe photos where no
            face was detected — sideways orientation is the most common reason
            why. Photos with an EXIF rotation tag show up automatically.
          </p>
        </div>
      ) : (
        <div className="rotation-view__grid">
          {items.map((item) => (
            <div
              key={item.id}
              className={`rotation-view__card${selected.has(item.id) ? " rotation-view__card--selected" : ""}${!item.rotatable ? " rotation-view__card--disabled" : ""}`}
            >
              <div className="rotation-view__previews">
                <figure className="rotation-view__preview">
                  <img src={photoThumbUrl(item.id, 200)} alt="Current" />
                  <figcaption>Current</figcaption>
                </figure>
                <span className="rotation-view__arrow" aria-hidden="true">
                  →
                </span>
                <figure className="rotation-view__preview">
                  <img
                    src={photoThumbUrl(item.id, 200)}
                    alt="After rotation"
                    style={{ transform: `rotate(${item.degrees}deg)` }}
                  />
                  <figcaption>After ({item.degrees}°)</figcaption>
                </figure>
              </div>
              <div className="rotation-view__meta">
                <span className="rotation-view__filename" title={item.path}>
                  {item.filename}
                </span>
                <span className="rotation-view__folder" title={item.folder}>
                  {item.folder}
                </span>
                <span className="rotation-view__tags">
                  <span className="rotation-view__source-tag">
                    {item.source === "exif" ? "EXIF tag" : "face detected"}
                  </span>
                  {item.file_size !== null && <span>{fmtSize(item.file_size)}</span>}
                  {item.is_network && (
                    <span className="rotation-view__network-tag">network</span>
                  )}
                  {!item.rotatable && (
                    <span className="rotation-view__unsupported-tag">
                      format not supported
                    </span>
                  )}
                </span>
              </div>
              <label className="rotation-view__checkbox">
                <input
                  type="checkbox"
                  checked={selected.has(item.id)}
                  disabled={!item.rotatable}
                  onChange={() => toggle(item.id)}
                />
                Apply this rotation
              </label>
            </div>
          ))}
        </div>
      )}

      {confirming && (
        <div className="rotation-view__overlay" role="dialog" aria-label="Confirm rotation">
          <div className="rotation-view__dialog">
            <h3>
              Rotate {rotatableSelected.length} photo{rotatableSelected.length === 1 ? "" : "s"}?
            </h3>
            <p>
              Each file will be rewritten in place. Every current version is
              backed up inside the app for 7 days before that happens — local
              files also go to the Windows Recycle Bin when possible. Restore
              any of them from Restore Backups (··· menu) or the Recycle Bin.
            </p>
            {networkSelected.length > 0 && (
              <p className="rotation-view__network-warning" role="alert">
                ℹ {networkSelected.length} file{networkSelected.length === 1 ? " is" : "s are"} on
                a network folder (marked below) — those typically skip the
                Windows Recycle Bin, but the app backup covers them the same way.
              </p>
            )}
            <div className="rotation-view__dialog-actions">
              <button
                type="button"
                className="rotation-view__btn rotation-view__btn--ghost"
                onClick={() => setConfirming(false)}
                disabled={busy}
              >
                Cancel
              </button>
              <button
                type="button"
                className="rotation-view__btn rotation-view__btn--primary"
                onClick={() => void confirmRotate()}
                disabled={busy}
              >
                {busy ? "Rotating…" : "Rotate now"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
