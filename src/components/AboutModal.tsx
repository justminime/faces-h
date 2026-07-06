import "./AboutModal.css";

interface AboutModalProps {
  version: string;
  onClose: () => void;
}

/** In-app About dialog (#171) — reachable from the native Help menu and the
 *  sidebar ··· menu. Description text matches tauri.conf.json's
 *  bundle.shortDescription so the two stay in sync. */
export function AboutModal({ version, onClose }: AboutModalProps) {
  return (
    <div
      className="about-modal__overlay"
      role="dialog"
      aria-label="About faces-h"
      onClick={onClose}
    >
      <div className="about-modal" onClick={(e) => e.stopPropagation()}>
        <img src="/icon.svg" alt="" className="about-modal__logo" aria-hidden="true" />
        <h2 className="about-modal__name">faces-h</h2>
        <p className="about-modal__version">Version {version}</p>
        <p className="about-modal__description">
          Local face recognition photo organizer. All processing happens on
          your device — no cloud, no account, no uploads.
        </p>
        <div className="about-modal__links">
          <a href="https://shifth.com/faces-h" target="_blank" rel="noreferrer">
            shifth.com/faces-h
          </a>
          <a href="https://github.com/justminime/faces-h" target="_blank" rel="noreferrer">
            GitHub
          </a>
        </div>
        <button type="button" className="about-modal__close" onClick={onClose}>
          Close
        </button>
      </div>
    </div>
  );
}
