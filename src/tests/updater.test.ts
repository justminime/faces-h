import { describe, beforeEach, expect, it, vi } from "vitest";
import { check } from "@tauri-apps/plugin-updater";
import { relaunch } from "@tauri-apps/plugin-process";
import { useUpdaterStore } from "../store/updater";
import { useToastStore } from "../store/toast";

vi.mock("@tauri-apps/plugin-updater", () => ({ check: vi.fn() }));
vi.mock("@tauri-apps/plugin-process", () => ({ relaunch: vi.fn() }));

describe("useUpdaterStore (#180)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useUpdaterStore.setState({ available: null, checking: false, installing: false, progress: -1 });
    useToastStore.setState({ toasts: [] });
  });

  it("sets available when an update is found (silent startup check)", async () => {
    vi.mocked(check).mockResolvedValue({ version: "0.6.0" } as never);
    await useUpdaterStore.getState().checkForUpdates(false);
    expect(useUpdaterStore.getState().available).toEqual({ version: "0.6.0" });
    expect(useToastStore.getState().toasts).toHaveLength(0);
  });

  it("stays silent when no update is found and the check was automatic", async () => {
    vi.mocked(check).mockResolvedValue(null);
    await useUpdaterStore.getState().checkForUpdates(false);
    expect(useUpdaterStore.getState().available).toBeNull();
    expect(useToastStore.getState().toasts).toHaveLength(0);
  });

  it("toasts 'up to date' when no update is found on a manual check", async () => {
    vi.mocked(check).mockResolvedValue(null);
    await useUpdaterStore.getState().checkForUpdates(true);
    expect(useToastStore.getState().toasts[0]?.message).toMatch(/latest version/i);
  });

  it("toasts an error when the manual check itself fails", async () => {
    vi.mocked(check).mockRejectedValue(new Error("network error"));
    await useUpdaterStore.getState().checkForUpdates(true);
    expect(useToastStore.getState().toasts[0]?.message).toMatch(/could not check/i);
  });

  it("a failed automatic check stays silent (no toast)", async () => {
    vi.mocked(check).mockRejectedValue(new Error("network error"));
    await useUpdaterStore.getState().checkForUpdates(false);
    expect(useToastStore.getState().toasts).toHaveLength(0);
  });

  it("installUpdate downloads, installs, and relaunches", async () => {
    const downloadAndInstall = vi.fn().mockImplementation(async (cb) => {
      cb({ event: "Started", data: { contentLength: 1000 } });
      cb({ event: "Progress", data: { chunkLength: 500 } });
      cb({ event: "Finished" });
    });
    useUpdaterStore.setState({ available: { version: "0.6.0", downloadAndInstall } as never });

    await useUpdaterStore.getState().installUpdate();

    expect(downloadAndInstall).toHaveBeenCalled();
    expect(relaunch).toHaveBeenCalled();
    expect(useUpdaterStore.getState().progress).toBe(100);
  });

  it("installUpdate surfaces a toast and resets state if the install fails", async () => {
    const downloadAndInstall = vi.fn().mockRejectedValue(new Error("boom"));
    useUpdaterStore.setState({ available: { version: "0.6.0", downloadAndInstall } as never });

    await useUpdaterStore.getState().installUpdate();

    expect(relaunch).not.toHaveBeenCalled();
    expect(useUpdaterStore.getState().installing).toBe(false);
    expect(useToastStore.getState().toasts[0]?.message).toMatch(/failed to install/i);
  });

  it("dismiss clears the available update", () => {
    useUpdaterStore.setState({ available: { version: "0.6.0" } as never });
    useUpdaterStore.getState().dismiss();
    expect(useUpdaterStore.getState().available).toBeNull();
  });
});
