import { describe, expect, it, beforeEach, afterEach, vi } from "vitest";
import { handleMessage, resetScanBumpThrottle } from "../api/ws";
import { useUIStore } from "../store/ui";
import { useToastStore } from "../store/toast";
import { useLogStore } from "../store/log";

function msg(obj: unknown): MessageEvent {
  return { data: JSON.stringify(obj) } as MessageEvent;
}

const scanVersion = () => useUIStore.getState().scanVersion;

beforeEach(() => {
  useUIStore.setState({ scanProgress: null, scanVersion: 0, modelDownloadProgress: null });
  useToastStore.setState({ toasts: [] });
  useLogStore.setState({ entries: [] });
  resetScanBumpThrottle();
});

describe("ws handleMessage", () => {
  it("scan_progress sets the progress fraction from scanned/total", () => {
    handleMessage(msg({ type: "scan_progress", scanned: 50, total: 200, eta_seconds: 10 }));
    expect(useUIStore.getState().scanProgress).toBe(0.25);
  });

  it("scan_progress bumps scanVersion so the gallery refreshes live", () => {
    handleMessage(msg({ type: "scan_progress", scanned: 10, total: 100 }));
    expect(scanVersion()).toBe(1);
  });

  it("scan_progress prefers 'processed' over 'scanned' for the fraction (#182)", () => {
    // A rescan of an unchanged library is almost all skips: 'scanned' (new
    // files only) can stay 0 for the whole run while 'processed' (scanned +
    // skipped) correctly reflects the files actually walked.
    handleMessage(msg({ type: "scan_progress", scanned: 0, processed: 50, total: 200 }));
    expect(useUIStore.getState().scanProgress).toBe(0.25);
  });

  it("scan_progress falls back to 'scanned' when 'processed' is absent", () => {
    handleMessage(msg({ type: "scan_progress", scanned: 50, total: 200 }));
    expect(useUIStore.getState().scanProgress).toBe(0.25);
  });

  it("repeated scan_progress ticks with current_file update one line in place, not one per tick (#182)", () => {
    // The filename is folded into the same progress line rather than a
    // separate push — a separate push became the log's "last" entry every
    // tick, which broke upsertLast's kind-matching on the NEXT tick and
    // produced a stuck-looking new line per tick instead of one live one.
    for (let i = 1; i <= 5; i++) {
      handleMessage(
        msg({
          type: "scan_progress",
          processed: i * 10,
          total: 100,
          current_file: `photo_${i}.jpg`,
        }),
      );
    }
    const progressEntries = useLogStore.getState().entries.filter((e) => e.kind === "progress");
    expect(progressEntries).toHaveLength(1);
    expect(progressEntries[0].message).toContain("50 / 100");
    expect(progressEntries[0].message).toContain("photo_5.jpg");
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
    expect(scanVersion()).toBe(0);
  });
});

describe("scan_progress refetch throttle (#110)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("bumps scanVersion at most once within the throttle window", () => {
    handleMessage(msg({ type: "scan_progress", scanned: 10, total: 100 }));
    expect(scanVersion()).toBe(1);

    // A storm of progress events inside the window must not bump again.
    for (let i = 20; i <= 90; i += 10) {
      vi.advanceTimersByTime(500);
      handleMessage(msg({ type: "scan_progress", scanned: i, total: 100 }));
    }
    expect(scanVersion()).toBe(1);
    // ...but progress itself still updates live.
    expect(useUIStore.getState().scanProgress).toBe(0.9);
  });

  it("bumps again once the throttle window has elapsed", () => {
    handleMessage(msg({ type: "scan_progress", scanned: 10, total: 100 }));
    expect(scanVersion()).toBe(1);

    vi.advanceTimersByTime(5_000);
    handleMessage(msg({ type: "scan_progress", scanned: 20, total: 100 }));
    expect(scanVersion()).toBe(2);
  });

  it("scan_complete always bumps immediately, even inside the throttle window", () => {
    handleMessage(msg({ type: "scan_progress", scanned: 10, total: 100 }));
    expect(scanVersion()).toBe(1);

    vi.advanceTimersByTime(100);
    handleMessage(msg({ type: "scan_complete", scanned: 12, total: 12 }));
    expect(scanVersion()).toBe(2);
  });

  it("sweep_complete always bumps immediately, even inside the throttle window", () => {
    handleMessage(msg({ type: "scan_progress", scanned: 10, total: 100 }));
    expect(scanVersion()).toBe(1);

    vi.advanceTimersByTime(100);
    handleMessage(msg({ type: "sweep_complete", moved: 3 }));
    expect(scanVersion()).toBe(2);
  });
});

describe("ws engine log forwarding (#126)", () => {
  it("pushes engine log messages into the activity log with the [engine] tag", async () => {
    const { useLogStore } = await import("../store/log");
    useLogStore.setState({ entries: [] });
    handleMessage(
      msg({ type: "log", source: "engine", level: "warning", message: "migration failed" }),
    );
    const entries = useLogStore.getState().entries;
    expect(entries).toHaveLength(1);
    expect(entries[0].message).toBe("[engine] migration failed");
    expect(entries[0].kind).toBe("warn");
  });

  it("maps info level to info kind and ignores empty messages", async () => {
    const { useLogStore } = await import("../store/log");
    useLogStore.setState({ entries: [] });
    handleMessage(msg({ type: "log", level: "info", message: "scan starting" }));
    handleMessage(msg({ type: "log", level: "error", message: "" }));
    const entries = useLogStore.getState().entries;
    expect(entries).toHaveLength(1);
    expect(entries[0].kind).toBe("info");
  });
});
