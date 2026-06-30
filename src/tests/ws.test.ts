import { describe, expect, it, beforeEach } from "vitest";
import { handleMessage } from "../api/ws";
import { useUIStore } from "../store/ui";
import { useToastStore } from "../store/toast";

function msg(obj: unknown): MessageEvent {
  return { data: JSON.stringify(obj) } as MessageEvent;
}

beforeEach(() => {
  useUIStore.setState({ scanProgress: null, scanVersion: 0, modelDownloadProgress: null });
  useToastStore.setState({ toasts: [] });
});

describe("ws handleMessage", () => {
  it("scan_progress sets the progress fraction from scanned/total", () => {
    handleMessage(msg({ type: "scan_progress", scanned: 50, total: 200, eta_seconds: 10 }));
    expect(useUIStore.getState().scanProgress).toBe(0.25);
  });

  it("scan_progress bumps scanVersion so the gallery refreshes live", () => {
    handleMessage(msg({ type: "scan_progress", scanned: 10, total: 100 }));
    expect(useUIStore.getState().scanVersion).toBe(1);
    handleMessage(msg({ type: "scan_progress", scanned: 20, total: 100 }));
    expect(useUIStore.getState().scanVersion).toBe(2);
  });

  it("scan_complete clears progress, bumps version, and toasts", () => {
    useUIStore.setState({ scanProgress: 0.9 });
    handleMessage(msg({ type: "scan_complete", scanned: 12, total: 12 }));
    const ui = useUIStore.getState();
    expect(ui.scanProgress).toBeNull();
    expect(ui.scanVersion).toBe(1);
    const toasts = useToastStore.getState().toasts;
    expect(toasts[toasts.length - 1]?.message).toContain("12");
  });

  it("model_download_progress updates the download fraction", () => {
    handleMessage(msg({ type: "model_download_progress", progress: 0.42 }));
    expect(useUIStore.getState().modelDownloadProgress).toBe(0.42);
  });

  it("ignores malformed payloads without throwing or mutating state", () => {
    expect(() => handleMessage({ data: "not json" } as MessageEvent)).not.toThrow();
    expect(() => handleMessage(msg({ noType: true }))).not.toThrow();
    expect(useUIStore.getState().scanVersion).toBe(0);
  });
});
