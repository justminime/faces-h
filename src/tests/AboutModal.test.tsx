import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { AboutModal } from "../components/AboutModal";

describe("AboutModal (#171)", () => {
  it("shows the app name, description, and given version", () => {
    render(<AboutModal version="0.5.0" onClose={vi.fn()} />);
    expect(screen.getByText("faces-h")).toBeInTheDocument();
    expect(screen.getByText("Version 0.5.0")).toBeInTheDocument();
    expect(screen.getByText(/local face recognition photo organizer/i)).toBeInTheDocument();
  });

  it("Close button calls onClose", () => {
    const onClose = vi.fn();
    render(<AboutModal version="0.5.0" onClose={onClose} />);
    fireEvent.click(screen.getByRole("button", { name: /close/i }));
    expect(onClose).toHaveBeenCalled();
  });

  it("clicking the overlay also calls onClose", () => {
    const onClose = vi.fn();
    render(<AboutModal version="0.5.0" onClose={onClose} />);
    fireEvent.click(screen.getByRole("dialog", { name: /about faces-h/i }));
    expect(onClose).toHaveBeenCalled();
  });
});
