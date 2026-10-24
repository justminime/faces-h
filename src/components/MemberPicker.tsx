import { useEffect, useState } from "react";
import { fetchCandidates, type MemberCandidate } from "../api/client";
import "./MemberPicker.css";

interface MemberPickerProps {
  /** Rank members for this face, or for this whole cluster. */
  target: { faceId: number } | { personId: number };
  value: MemberCandidate | null;
  onChange: (member: MemberCandidate | null) => void;
  autoFocus?: boolean;
}

/** Shown before the match % so the best guesses stand out. */
const TOP = 3;

function label(c: MemberCandidate, star: boolean): string {
  const parts = [c.name];
  if (c.heb_name) parts.push(c.heb_name);
  if (c.birth_year) parts.push(String(c.birth_year));
  const pct = c.similarity != null ? ` — ${Math.round(c.similarity * 100)}%` : "";
  return `${star ? "★ " : ""}${parts.join(" · ")}${pct}${c.current ? " (current)" : ""}`;
}

/** Dropdown of family-list members only (#198) — no free text, so no new
 *  names. Closest match first, with its %, then everyone else by name. */
export function MemberPicker({ target, value, onChange, autoFocus }: MemberPickerProps) {
  const [candidates, setCandidates] = useState<MemberCandidate[] | null>(null);
  const key = "faceId" in target ? `f${target.faceId}` : `p${target.personId}`;

  useEffect(() => {
    let alive = true;
    setCandidates(null);
    fetchCandidates(target)
      .then((c) => alive && setCandidates(c))
      .catch(() => alive && setCandidates([]));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `key` identifies the target
  }, [key]);

  if (candidates === null) {
    return <p className="member-picker__loading">Finding the closest matches…</p>;
  }

  const scored = candidates.filter((c) => c.similarity != null);
  const rest = candidates.filter((c) => c.similarity == null);

  return (
    <select
      className="member-picker"
      aria-label="Family member"
      dir="auto"
      value={value?.id ?? ""}
      autoFocus={autoFocus}
      onChange={(e) => {
        const id = Number(e.target.value);
        onChange(candidates.find((c) => c.id === id) ?? null);
      }}
    >
      <option value="">Choose who this is…</option>
      {scored.length > 0 && (
        <optgroup label="Best matches">
          {scored.map((c, i) => (
            <option key={c.id} value={c.id}>
              {label(c, i < TOP)}
            </option>
          ))}
        </optgroup>
      )}
      <optgroup label={scored.length > 0 ? "Everyone else" : "Family"}>
        {rest.map((c) => (
          <option key={c.id} value={c.id}>
            {label(c, false)}
          </option>
        ))}
      </optgroup>
    </select>
  );
}
