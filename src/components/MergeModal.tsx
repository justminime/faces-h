import { useState } from "react";
import { mergePeople } from "../api/client";
import { Medallion } from "./Medallion";
import type { Person } from "../types";
import "./MergeModal.css";

interface MergeModalProps {
  sourcePerson: Person;
  people: Person[];
  onMerged: (survivingId: number) => void;
  onCancel: () => void;
}

export function MergeModal({
  sourcePerson,
  people,
  onMerged,
  onCancel,
}: MergeModalProps) {
  const [targetId, setTargetId] = useState<number | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [merging, setMerging] = useState(false);

  const targetPerson = people.find((p) => p.id === targetId) ?? null;

  const handleMerge = async () => {
    if (!targetId) return;
    if (!confirmed) {
      setConfirmed(true);
      return;
    }
    setMerging(true);
    try {
      const result = await mergePeople(sourcePerson.id, targetId);
      onMerged(result.surviving_id);
    } finally {
      setMerging(false);
    }
  };

  const selectTarget = (id: number) => {
    setTargetId(id);
    setConfirmed(false);
  };

  return (
    <div role="dialog" aria-modal="true" className="merge-modal">
      <h2 className="merge-modal__title">Merge into another person</h2>

      <div className="merge-modal__source">
        <Medallion
          src={sourcePerson.avatarSrc}
          alt={sourcePerson.name ?? "Unknown"}
          size={40}
        />
        <span className="merge-modal__source-name">
          {sourcePerson.name ?? "Unknown"}
        </span>
      </div>

      <ul className="merge-modal__list">
        {people
          .filter((p) => p.id !== sourcePerson.id)
          .map((p) => (
            <li key={p.id}>
              <button
                type="button"
                className={`merge-modal__person${targetId === p.id ? " merge-modal__person--selected" : ""}`}
                onClick={() => selectTarget(p.id)}
              >
                <Medallion
                  src={p.avatarSrc}
                  alt={p.name ?? "Unknown"}
                  size={32}
                  selected={targetId === p.id}
                />
                <span>{p.name ?? "Unknown"}</span>
              </button>
            </li>
          ))}
      </ul>

      {targetPerson !== null && (
        <p className="merge-modal__confirm-text">
          {confirmed
            ? `Merge "${sourcePerson.name ?? "Unknown"}" into "${targetPerson.name ?? "Unknown"}"? Cannot be undone.`
            : `"${targetPerson.name ?? "Unknown"}" will be the surviving person.`}
        </p>
      )}

      <div className="merge-modal__actions">
        <button
          type="button"
          className="merge-modal__btn merge-modal__btn--danger"
          onClick={handleMerge}
          disabled={!targetId || merging}
        >
          {confirmed ? "Confirm Merge" : "Merge"}
        </button>
        <button type="button" className="merge-modal__btn" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </div>
  );
}
