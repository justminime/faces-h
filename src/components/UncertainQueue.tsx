import { useState } from "react";
import type { QueueItem } from "../api/types";
import { confirmFace } from "../api/client";
import { useUIStore } from "../store/ui";
import "./UncertainQueue.css";

interface UncertainQueueProps {
  items: QueueItem[];
  onReviewed: (faceId: number) => void;
}

interface PickerProps {
  people: { id: number; name: string | null }[];
  onPick: (personId: number) => void;
  onClose: () => void;
}

function PersonPicker({ people, onPick, onClose }: PickerProps) {
  return (
    <div className="uq-picker" role="dialog" aria-label="Choose a person">
      <p className="uq-picker__prompt">Who is this?</p>
      <ul className="uq-picker__list">
        {people.map((p) => (
          <li key={p.id}>
            <button className="uq-picker__item" onClick={() => onPick(p.id)}>
              {p.name ?? "Unnamed"}
            </button>
          </li>
        ))}
      </ul>
      <button className="uq-picker__cancel" onClick={onClose}>
        Cancel
      </button>
    </div>
  );
}

interface CardProps {
  item: QueueItem;
  baseUrl: string;
  onReviewed: (faceId: number) => void;
}

function QueueCard({ item, baseUrl, onReviewed }: CardProps) {
  const people = useUIStore((s) => s.people);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  async function handleConfirm(personId: number) {
    if (busy) return;
    setBusy(true);
    try {
      await confirmFace(item.face_id, personId);
      onReviewed(item.face_id);
    } finally {
      setBusy(false);
      setPickerOpen(false);
    }
  }

  const suggestedName = item.suggested_person_name ?? "Unknown";
  const conf =
    item.assign_conf != null ? Math.round(item.assign_conf * 100) : null;

  return (
    <article
      className="uq-card"
      data-testid={`queue-card-${item.face_id}`}
      aria-label={`Uncertain face ${item.face_id}`}
    >
      <img
        className="uq-card__crop"
        src={`${baseUrl}${item.face_crop_url}`}
        alt={`Face ${item.face_id} crop`}
      />
      <div className="uq-card__info">
        <p className="uq-card__suggestion">
          {item.suggested_person_id != null
            ? `Looks like ${suggestedName}${conf != null ? ` (${conf}%)` : ""}`
            : "No match found"}
        </p>
      </div>
      <div className="uq-card__actions">
        {item.suggested_person_id != null && (
          <button
            className="uq-card__btn uq-card__btn--confirm"
            disabled={busy}
            onClick={() => void handleConfirm(item.suggested_person_id!)}
          >
            Yes, this is {suggestedName}
          </button>
        )}
        <button
          className="uq-card__btn uq-card__btn--pick"
          disabled={busy}
          onClick={() => setPickerOpen(true)}
        >
          No, someone else
        </button>
        <button
          className="uq-card__btn uq-card__btn--skip"
          disabled={busy}
          onClick={() => onReviewed(item.face_id)}
        >
          Skip
        </button>
      </div>

      {pickerOpen && (
        <PersonPicker
          people={people}
          onPick={(id) => void handleConfirm(id)}
          onClose={() => setPickerOpen(false)}
        />
      )}
    </article>
  );
}

export function UncertainQueue({ items, onReviewed }: UncertainQueueProps) {
  const baseUrl = "";

  if (items.length === 0) {
    return (
      <div className="uq-empty">
        <p>No faces waiting for review.</p>
      </div>
    );
  }

  return (
    <section className="uq-list" aria-label="Uncertain face review queue">
      {items.map((item) => (
        <QueueCard
          key={item.face_id}
          item={item}
          baseUrl={baseUrl}
          onReviewed={onReviewed}
        />
      ))}
    </section>
  );
}
