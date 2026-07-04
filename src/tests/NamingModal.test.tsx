import { describe, beforeEach, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { NamingModal } from "../components/NamingModal";
import { renamePerson, mergePeople } from "../api/client";

vi.mock("../api/client", () => ({
  renamePerson: vi.fn(),
  mergePeople: vi.fn(),
}));

const SAMPLE_SRCS = ["/face1.jpg", "/face2.jpg"];

const defaultProps = {
  personId: 1,
  sampleFaceSrcs: SAMPLE_SRCS,
  existingPeople: [
    { id: 2, name: "Bob" },
    { id: 3, name: "Carol" },
  ],
  onSaved: vi.fn(),
  onSkip: vi.fn(),
};

describe("NamingModal", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(renamePerson).mockResolvedValue({ id: 1, name: "Alice" });
    vi.mocked(mergePeople).mockResolvedValue({ surviving_id: 2, merged_count: 5 });
  });

  it("renders face crop grid", () => {
    render(<NamingModal {...defaultProps} />);
    expect(screen.getAllByRole("img")).toHaveLength(SAMPLE_SRCS.length);
  });

  it("typing a new name enables Save button", () => {
    render(<NamingModal {...defaultProps} />);
    expect(screen.getByRole("button", { name: /save/i })).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/person name/i), { target: { value: "Alice" } });
    expect(screen.getByRole("button", { name: /save/i })).not.toBeDisabled();
  });

  it("submitting a new name calls renamePerson and onSaved", async () => {
    const onSaved = vi.fn();
    render(<NamingModal {...defaultProps} onSaved={onSaved} />);
    fireEvent.change(screen.getByLabelText(/person name/i), { target: { value: "Alice" } });
    fireEvent.click(screen.getByRole("button", { name: /save/i }));
    await waitFor(() => expect(renamePerson).toHaveBeenCalledWith(1, "Alice"));
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith("Alice"));
  });

  it("typing an existing name shows merge hint and Merge button", () => {
    render(<NamingModal {...defaultProps} />);
    fireEvent.change(screen.getByLabelText(/person name/i), { target: { value: "Bob" } });
    expect(screen.getByText(/already exists/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /merge/i })).toBeInTheDocument();
  });

  it("confirming a merge calls mergePeople not renamePerson", async () => {
    const onSaved = vi.fn();
    render(<NamingModal {...defaultProps} onSaved={onSaved} />);
    fireEvent.change(screen.getByLabelText(/person name/i), { target: { value: "Bob" } });
    fireEvent.click(screen.getByRole("button", { name: /merge/i }));
    await waitFor(() => expect(mergePeople).toHaveBeenCalledWith(1, 2));
    expect(renamePerson).not.toHaveBeenCalled();
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith("Bob"));
  });

  it("Cancel closes without saving", () => {
    const onSkip = vi.fn();
    render(<NamingModal {...defaultProps} onSkip={onSkip} />);
    fireEvent.click(screen.getByRole("button", { name: /cancel/i }));
    expect(onSkip).toHaveBeenCalled();
    expect(renamePerson).not.toHaveBeenCalled();
  });
});
