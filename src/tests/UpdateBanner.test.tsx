import { describe, beforeEach, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { UpdateBanner } from "../components/UpdateBanner";
import { useUpdaterStore } from "../store/updater";

describe("UpdateBanner (#180)", () => {
  beforeEach(() => {
    useUpdaterStore.setState({ available: null, checking: false, installing: false, progress: -1 });
  });

  it("renders nothing when no update is available", () => {
    const { container } = render(<UpdateBanner />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows the version and action buttons when an update is available", () => {
    useUpdaterStore.setState({ available: { version: "0.6.0" } as never });
    render(<UpdateBanner />);
    expect(screen.getByText(/update available/i)).toHaveTextContent("0.6.0");
    expect(screen.getByRole("button", { name: /update & restart/i })).toBeInTheDocument();
  });

  it("clicking Update & Restart calls installUpdate", () => {
    const installUpdate = vi.fn();
    useUpdaterStore.setState({ available: { version: "0.6.0" } as never, installUpdate });
    render(<UpdateBanner />);
    fireEvent.click(screen.getByRole("button", { name: /update & restart/i }));
    expect(installUpdate).toHaveBeenCalled();
  });

  it("Dismiss calls dismiss and hides the banner", () => {
    const dismiss = vi.fn();
    useUpdaterStore.setState({ available: { version: "0.6.0" } as never, dismiss });
    render(<UpdateBanner />);
    fireEvent.click(screen.getByRole("button", { name: /dismiss update notification/i }));
    expect(dismiss).toHaveBeenCalled();
  });

  it("shows install progress and hides action buttons while installing", () => {
    useUpdaterStore.setState({
      available: { version: "0.6.0" } as never,
      installing: true,
      progress: 42,
    });
    render(<UpdateBanner />);
    expect(screen.getByText(/installing update… 42%/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /update & restart/i })).not.toBeInTheDocument();
  });
});
