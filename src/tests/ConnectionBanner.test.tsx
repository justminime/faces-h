import { describe, it, expect, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { ConnectionBanner } from "../components/ConnectionBanner";
import { useConnectionStore } from "../store/connection";
import { useUIStore } from "../store/ui";

beforeEach(() => {
  useConnectionStore.getState().reset();
  useUIStore.setState({ modelDownloadProgress: null });
});

describe("ConnectionBanner (#118)", () => {
  it("shows the engine-starting message with the first-launch explanation", () => {
    render(<ConnectionBanner />);
    expect(
      screen.getByText(
        "Starting the face engine… first launch after an install can take 1–2 minutes (Windows scans the new program).",
      ),
    ).toBeInTheDocument();
  });

  it("shows the retry attempt while connecting", () => {
    useConnectionStore.setState({ phase: "connecting", attempt: 7 });
    render(<ConnectionBanner />);
    expect(screen.getByText("Connecting to the engine… (attempt 7)")).toBeInTheDocument();
  });

  it("shows model download progress during startup", () => {
    useConnectionStore.setState({ phase: "connecting" });
    useUIStore.setState({ modelDownloadProgress: 0.43 });
    render(<ConnectionBanner />);
    expect(screen.getByText("Downloading the face model… 43%")).toBeInTheDocument();
  });

  it("shows loading-library once the engine is reachable", () => {
    useConnectionStore.setState({ phase: "loading-library" });
    render(<ConnectionBanner />);
    expect(screen.getByText("Loading your library…")).toBeInTheDocument();
  });

  it("renders nothing when connected", () => {
    useConnectionStore.setState({ phase: "connected" });
    render(<ConnectionBanner />);
    expect(screen.queryByTestId("connection-banner")).not.toBeInTheDocument();
  });

  it("does not show a completed model download over the lost message", () => {
    useConnectionStore.setState({ phase: "lost" });
    useUIStore.setState({ modelDownloadProgress: 0.5 });
    render(<ConnectionBanner />);
    expect(
      screen.getByText("Connection to the engine lost — reconnecting…"),
    ).toBeInTheDocument();
  });

  it("shows the mid-session lost message", () => {
    useConnectionStore.setState({ phase: "lost" });
    render(<ConnectionBanner />);
    expect(
      screen.getByText("Connection to the engine lost — reconnecting…"),
    ).toBeInTheDocument();
  });

  it("shows a persistent error state as an alert when the engine failed", () => {
    useConnectionStore.setState({ phase: "failed" });
    render(<ConnectionBanner />);
    const banner = screen.getByRole("alert");
    expect(banner).toHaveTextContent("The engine failed to start — check the logs.");
  });
});
