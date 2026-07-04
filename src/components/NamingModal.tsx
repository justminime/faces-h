import { useState } from "react";
import { renamePerson, mergePeople } from "../api/client";
import "./NamingModal.css";

interface ExistingPerson {
  id: number;
  name: string;
}

interface NamingModalProps {
  personId: number;
  sampleFaceSrcs: string[];
  existingPeople: ExistingPerson[];
  onSaved: (name: string) => void;
  onSkip: () => void;
}

export function NamingModal({
  personId,
  sampleFaceSrcs,
  existingPeople,
  onSaved,
  onSkip,
}: NamingModalProps) {
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);

  const trimmed = name.trim();

  // Case-insensitive match against existing named people (excluding self)
  const mergeTarget = existingPeople.find(
    (p) => p.id !== personId && p.name.toLowerCase() === trimmed.toLowerCase(),
  ) ?? null;

  const handleSave = async () => {
    if (!trimmed) return;
    setSaving(true);
    try {
      if (mergeTarget) {
        // Merge this unnamed cluster into the existing named person,
        // then delete the now-empty cluster record.
        await mergePeople(personId, mergeTarget.id);
      } else {
        await renamePerson(personId, trimmed);
      }
      onSaved(trimmed);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div role="dialog" aria-modal="true" className="naming-modal">
      <div className="naming-modal__crops">
        {sampleFaceSrcs.map((src, i) => (
          <img
            key={i}
            src={src}
            alt={`Face sample ${i + 1}`}
            className="naming-modal__crop"
          />
        ))}
      </div>
      <input
        type="text"
        list="naming-suggestions"
        value={name}
        onChange={(e) => setName(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter" && trimmed && !saving) void handleSave(); }}
        placeholder="Enter name…"
        className="naming-modal__input"
        aria-label="Person name"
        autoFocus
      />
      <datalist id="naming-suggestions">
        {existingPeople.map((p) => (
          <option key={p.id} value={p.name} />
        ))}
      </datalist>

      {mergeTarget && (
        <p className="naming-modal__merge-hint">
          "{mergeTarget.name}" already exists — saving will merge these two clusters together.
        </p>
      )}

      <div className="naming-modal__actions">
        <button
          type="button"
          className="naming-modal__btn naming-modal__btn--primary"
          onClick={handleSave}
          disabled={!trimmed || saving}
        >
          {mergeTarget ? "Merge" : "Save"}
        </button>
        <button type="button" className="naming-modal__btn" onClick={onSkip}>
          Cancel
        </button>
      </div>
    </div>
  );
}
