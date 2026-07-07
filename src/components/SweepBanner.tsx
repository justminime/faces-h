import { useSweepStore } from "../store/sweep";
import "./SweepBanner.css";

/**
 * Subtle "the app is doing something" indicator while a background sweep is
 * in progress (#184) — shown from the moment a `sweep_started` WebSocket
 * event arrives (naming, confirming, or merging a person) until the matching
 * `sweep_complete`. Purely visual: it does not affect what gets swept or
 * when faces are auto-assigned (see `sidecar/services/reeval.py`).
 *
 * Deliberately a quieter pill rather than a toast — sweeps take a few
 * seconds, and toasts vanish before the user would notice one appearing.
 */
export function SweepBanner() {
  const sweeping = useSweepStore((s) => s.sweeping);

  if (!sweeping) return null;

  const label = sweeping.personName
    ? `Looking for more matches for ${sweeping.personName}…`
    : "Looking for more matches…";

  return (
    <div className="sweep-banner" role="status" data-testid="sweep-banner">
      <span className="sweep-banner__spinner" aria-hidden="true" />
      <span className="sweep-banner__msg">{label}</span>
    </div>
  );
}
