import { useCallback, useEffect, useState } from "react";
import {
  fetchDismissedQueue,
  restoreDismissedFace,
  type DismissedItem,
} from "../api/client";
import { useToastStore } from "../store/toast";
import "./DismissedView.css";

const PAGE = 100;

/** Secondary review window for faces marked "not relevant" (#168) —
 *  deliberately separate from the main To-review queue and gallery, so
 *  dismissed faces stay out of the way until the user chooses to revisit
 *  them here and restore any back into normal evaluation. */
export function DismissedView() {
  const [items, setItems] = useState<DismissedItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [restoring, setRestoring] = useState<number | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    fetchDismissedQueue(0, PAGE)
      .then(setItems)
      .catch(() => setItems([]))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function doRestore(item: DismissedItem) {
    if (restoring !== null) return;
    setRestoring(item.face_id);
    try {
      await restoreDismissedFace(item.face_id);
      useToastStore.getState().addToast("Face restored for review");
      setItems((prev) => prev.filter((i) => i.face_id !== item.face_id));
      // Restoring sends the face to 'unreviewed', not back into the
      // uncertain queue, so the badge count itself doesn't change — no
      // queue-count refetch needed here.
    } catch {
      useToastStore.getState().addToast("Could not restore this face");
    } finally {
      setRestoring(null);
    }
  }

  return (
    <div className="dismissed-view">
      <header className="dismissed-view__header">
        <h2 className="dismissed-view__title">Not relevant faces</h2>
        <p className="dismissed-view__subtitle">
          {loading
            ? "Loading…"
            : items.length === 0
              ? "Nothing dismissed right now"
              : `${items.length} face${items.length === 1 ? "" : "s"} marked not relevant`}
        </p>
      </header>

      {!loading && items.length === 0 ? (
        <div className="dismissed-view__empty">
          <p>Nothing here.</p>
          <p className="dismissed-view__hint">
            Faces you mark &ldquo;Not relevant&rdquo; in the To-review queue
            land here instead of disappearing — restore one anytime to send
            it back for review.
          </p>
        </div>
      ) : (
        <div className="dismissed-view__grid">
          {items.map((item) => (
            <div key={item.face_id} className="dismissed-view__card">
              <img
                className="dismissed-view__crop"
                src={item.face_crop_url}
                alt={`Face ${item.face_id}`}
                loading="lazy"
              />
              <button
                type="button"
                className="dismissed-view__restore-btn"
                onClick={() => void doRestore(item)}
                disabled={restoring === item.face_id}
              >
                {restoring === item.face_id ? "Restoring…" : "Restore for review"}
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
