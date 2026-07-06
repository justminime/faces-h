import { useCallback, useEffect, useRef, useState } from "react";
import { fetchUncertainQueue, fetchQueueCount } from "../api/client";
import type { QueueItem } from "../api/types";
import { UncertainQueue } from "./UncertainQueue";
import { useQueueStore } from "../store/queue";
import { useUIStore } from "../store/ui";
import { useToastStore } from "../store/toast";
import "./QueueView.css";

const QUEUE_PAGE = 100;

/** Full review flow for uncertain faces (#108): fetches the queue, renders
 *  UncertainQueue cards, and keeps the sidebar badge in sync as items are
 *  confirmed or skipped. */
export function QueueView() {
  const [items, setItems] = useState<QueueItem[]>([]);
  const [loading, setLoading] = useState(true);
  const setQueueCount = useQueueStore((s) => s.setQueueCount);
  const queueCount = useQueueStore((s) => s.queueCount);
  // Faces skipped this session stay uncertain server-side; remember them so a
  // refetch doesn't surface them again immediately.
  const skippedRef = useRef<Set<number>>(new Set());

  const refresh = useCallback(() => {
    setLoading(true);
    Promise.all([fetchUncertainQueue(0, QUEUE_PAGE), fetchQueueCount()])
      .then(([queue, count]) => {
        setItems(queue.filter((q) => !skippedRef.current.has(q.face_id)));
        setQueueCount(count.count);
      })
      .catch(() => setItems([]))
      .finally(() => setLoading(false));
  }, [setQueueCount]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // A background sweep (#169) — triggered by confirming a face elsewhere —
  // can resolve several OTHER faces in this exact list without this
  // component knowing. scanVersion is the same signal the sidebar/people
  // list already use to refresh after that happens; without it, resolved
  // cards stayed stuck showing stale Yes/No/Not relevant buttons (#178).
  const scanVersion = useUIStore((s) => s.scanVersion);
  const mountedVersion = useRef(scanVersion);
  useEffect(() => {
    if (scanVersion === mountedVersion.current) return;
    mountedVersion.current = scanVersion;
    refresh();
  }, [scanVersion, refresh]);

  const handleReviewed = useCallback(
    (faceId: number, mode: "confirmed" | "skipped" | "dismissed") => {
      if (mode === "skipped") skippedRef.current.add(faceId);
      setItems((prev) => {
        const next = prev.filter((i) => i.face_id !== faceId);
        // Page exhausted but more may be waiting server-side — pull the next batch.
        if (next.length === 0) refresh();
        return next;
      });
      if (mode !== "skipped") {
        // Confirmed and dismissed are both persistent server-side, so the
        // badge count needs a refresh either way.
        fetchQueueCount()
          .then((c) => setQueueCount(c.count))
          .catch(() => {});
      }
      if (mode === "confirmed") {
        // Confirming changes photo counts / medallions — reuse the existing
        // sidebar refresh channel. Dismissing touches neither.
        useUIStore.getState().bumpScanVersion();
      }
    },
    [refresh, setQueueCount],
  );

  // A card's action failed — most likely another sweep/refresh already
  // resolved this exact face server-side. Don't leave a dead card in place;
  // tell the user and resync the whole list (#178).
  const handleError = useCallback(() => {
    useToastStore
      .getState()
      .addToast("This face was already updated elsewhere — refreshing the queue");
    refresh();
  }, [refresh]);

  return (
    <div className="queue-view">
      <header className="queue-view__header">
        <h2 className="queue-view__title">Review uncertain faces</h2>
        <p className="queue-view__subtitle">
          {queueCount > 0
            ? `${queueCount} face${queueCount === 1 ? "" : "s"} waiting for your confirmation`
            : "All caught up"}
        </p>
      </header>
      {loading && items.length === 0 ? (
        <p className="queue-view__loading">Loading review queue…</p>
      ) : (
        <UncertainQueue
          items={items}
          onReviewed={(faceId) => handleReviewed(faceId, "confirmed")}
          onSkipped={(faceId) => handleReviewed(faceId, "skipped")}
          onDismissed={(faceId) => handleReviewed(faceId, "dismissed")}
          onError={handleError}
        />
      )}
    </div>
  );
}
