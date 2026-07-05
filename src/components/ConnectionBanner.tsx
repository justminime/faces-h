import { useConnectionStore } from "../store/connection";
import { useUIStore } from "../store/ui";
import "./ConnectionBanner.css";

/**
 * Slim status banner across the top of the content area (#118).
 *
 * Shows what the app is doing between window-open and the first data load
 * (engine starting / connecting / model download / loading library), a
 * mid-session reconnect notice, and a persistent error if the engine failed
 * to start. Hidden entirely once connected.
 */
export function ConnectionBanner() {
  const phase = useConnectionStore((s) => s.phase);
  const attempt = useConnectionStore((s) => s.attempt);
  const modelDownloadProgress = useUIStore((s) => s.modelDownloadProgress);

  if (phase === "connected") return null;

  const isFailed = phase === "failed";
  const isStartup =
    phase === "engine-starting" ||
    phase === "connecting" ||
    phase === "loading-library";
  const isDownloading =
    isStartup && modelDownloadProgress !== null && modelDownloadProgress < 1;

  let message: string;
  if (isFailed) {
    message = "The engine failed to start — check the logs.";
  } else if (phase === "lost") {
    message = "Connection to the engine lost — reconnecting…";
  } else if (isDownloading) {
    const pct = Math.round((modelDownloadProgress ?? 0) * 100);
    message = `Downloading the face model… ${pct}%`;
  } else if (phase === "engine-starting") {
    message =
      "Starting the face engine… first launch after an install can take 1–2 minutes (Windows scans the new program).";
  } else if (phase === "connecting") {
    message = `Connecting to the engine… (attempt ${Math.max(attempt, 1)})`;
  } else {
    message = "Loading your library…";
  }

  return (
    <div
      className={`connection-banner${isFailed ? " connection-banner--error" : ""}`}
      role={isFailed ? "alert" : "status"}
      data-testid="connection-banner"
    >
      {isFailed ? (
        <span className="connection-banner__icon" aria-hidden="true">
          ⚠
        </span>
      ) : (
        <span className="connection-banner__spinner" aria-hidden="true" />
      )}
      <span className="connection-banner__msg">{message}</span>
    </div>
  );
}
