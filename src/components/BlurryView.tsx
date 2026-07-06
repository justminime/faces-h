import { useCallback, useEffect, useRef, useState } from "react";
import {
  fetchBlurryPhotos,
  trashPhotos,
  photoThumbUrl,
  type BlurryPhoto,
} from "../api/client";
import { TrashConfirmDialog } from "./TrashConfirmDialog";
import { useToastStore } from "../store/toast";
import { useUIStore } from "../store/ui";
import "./BlurryView.css";

// Slider % → Laplacian-variance cutoff. 100% casts the widest net (mildly
// soft photos included); 20% keeps only the most severely blurred.
const MAX_THRESHOLD = 120;
const sliderToThreshold = (pct: number) => Math.round((pct / 100) * MAX_THRESHOLD);

/** Review-and-delete view for blurry photos (#154): a live cutoff slider
 *  refilters the grid so the user sees exactly what each level captures,
 *  then moves the selected files to the OS Recycle Bin. */
export function BlurryView() {
  const [photos, setPhotos] = useState<BlurryPhoto[]>([]);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [sliderPct, setSliderPct] = useState(50);
  const [loading, setLoading] = useState(true);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const load = useCallback((pct: number) => {
    setLoading(true);
    fetchBlurryPhotos(0, 200, sliderToThreshold(pct))
      .then((rows) => {
        setPhotos(rows);
        // Drop selections that fell outside the new cutoff.
        setSelected((prev) => {
          const ids = new Set(rows.map((r) => r.id));
          return new Set([...prev].filter((id) => ids.has(id)));
        });
      })
      .catch(() => setPhotos([]))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load(sliderPct);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function onSlider(pct: number) {
    setSliderPct(pct);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => load(pct), 300);
  }

  function toggle(id: number) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function selectAll() {
    setSelected((prev) =>
      prev.size === photos.length ? new Set() : new Set(photos.map((p) => p.id)),
    );
  }

  async function confirmTrash() {
    if (busy || selected.size === 0) return;
    setBusy(true);
    try {
      const result = await trashPhotos([...selected]);
      const parts = [`Deleted ${result.trashed + result.deleted_permanently} photo${result.trashed + result.deleted_permanently === 1 ? "" : "s"}`];
      if (result.deleted_permanently > 0) {
        parts.push(`${result.deleted_permanently} backed up in-app (no Recycle Bin available)`);
      }
      if (result.failed.length > 0) parts.push(`${result.failed.length} failed`);
      useToastStore.getState().addToast(parts.join(" — "));
      setSelected(new Set());
      setConfirming(false);
      load(sliderPct);
      // Photo counts changed — refresh the sidebar via the existing channel.
      useUIStore.getState().bumpScanVersion();
    } catch {
      useToastStore.getState().addToast("Could not move photos to the Recycle Bin");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="blurry-view">
      <header className="blurry-view__header">
        <div>
          <h2 className="blurry-view__title">Blurry photos</h2>
          <p className="blurry-view__subtitle">
            {loading
              ? "Scanning for blur…"
              : `${photos.length} photo${photos.length === 1 ? "" : "s"} at or below the cutoff — most blurred first`}
          </p>
        </div>
        <div className="blurry-view__controls">
          <label className="blurry-view__slider-label" htmlFor="blur-cutoff">
            Blur cutoff: <strong>{sliderPct}%</strong>
          </label>
          <input
            id="blur-cutoff"
            type="range"
            min={20}
            max={100}
            step={5}
            value={sliderPct}
            onChange={(e) => onSlider(Number(e.target.value))}
            aria-label="Blur cutoff"
          />
          <button
            type="button"
            className="blurry-view__btn blurry-view__btn--ghost"
            onClick={selectAll}
            disabled={photos.length === 0}
          >
            {selected.size === photos.length && photos.length > 0
              ? "Clear selection"
              : "Select all"}
          </button>
          <button
            type="button"
            className="blurry-view__btn blurry-view__btn--danger"
            onClick={() => setConfirming(true)}
            disabled={selected.size === 0}
          >
            Delete {selected.size > 0 ? selected.size : ""} selected…
          </button>
        </div>
      </header>

      {!loading && photos.length === 0 ? (
        <div className="blurry-view__empty">
          <p>No blurry photos at this cutoff.</p>
          <p className="blurry-view__hint">
            Raise the slider to cast a wider net. Photos added before this
            feature get scored on their next rescan.
          </p>
        </div>
      ) : (
        <div className="blurry-view__grid">
          {photos.map((p) => (
            <button
              type="button"
              key={p.id}
              className={`blurry-view__tile${selected.has(p.id) ? " blurry-view__tile--selected" : ""}`}
              onClick={() => toggle(p.id)}
              aria-pressed={selected.has(p.id)}
              aria-label={`Photo ${p.id}, blur score ${Math.round(p.blur_score)}`}
            >
              <img src={photoThumbUrl(p.id)} alt={p.path} loading="lazy" />
              <span className="blurry-view__score">{Math.round(p.blur_score)}</span>
              <span className="blurry-view__check" aria-hidden="true">
                {selected.has(p.id) ? "✓" : ""}
              </span>
            </button>
          ))}
        </div>
      )}

      {confirming && (
        <TrashConfirmDialog
          items={photos
            .filter((p) => selected.has(p.id))
            .map((p) => {
              const parts = p.path.split(/[/\\]/);
              return {
                id: p.id,
                filename: parts[parts.length - 1] ?? p.path,
                folder: parts.slice(0, -1).join("\\"),
                fileSize: p.file_size,
                thumbSrc: photoThumbUrl(p.id, 64),
                isNetwork: p.is_network,
              };
            })}
          busy={busy}
          onCancel={() => setConfirming(false)}
          onConfirm={() => void confirmTrash()}
        />
      )}
    </div>
  );
}
