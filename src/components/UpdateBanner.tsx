import { useUpdaterStore } from "../store/updater";
import "./UpdateBanner.css";

/** Update notification banner (#180) — appears when a new release is found
 *  (auto-checked at startup, or via Help > Check for Updates…). Installing
 *  runs the NSIS installer in passive mode under the hood, so unlike a
 *  manually downloaded installer it never shows the "uninstall previous
 *  version?" prompt; relaunch() restarts straight into the new version. */
export function UpdateBanner() {
  const available = useUpdaterStore((s) => s.available);
  const installing = useUpdaterStore((s) => s.installing);
  const progress = useUpdaterStore((s) => s.progress);
  const installUpdate = useUpdaterStore((s) => s.installUpdate);
  const dismiss = useUpdaterStore((s) => s.dismiss);

  if (!available) return null;

  return (
    <div className="update-banner" role="status">
      <span className="update-banner__text">
        {installing
          ? `Installing update…${progress >= 0 ? ` ${progress}%` : ""}`
          : `Update available — v${available.version}`}
      </span>
      {!installing && (
        <div className="update-banner__actions">
          <button
            type="button"
            className="update-banner__btn"
            onClick={() => void installUpdate()}
          >
            Update &amp; Restart
          </button>
          <button
            type="button"
            className="update-banner__dismiss"
            onClick={dismiss}
            aria-label="Dismiss update notification"
          >
            ✕
          </button>
        </div>
      )}
    </div>
  );
}
