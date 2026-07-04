import { useState, useEffect, useRef } from "react";
import { open } from "@tauri-apps/plugin-dialog";
import { fetchModelsStatus, preloadModels, startScan } from "../api/client";
import { useUIStore } from "../store/ui";
import "./Onboarding.css";

export const ONBOARDING_KEY = "onboarding_complete";

type Step = "engine-wait" | "welcome" | "folder" | "download" | "starting" | "error";

interface OnboardingProps {
  onComplete: () => void;
}

export function Onboarding({ onComplete }: OnboardingProps) {
  const [step, setStep] = useState<Step>("engine-wait");
  const [folderPath, setFolderPath] = useState<string>("");
  const [modelsReady, setModelsReady] = useState<boolean | null>(null);
  const modelDownloadProgress = useUIStore((s) => s.modelDownloadProgress);
  const setModelDownloadProgress = useUIStore((s) => s.setModelDownloadProgress);

  // Poll until the sidecar HTTP server is reachable, then advance to welcome.
  // On first run after an upgrade Windows Defender scans the new binary which
  // can delay startup by 60+ seconds.
  useEffect(() => {
    if (step !== "engine-wait") return;
    const poll = setInterval(async () => {
      try {
        await fetchModelsStatus();
        clearInterval(poll);
        setStep("welcome");
      } catch {
        // sidecar not yet reachable — keep waiting
      }
    }, 2_000);
    return () => clearInterval(poll);
  }, [step]);

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

  const [errorMessage, setErrorMessage] = useState<string>("");

  async function handleStartScanning() {
    try {
      const status = await fetchModelsStatus();
      if (!status.ready) {
        setModelsReady(false);
        setStep("download");
        return;
      }
    } catch {
      setErrorMessage(
        "Cannot reach the faces-h engine. Make sure the app is fully started and try again.",
      );
      setStep("error");
      return;
    }
    setModelsReady(true);
    await triggerScan();
  }

  async function handleDownloadComplete() {
    await triggerScan();
  }

  // Guards against starting the scan more than once: model-ready can be
  // signalled by both the WebSocket progress event and the status poll, which
  // would otherwise fire two concurrent scans — and two recognizers loading the
  // same ONNX model at once fails on Windows with a file-sharing error.
  const scanTriggeredRef = useRef(false);

  async function triggerScan() {
    if (scanTriggeredRef.current) return;
    scanTriggeredRef.current = true;
    setStep("starting");
    try {
      await startScan(folderPath);
      localStorage.setItem(ONBOARDING_KEY, "1");
      onComplete();
    } catch {
      scanTriggeredRef.current = false;
      setErrorMessage(
        "Could not start the scan. The engine may still be loading — please wait a moment and try again.",
      );
      setStep("error");
    }
  }

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const downloadPct =
    modelDownloadProgress !== null ? Math.round(modelDownloadProgress * 100) : null;

  // Auto-advance when WebSocket reports 100%
  useEffect(() => {
    if (step === "download" && modelDownloadProgress !== null && modelDownloadProgress >= 1) {
      void handleDownloadComplete();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [modelDownloadProgress, step]);

  // When the download step appears, trigger the actual model download.
  // Without this call nothing starts — InsightFace only downloads on first use.
  useEffect(() => {
    if (step !== "download") return;
    void preloadModels().catch(() => {
      // sidecar not yet reachable — polling below will retry
    });
  }, [step]);

  // Polling fallback: if WebSocket events aren't arriving, poll /models/status
  // every 2 s so we still advance when the download finishes.
  useEffect(() => {
    if (step !== "download") return;
    pollRef.current = setInterval(async () => {
      try {
        const status = await fetchModelsStatus();
        if (status.ready) {
          clearInterval(pollRef.current!);
          setModelDownloadProgress(1);
          void handleDownloadComplete();
        } else if (typeof status.progress === "number") {
          // Drive the bar from polling too, so it still advances if WebSocket
          // progress events aren't arriving. Only ever move forward, so this
          // never fights a WebSocket update that's further ahead.
          const current = useUIStore.getState().modelDownloadProgress ?? 0;
          if (status.progress > current) setModelDownloadProgress(status.progress);
        }
      } catch {
        // sidecar not yet reachable — keep polling and retry preload
        void preloadModels().catch(() => {});
      }
    }, 2_000);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step]);

  if (step === "engine-wait") {
    return (
      <div className="onboarding" data-testid="onboarding-engine-wait">
        <div className="onboarding__card">
          <img src="/icon.svg" alt="" className="onboarding__logo" aria-hidden="true" />
          <h1 className="onboarding__title">faces-h</h1>
          <p className="onboarding__tagline">Starting engine…</p>
          <div className="onboarding__progress-track onboarding__progress-track--indeterminate">
            <div className="onboarding__progress-bar onboarding__progress-bar--pulse" />
          </div>
          <p className="onboarding__progress-label">
            This may take 1–2 minutes on first launch after an update.
          </p>
        </div>
      </div>
    );
  }

  if (step === "welcome") {
    return (
      <div className="onboarding" data-testid="onboarding-welcome">
        <div className="onboarding__card">
          <img src="/icon.svg" alt="" className="onboarding__logo" aria-hidden="true" />
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
    const isIndeterminate = downloadPct === null;
    const pctLabel = downloadPct !== null ? `${downloadPct}%` : "Starting…";
    return (
      <div className="onboarding" data-testid="onboarding-download">
        <div className="onboarding__card">
          <h2 className="onboarding__title">Downloading face model</h2>
          <p className="onboarding__tagline">
            ~300 MB — this happens only once. Keep the app open.
          </p>
          <div
            className={`onboarding__progress-track${isIndeterminate ? " onboarding__progress-track--indeterminate" : ""}`}
            role="progressbar"
            aria-valuenow={downloadPct ?? undefined}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label="Model download progress"
          >
            <div
              className={`onboarding__progress-bar${isIndeterminate ? " onboarding__progress-bar--pulse" : ""}`}
              style={isIndeterminate ? undefined : { width: `${downloadPct}%` }}
            />
          </div>
          <p className="onboarding__progress-label" data-testid="download-pct">{pctLabel}</p>
          {modelsReady === false && downloadPct !== null && downloadPct < 100 && (
            <button
              className="onboarding__btn onboarding__btn--ghost"
              onClick={() => void handleDownloadComplete()}
            >
              Skip and start scanning
            </button>
          )}
        </div>
      </div>
    );
  }

  if (step === "error") {
    return (
      <div className="onboarding" data-testid="onboarding-error">
        <div className="onboarding__card">
          <h2 className="onboarding__title">Something went wrong</h2>
          <p className="onboarding__tagline onboarding__tagline--error">{errorMessage}</p>
          <button
            className="onboarding__btn onboarding__btn--primary"
            onClick={() => setStep("folder")}
          >
            Try again
          </button>
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
