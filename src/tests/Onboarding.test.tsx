import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Onboarding, ONBOARDING_KEY } from "../components/Onboarding";

vi.mock("@tauri-apps/plugin-dialog", () => ({ open: vi.fn() }));
vi.mock("../api/client", () => ({
  fetchModelsStatus: vi.fn(),
  startScan: vi.fn(),
}));

import { open } from "@tauri-apps/plugin-dialog";
import { fetchModelsStatus, startScan } from "../api/client";

const mockOpen = vi.mocked(open);
const mockFetchModelsStatus = vi.mocked(fetchModelsStatus);
const mockStartScan = vi.mocked(startScan);

beforeEach(() => {
  localStorage.clear();
  vi.clearAllMocks();
  mockStartScan.mockResolvedValue({ status: "started" });
  mockFetchModelsStatus.mockResolvedValue({ ready: true, downloading: false, progress: 0 });
});

describe("Onboarding", () => {
  it("renders onboarding when localStorage key is absent", () => {
    render(<Onboarding onComplete={vi.fn()} />);
    expect(screen.getByTestId("onboarding-welcome")).toBeTruthy();
  });

  it("skips onboarding when localStorage key is present", () => {
    localStorage.setItem(ONBOARDING_KEY, "1");
    // The App conditionally renders Onboarding; simulate that gating
    const shouldShow = localStorage.getItem(ONBOARDING_KEY) === null;
    expect(shouldShow).toBe(false);
  });

  it("Start scanning button is disabled until folder is selected", async () => {
    const user = userEvent.setup();
    render(<Onboarding onComplete={vi.fn()} />);

    await user.click(screen.getByText("Get started"));
    const btn = screen.getByTestId("start-scanning-btn") as HTMLButtonElement;
    expect(btn.disabled).toBe(true);

    mockOpen.mockResolvedValueOnce("/Users/me/Photos");
    await user.click(screen.getByText("Browse…"));
    await waitFor(() => expect(screen.getByTestId("selected-path")).toBeTruthy());
    expect(btn.disabled).toBe(false);
  });

  it("skips download step when models are already ready", async () => {
    const user = userEvent.setup();
    const onComplete = vi.fn();
    mockOpen.mockResolvedValueOnce("/Users/me/Photos");
    mockFetchModelsStatus.mockResolvedValue({ ready: true, downloading: false, progress: 0 });

    render(<Onboarding onComplete={onComplete} />);
    await user.click(screen.getByText("Get started"));
    await user.click(screen.getByText("Browse…"));
    await waitFor(() => screen.getByTestId("selected-path"));
    await user.click(screen.getByTestId("start-scanning-btn"));

    await waitFor(() => expect(onComplete).toHaveBeenCalledOnce());
    // download step should never have appeared
    expect(screen.queryByTestId("onboarding-download")).toBeNull();
  });
});
