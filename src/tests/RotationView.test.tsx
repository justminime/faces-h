import { describe, beforeEach, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { RotationView } from "../components/RotationView";
import {
  fetchRotationSuggestions,
  startRotationScan,
  rotatePhotos,
} from "../api/client";

vi.mock("../api/client", () => ({
  fetchRotationSuggestions: vi.fn(),
  startRotationScan: vi.fn(),
  rotatePhotos: vi.fn(),
  photoThumbUrl: (id: number) => `http://t/photos/${id}/thumbnail`,
}));

const suggestions = [
  {
    id: 1,
    path: "C:/g/sideways.jpg",
    folder: "C:/g",
    filename: "sideways.jpg",
    file_size: 500_000,
    degrees: 90,
    source: "faces" as const,
    is_network: false,
    rotatable: true,
  },
  {
    id: 2,
    path: "\\\\nas\\share\\net.jpg",
    folder: "\\\\nas\\share",
    filename: "net.jpg",
    file_size: 300_000,
    degrees: 180,
    source: "exif" as const,
    is_network: true,
    rotatable: true,
  },
];

describe("RotationView (#160)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchRotationSuggestions).mockResolvedValue(suggestions);
    vi.mocked(startRotationScan).mockResolvedValue({ status: "started" });
    vi.mocked(rotatePhotos).mockResolvedValue({
      rotated: 2,
      recycled: 1,
      permanent: 1,
      failed: [],
    });
  });

  it("lists suggestions with before/after previews, pre-selected", async () => {
    render(<RotationView />);
    await waitFor(() => screen.getByText("sideways.jpg"));
    expect(screen.getByText("net.jpg")).toBeInTheDocument();
    expect(screen.getAllByAltText("Current")).toHaveLength(2);
    expect(screen.getAllByAltText(/after rotation/i)).toHaveLength(2);
    // Both rotatable suggestions start selected.
    const checkboxes = screen.getAllByRole("checkbox") as HTMLInputElement[];
    expect(checkboxes.every((c) => c.checked)).toBe(true);
  });

  it("Scan for sideways photos triggers the background scan", async () => {
    render(<RotationView />);
    await waitFor(() => screen.getByText("sideways.jpg"));
    fireEvent.click(screen.getByRole("button", { name: /scan for sideways photos/i }));
    await waitFor(() => expect(startRotationScan).toHaveBeenCalled());
  });

  it("confirming rotation warns about network files and calls rotatePhotos", async () => {
    render(<RotationView />);
    await waitFor(() => screen.getByText("sideways.jpg"));

    fireEvent.click(screen.getByRole("button", { name: /rotate 2 selected/i }));
    expect(screen.getByRole("dialog", { name: /confirm rotation/i })).toBeInTheDocument();
    expect(screen.getByText(/typically skip the/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /rotate now/i }));
    await waitFor(() =>
      expect(rotatePhotos).toHaveBeenCalledWith([
        { photo_id: 1, degrees: 90 },
        { photo_id: 2, degrees: 180 },
      ]),
    );
  });

  it("shows the empty state when there are no suggestions", async () => {
    vi.mocked(fetchRotationSuggestions).mockResolvedValue([]);
    render(<RotationView />);
    await waitFor(() =>
      expect(screen.getByText(/no sideways photos found/i)).toBeInTheDocument(),
    );
  });
});
