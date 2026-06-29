import { useState } from "react";
import { renamePerson } from "../api/client";
import "./NamingModal.css";

interface NamingModalProps {
  personId: number;
  sampleFaceSrcs: string[];
  existingNames: string[];
  onSaved: (name: string) => void;
  onSkip: () => void;
}

export function NamingModal({
  personId,
  sampleFaceSrcs,
  existingNames,
  onSaved,
  onSkip,
}: NamingModalProps) {
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);

  const trimmed = name.trim();

  const handleSave = async () => {
    if (!trimmed) return;
    setSaving(true);
    try {
      await renamePerson(personId, trimmed);
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
        placeholder="Enter name…"
        className="naming-modal__input"
        aria-label="Person name"
      />
      <datalist id="naming-suggestions">
        {existingNames.map((n) => (
          <option key={n} value={n} />
        ))}
      </datalist>
      <div className="naming-modal__actions">
        <button
          type="button"
          className="naming-modal__btn naming-modal__btn--primary"
          onClick={handleSave}
          disabled={!trimmed || saving}
        >
          Save
        </button>
        <button type="button" className="naming-modal__btn" onClick={onSkip}>
          Skip
        </button>
      </div>
    </div>
  );
}
