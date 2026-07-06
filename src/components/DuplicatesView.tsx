import { useCallback, useEffect, useState } from "react";
import {
  fetchDuplicates,
  trashPhotos,
  photoThumbUrl,
  type DuplicateGroup,
} from "../api/client";
import { TrashConfirmDialog } from "./TrashConfirmDialog";
import { useToastStore } from "../store/toast";
import { useUIStore } from "../store/ui";
import "./DuplicatesView.css";

function fmtSize(bytes: number | null): string {
  if (bytes === null) return "";
  if (bytes >= 1_048_576) return `${(bytes / 1_048_576).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

/** Duplicate review view (#155): exact and visually-identical groups, each
 *  copy shown with its folder + filename so the user can pick what to keep;
 *  the rest go to the Recycle Bin via the #154 flow. */
export function DuplicatesView() {
  const [groups, setGroups] = useState<DuplicateGroup[]>([]);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [loading, setLoading] = useState(true);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    fetchDuplicates()
      .then(setGroups)
      .catch(() => setGroups([]))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  function toggle(id: number) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  /** Selects every copy except the first of each group — one keeper apiece. */
  function selectRedundant() {
    setSelected(
      new Set(groups.flatMap((g) => g.photos.slice(1).map((p) => p.id))),
    );
  }

  async function confirmTrash() {
    if (busy || selected.size === 0) return;
    setBusy(true);
    try {
      const result = await trashPhotos([...selected]);
      useToastStore
        .getState()
        .addToast(
          `Moved ${result.trashed} duplicate${result.trashed === 1 ? "" : "s"} to the Recycle Bin`,
        );
      setSelected(new Set());
      setConfirming(false);
      load();
      useUIStore.getState().bumpScanVersion();
    } catch {
      useToastStore.getState().addToast("Could not move photos to the Recycle Bin");
    } finally {
      setBusy(false);
    }
  }

  const dupCount = groups.reduce((n, g) => n + g.photos.length, 0);

  return (
    <div className="dupes-view">
      <header className="dupes-view__header">
        <div>
          <h2 className="dupes-view__title">Duplicate photos</h2>
          <p className="dupes-view__subtitle">
            {loading
              ? "Comparing files… (first run hashes candidates, later runs are instant)"
              : groups.length === 0
                ? "No duplicates found"
                : `${groups.length} group${groups.length === 1 ? "" : "s"} · ${dupCount} photos — biggest space-savers first`}
          </p>
        </div>
        <div className="dupes-view__controls">
          <button
            type="button"
            className="dupes-view__btn dupes-view__btn--ghost"
            onClick={selectRedundant}
            disabled={groups.length === 0}
          >
            Keep one per group
          </button>
          <button
            type="button"
            className="dupes-view__btn dupes-view__btn--danger"
            onClick={() => setConfirming(true)}
            disabled={selected.size === 0}
          >
            Delete {selected.size > 0 ? selected.size : ""} selected…
          </button>
        </div>
      </header>

      <div className="dupes-view__groups">
        {groups.map((g, i) => (
          <section key={i} className="dupes-view__group">
            <div className="dupes-view__group-label">
              <span
                className={`dupes-view__kind dupes-view__kind--${g.kind}`}
              >
                {g.kind === "exact" ? "Exact copies" : "Same photo"}
              </span>
              <span className="dupes-view__group-count">
                {g.photos.length} files
              </span>
            </div>
            <div className="dupes-view__rows">
              {g.photos.map((p) => (
                <button
                  type="button"
                  key={p.id}
                  className={`dupes-view__row${selected.has(p.id) ? " dupes-view__row--selected" : ""}`}
                  onClick={() => toggle(p.id)}
                  aria-pressed={selected.has(p.id)}
                  aria-label={`${p.filename} in ${p.folder}`}
                >
                  <img src={photoThumbUrl(p.id, 128)} alt="" loading="lazy" />
                  <span className="dupes-view__fileinfo">
                    <span className="dupes-view__filename">{p.filename}</span>
                    <span className="dupes-view__folder" title={p.folder}>
                      {p.folder}
                    </span>
                  </span>
                  <span className="dupes-view__size">{fmtSize(p.file_size)}</span>
                  <span className="dupes-view__check" aria-hidden="true">
                    {selected.has(p.id) ? "✓" : ""}
                  </span>
                </button>
              ))}
            </div>
          </section>
        ))}
      </div>

      {confirming && (
        <TrashConfirmDialog
          items={groups
            .flatMap((g) => g.photos)
            .filter((p) => selected.has(p.id))
            .map((p) => ({
              id: p.id,
              filename: p.filename,
              folder: p.folder,
              fileSize: p.file_size,
              thumbSrc: photoThumbUrl(p.id, 64),
              isNetwork: p.is_network,
            }))}
          busy={busy}
          onCancel={() => setConfirming(false)}
          onConfirm={() => void confirmTrash()}
        />
      )}
    </div>
  );
}
