import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Onboarding, ONBOARDING_KEY } from "../components/Onboarding";

vi.mock("@tauri-apps/plugin-dialog", () => ({ open: vi.fn() }));
vi.mock("../api/client", () => ({
  fetchModelsStatus: vi.fn(),
  startScan: vi.fn(),
  preloadModels: vi.fn(),
}));

import { open } from "@tauri-apps/plugin-dialog";
import { fetchModelsStatus, startScan, preloadModels } from "../api/client";
import { useUIStore } from "../store/ui";

const mockOpen = vi.mocked(open);
const mockFetchModelsStatus = vi.mocked(fetchModelsStatus);
const mockStartScan = vi.mocked(startScan);
const mockPreloadModels = vi.mocked(preloadModels);

const READY = { ready: true, downloading: false, progress: 1 };
const NOT_READY = { ready: false, downloading: true, progress: 0 };

beforeEach(() => {
  localStorage.clear();
  vi.clearAllMocks();
  mockStartScan.mockResolvedValue({ status: "started" });
  mockFetchModelsStatus.mockResolvedValue(READY);
  mockPreloadModels.mockResolvedValue({ status: "started" });
  useUIStore.setState({ modelDownloadProgress: null, scanVersion: 0, scanProgress: null });
});

/** The app opens on an "engine-wait" splash and advances to "welcome" once the
 *  sidecar responds (a 2 s poll). Wait that out before driving the flow. */
async function reachWelcome(): Promise<void> {
  await waitFor(() => expect(screen.getByTestId("onboarding-welcome")).toBeTruthy(), {
    timeout: 4000,
  });
}

describe("Onboarding", () => {
  it("advances from engine-wait to the welcome screen once the sidecar responds", async () => {
    render(<Onboarding onComplete={vi.fn()} />);
    await reachWelcome();
    expect(screen.getByTestId("onboarding-welcome")).toBeTruthy();
  });

  it("treats the localStorage flag as the skip signal", () => {
    localStorage.setItem(ONBOARDING_KEY, "1");
    const shouldShow = localStorage.getItem(ONBOARDING_KEY) === null;
    expect(shouldShow).toBe(false);
  });

  it("Start scanning button is disabled until a folder is selected", async () => {
    const user = userEvent.setup();
    render(<Onboarding onComplete={vi.fn()} />);
    await reachWelcome();

    await user.click(screen.getByText("Get started"));
    const btn = screen.getByTestId("start-scanning-btn") as HTMLButtonElement;
    expect(btn.disabled).toBe(true);

    mockOpen.mockResolvedValueOnce("/Users/me/Photos");
    await user.click(screen.getByText("Browse…"));
    await waitFor(() => expect(screen.getByTestId("selected-path")).toBeTruthy());
    expect(btn.disabled).toBe(false);
  });

  it("skips the download step and scans immediately when models are ready", async () => {
    const user = userEvent.setup();
    const onComplete = vi.fn();
    mockOpen.mockResolvedValueOnce("/Users/me/Photos");

    render(<Onboarding onComplete={onComplete} />);
    await reachWelcome();
    await user.click(screen.getByText("Get started"));
    await user.click(screen.getByText("Browse…"));
    await waitFor(() => screen.getByTestId("selected-path"));
    await user.click(screen.getByTestId("start-scanning-btn"));

    await waitFor(() => expect(onComplete).toHaveBeenCalledOnce());
    expect(mockStartScan).toHaveBeenCalledTimes(1);
    expect(screen.queryByTestId("onboarding-download")).toBeNull();
  });

  it("starts the scan exactly once when the model becomes ready (double-scan guard)", async () => {
    const user = userEvent.setup();
    const onComplete = vi.fn();
    mockOpen.mockResolvedValueOnce("/Users/me/Photos");
    // engine-wait poll → resolves (advances to welcome);
    // handleStartScanning → not ready (shows the download step);
    // download-step poll → ready.
    mockFetchModelsStatus
      .mockResolvedValueOnce(READY)
      .mockResolvedValueOnce(NOT_READY)
      .mockResolvedValue(READY);

    render(<Onboarding onComplete={onComplete} />);
    await reachWelcome();
    await user.click(screen.getByText("Get started"));
    await user.click(screen.getByText("Browse…"));
    await waitFor(() => screen.getByTestId("selected-path"));
    await user.click(screen.getByTestId("start-scanning-btn"));
    await waitFor(() => screen.getByTestId("onboarding-download"));

    // WebSocket reports 100% — the >=1 effect fires handleDownloadComplete.
    await act(async () => {
      useUIStore.setState({ modelDownloadProgress: 1 });
    });
    // The status poll also reports ready and tries to start again; the guard
    // must collapse both ready-signals into a single scan start.
    await waitFor(() => expect(onComplete).toHaveBeenCalled());
    await new Promise((r) => setTimeout(r, 50));

    expect(mockStartScan).toHaveBeenCalledTimes(1);
  });
});
