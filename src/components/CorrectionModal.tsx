import { useState } from "react";
import { correctFace, personForMember, type MemberCandidate } from "../api/client";
import type { Person } from "../types";
import { useFamilyStore } from "../store/family";
import { MemberPicker } from "./MemberPicker";
import "./CorrectionModal.css";

interface CorrectionModalProps {
  faceId: number;
  photoId: number;
  people: Person[];
  onCorrected: () => void;
  onClose: () => void;
}

export function CorrectionModal({
  faceId,
  photoId,
  people,
  onCorrected,
  onClose,
}: CorrectionModalProps) {
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [member, setMember] = useState<MemberCandidate | null>(null);
  // #198: with a family list loaded, pick a member — never free text.
  const familyLoaded = useFamilyStore((s) => s.loaded);

  const filtered = people.filter((p) =>
    (p.name ?? "").toLowerCase().includes(query.toLowerCase()),
  );

  async function submit(newPersonId: number | null) {
    if (busy) return;
    setBusy(true);
    try {
      await correctFace(photoId, faceId, newPersonId);
      onCorrected();
    } finally {
      setBusy(false);
    }
  }

  async function submitMember(m: MemberCandidate) {
    if (busy) return;
    setBusy(true);
    try {
      const personId = m.person_id ?? (await personForMember(m.id));
      await correctFace(photoId, faceId, personId);
      onCorrected();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      className="correction-modal-overlay"
      role="dialog"
      aria-modal="true"
      aria-label="Correct person"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="correction-modal">
        <h2 className="correction-modal__title">Who is this person?</h2>

        {familyLoaded ? (
          <>
            <MemberPicker target={{ faceId }} value={member} onChange={setMember} autoFocus />
            <button
              className="correction-modal__save"
              disabled={busy || member === null}
              onClick={() => member && void submitMember(member)}
            >
              Save
            </button>
            <button
              className="correction-modal__item correction-modal__item--unknown"
              disabled={busy}
              onClick={() => void submit(null)}
            >
              Unknown person
            </button>
          </>
        ) : (
        <>
        <input
          className="correction-modal__search"
          type="text"
          placeholder="Search people…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label="Search people"
          autoFocus
        />

        <ul className="correction-modal__list" role="listbox">
          <li>
            <button
              className="correction-modal__item correction-modal__item--unknown"
              role="option"
              aria-selected={false}
              disabled={busy}
              onClick={() => void submit(null)}
            >
              Unknown person
            </button>
          </li>
          {filtered.map((p) => (
            <li key={p.id}>
              <button
                className="correction-modal__item"
                role="option"
                aria-selected={false}
                disabled={busy}
                onClick={() => void submit(p.id)}
              >
                {p.name ?? "Unnamed"}
              </button>
            </li>
          ))}
        </ul>
        </>
        )}

        <button
          className="correction-modal__cancel"
          onClick={onClose}
          disabled={busy}
        >
          Cancel
        </button>
      </div>
    </div>
  );
}
