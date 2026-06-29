import { useState, useEffect } from "react";
import { open } from "@tauri-apps/plugin-dialog";
import { fetchModelsStatus, startScan } from "../api/client";
import { useUIStore } from "../store/ui";
import "./Onboarding.css";

export const ONBOARDING_KEY = "onboarding_complete";

type Step = "welcome" | "folder" | "download" | "starting";

interface OnboardingProps {
  onComplete: () => void;
}

export function Onboarding({ onComplete }: OnboardingProps) {
  const [step, setStep] = useState<Step>("welcome");
  const [folderPath, setFolderPath] = useState<string>("");
  const [modelsReady, setModelsReady] = useState<boolean | null>(null);
  const modelDownloadProgress = useUIStore((s) => s.modelDownloadProgress);

  async function handlePickFolder() {
    try {
      const selected = await open({ directory: true, multiple: false });
      if (typeof selected === "string" && selected.length > 0) {
        setFolderPath(selected);
      }
    } catch {
      // not in Tauri — no-op
    }
  }

  async function handleStartScanning() {
    try {
      const status = await fetchModelsStatus();
      if (!status.ready) {
        setModelsReady(false);
        setStep("download");
        return;
      }
    } catch {
      // sidecar not up — proceed optimistically
    }
    setModelsReady(true);
    await triggerScan();
  }

  async function handleDownloadComplete() {
    await triggerScan();
  }

  async function triggerScan() {
    setStep("starting");
    try {
      await startScan(folderPath);
    } catch {
      // sidecar not reachable — still complete onboarding
    }
    localStorage.setItem(ONBOARDING_KEY, "1");
    onComplete();
  }

  const downloadPct =
    modelDownloadProgress !== null ? Math.round(modelDownloadProgress * 100) : 0;

  // Auto-advance from download step once progress reaches 100%
  useEffect(() => {
    if (step === "download" && modelDownloadProgress !== null && modelDownloadProgress >= 1) {
      void handleDownloadComplete();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [modelDownloadProgress, step]);

  if (step === "welcome") {
    return (
      <div className="onboarding" data-testid="onboarding-welcome">
        <div className="onboarding__card">
          <h1 className="onboarding__title">faces-h</h1>
          <p className="onboarding__tagline">
            Organize your photo library by the faces in it — entirely on your device.
          </p>
          <button
            className="onboarding__btn onboarding__btn--primary"
            onClick={() => setStep("folder")}
          >
            Get started
          </button>
        </div>
      </div>
    );
  }

  if (step === "folder") {
    return (
      <div className="onboarding" data-testid="onboarding-folder">
        <div className="onboarding__card">
          <h2 className="onboarding__title">Choose your photo folder</h2>
          <p className="onboarding__tagline">
            Select the folder faces-h should scan. Sub-folders are included automatically.
          </p>
          <button
            className="onboarding__btn onboarding__btn--secondary"
            onClick={() => void handlePickFolder()}
          >
            Browse…
          </button>
          {folderPath && (
            <p className="onboarding__path" data-testid="selected-path">
              {folderPath}
            </p>
          )}
          <button
            className="onboarding__btn onboarding__btn--primary"
            disabled={!folderPath}
            onClick={() => void handleStartScanning()}
            data-testid="start-scanning-btn"
          >
            Start scanning
          </button>
        </div>
      </div>
    );
  }

  if (step === "download") {
    return (
      <div className="onboarding" data-testid="onboarding-download">
        <div className="onboarding__card">
          <h2 className="onboarding__title">Downloading face recognition model</h2>
          <p className="onboarding__tagline">
            Downloading face recognition model (300 MB) — this happens only once.
          </p>
          <div
            className="onboarding__progress-track"
            role="progressbar"
            aria-valuenow={downloadPct}
            aria-valuemin={0}
            aria-valuemax={100}
          >
            <div
              className="onboarding__progress-bar"
              style={{ width: `${downloadPct}%` }}
            />
          </div>
          <p className="onboarding__progress-label">{downloadPct}%</p>
          {modelsReady === false && downloadPct < 100 && (
            <button
              className="onboarding__btn onboarding__btn--ghost"
              onClick={() => void handleDownloadComplete()}
            >
              Continue anyway
            </button>
          )}
        </div>
      </div>
    );
  }

  // "starting" step — brief transition
  return (
    <div className="onboarding" data-testid="onboarding-starting">
      <div className="onboarding__card">
        <p className="onboarding__tagline">Starting scan…</p>
      </div>
    </div>
  );
}
