import { describe, beforeEach, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { NamingModal } from "../components/NamingModal";
import { renamePerson } from "../api/client";

vi.mock("../api/client", () => ({
  renamePerson: vi.fn(),
}));

const SAMPLE_SRCS = ["/face1.jpg", "/face2.jpg"];

const defaultProps = {
  personId: 1,
  sampleFaceSrcs: SAMPLE_SRCS,
  existingNames: ["Bob", "Carol"],
  onSaved: vi.fn(),
  onSkip: vi.fn(),
};

describe("NamingModal", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(renamePerson).mockResolvedValue({ id: 1, name: "Alice" });
  });

  it("renders face crop grid", () => {
    render(<NamingModal {...defaultProps} />);
    expect(screen.getAllByRole("img")).toHaveLength(SAMPLE_SRCS.length);
  });

  it("typing a name enables Save button", () => {
    render(<NamingModal {...defaultProps} />);
    expect(screen.getByRole("button", { name: /save/i })).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/person name/i), { target: { value: "Alice" } });
    expect(screen.getByRole("button", { name: /save/i })).not.toBeDisabled();
  });

  it("submitting calls renamePerson and onSaved", async () => {
    const onSaved = vi.fn();
    render(<NamingModal {...defaultProps} onSaved={onSaved} />);
    fireEvent.change(screen.getByLabelText(/person name/i), { target: { value: "Alice" } });
    fireEvent.click(screen.getByRole("button", { name: /save/i }));
    await waitFor(() => expect(renamePerson).toHaveBeenCalledWith(1, "Alice"));
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith("Alice"));
  });

  it("Skip closes without saving", () => {
    const onSkip = vi.fn();
    render(<NamingModal {...defaultProps} onSkip={onSkip} />);
    fireEvent.click(screen.getByRole("button", { name: /skip/i }));
    expect(onSkip).toHaveBeenCalled();
    expect(renamePerson).not.toHaveBeenCalled();
  });
});
