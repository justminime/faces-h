import { describe, beforeEach, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { CorrectionModal } from "../components/CorrectionModal";
import { correctFace } from "../api/client";
import type { Person } from "../mocks/data";

vi.mock("../api/client", () => ({
  correctFace: vi.fn(),
}));

const PEOPLE: Person[] = [
  { id: 1, name: "Alice", avatarSrc: "", photoCount: 5 },
  { id: 2, name: "Bob", avatarSrc: "", photoCount: 3 },
];

const defaultProps = {
  faceId: 10,
  photoId: 100,
  people: PEOPLE,
  onCorrected: vi.fn(),
  onClose: vi.fn(),
};

describe("CorrectionModal", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(correctFace).mockResolvedValue({ status: "queued", face_id: 10 });
  });

  it("renders people list and Unknown person option", () => {
    render(<CorrectionModal {...defaultProps} />);
    expect(screen.getByRole("option", { name: "Alice" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Bob" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: /unknown person/i })).toBeInTheDocument();
  });

  it("typing in search filters the people list", () => {
    render(<CorrectionModal {...defaultProps} />);
    fireEvent.change(screen.getByLabelText(/search people/i), {
      target: { value: "ali" },
    });
    expect(screen.getByRole("option", { name: "Alice" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "Bob" })).not.toBeInTheDocument();
  });

  it("clicking a person calls correctFace with their id and closes modal", async () => {
    const onCorrected = vi.fn();
    render(<CorrectionModal {...defaultProps} onCorrected={onCorrected} />);
    fireEvent.click(screen.getByRole("option", { name: "Alice" }));
    await waitFor(() =>
      expect(correctFace).toHaveBeenCalledWith(100, 10, 1),
    );
    await waitFor(() => expect(onCorrected).toHaveBeenCalled());
  });

  it("clicking Unknown person calls correctFace with null", async () => {
    const onCorrected = vi.fn();
    render(<CorrectionModal {...defaultProps} onCorrected={onCorrected} />);
    fireEvent.click(screen.getByRole("option", { name: /unknown person/i }));
    await waitFor(() =>
      expect(correctFace).toHaveBeenCalledWith(100, 10, null),
    );
    await waitFor(() => expect(onCorrected).toHaveBeenCalled());
  });
});
