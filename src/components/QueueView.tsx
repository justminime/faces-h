import { useCallback, useEffect, useRef, useState } from "react";
import { fetchUncertainQueue, fetchQueueCount } from "../api/client";
import type { QueueItem } from "../api/types";
import { UncertainQueue } from "./UncertainQueue";
import { useQueueStore } from "../store/queue";
import { useUIStore } from "../store/ui";
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

  const handleReviewed = useCallback(
    (faceId: number, skipped: boolean) => {
      if (skipped) skippedRef.current.add(faceId);
      setItems((prev) => {
        const next = prev.filter((i) => i.face_id !== faceId);
        // Page exhausted but more may be waiting server-side — pull the next batch.
        if (next.length === 0) refresh();
        return next;
      });
      if (!skipped) {
        fetchQueueCount()
          .then((c) => setQueueCount(c.count))
          .catch(() => {});
        // Confirming changes photo counts / medallions — reuse the existing
        // sidebar refresh channel.
        useUIStore.getState().bumpScanVersion();
      }
    },
    [refresh, setQueueCount],
  );

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
          onReviewed={(faceId) => handleReviewed(faceId, false)}
          onSkipped={(faceId) => handleReviewed(faceId, true)}
        />
      )}
    </div>
  );
}
