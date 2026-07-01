import { describe, beforeEach, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { SearchView } from "../components/SearchView";
import { searchPhotos } from "../api/client";
import type { Person } from "../mocks/data";
import type { ApiPhoto } from "../api/types";

vi.mock("../api/client", () => ({
  searchPhotos: vi.fn(),
  photoThumbUrl: (photoId: number) => `http://test/photos/${photoId}/thumbnail?size=256`,
}));

vi.mock("@tauri-apps/api/core", () => ({
  invoke: vi.fn(),
}));

const PEOPLE: Person[] = [
  { id: 1, name: "Alice", avatarSrc: "", photoCount: 5 },
  { id: 2, name: "Bob", avatarSrc: "", photoCount: 3 },
];

const MOCK_PHOTOS: ApiPhoto[] = [
  { id: 10, path: "/photos/img1.jpg", taken_at: null, faces: [{ face_id: 1, person_id: 1, assign_conf: 0.9 }] },
  { id: 11, path: "/photos/img2.jpg", taken_at: null, faces: [{ face_id: 2, person_id: 1, assign_conf: 0.85 }] },
];

describe("SearchView", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(searchPhotos).mockResolvedValue(MOCK_PHOTOS);
  });

  it("adding a person chip updates the query and enables Search button", () => {
    render(<SearchView people={PEOPLE} />);
    const input = screen.getByLabelText(/add person to search/i);
    expect(screen.getByRole("button", { name: /search/i })).toBeDisabled();

    fireEvent.change(input, { target: { value: "Ali" } });
    fireEvent.click(screen.getByRole("option", { name: "Alice" }));

    expect(screen.getByText("Alice")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /search/i })).not.toBeDisabled();
  });

  it("clicking Search calls searchPhotos and renders result grid", async () => {
    render(<SearchView people={PEOPLE} />);
    const input = screen.getByLabelText(/add person to search/i);

    fireEvent.change(input, { target: { value: "Ali" } });
    fireEvent.click(screen.getByRole("option", { name: "Alice" }));
    fireEvent.click(screen.getByRole("button", { name: /search/i }));

    await waitFor(() =>
      expect(searchPhotos).toHaveBeenCalledWith(
        expect.objectContaining({ people_ids: [1] }),
      ),
    );
    await waitFor(() =>
      expect(screen.getAllByRole("button", { name: /\/photos\/img/i })).toHaveLength(
        MOCK_PHOTOS.length,
      ),
    );
  });

  it("defaults to 'contains' and sends match='exact' when toggled", async () => {
    render(<SearchView people={PEOPLE} />);
    const input = screen.getByLabelText(/add person to search/i);
    fireEvent.change(input, { target: { value: "Ali" } });
    fireEvent.click(screen.getByRole("option", { name: "Alice" }));

    // Default: contains.
    fireEvent.click(screen.getByRole("button", { name: /^search$/i }));
    await waitFor(() =>
      expect(searchPhotos).toHaveBeenLastCalledWith(
        expect.objectContaining({ people_ids: [1], match: "contains" }),
      ),
    );

    // Toggle to exact and search again.
    fireEvent.click(screen.getByRole("radio", { name: /only these people/i }));
    fireEvent.click(screen.getByRole("button", { name: /^search$/i }));
    await waitFor(() =>
      expect(searchPhotos).toHaveBeenLastCalledWith(
        expect.objectContaining({ people_ids: [1], match: "exact" }),
      ),
    );
  });

  it("double-clicking a result calls open_in_viewer with the path", async () => {
    const { invoke } = await import("@tauri-apps/api/core");
    render(<SearchView people={PEOPLE} />);
    const input = screen.getByLabelText(/add person to search/i);

    fireEvent.change(input, { target: { value: "Ali" } });
    fireEvent.click(screen.getByRole("option", { name: "Alice" }));
    fireEvent.click(screen.getByRole("button", { name: /search/i }));

    await waitFor(() =>
      expect(screen.getByTestId("search-result-10")).toBeInTheDocument(),
    );

    fireEvent.doubleClick(screen.getByTestId("search-result-10"));
    await waitFor(() =>
      expect(invoke).toHaveBeenCalledWith("open_in_viewer", { path: "/photos/img1.jpg" }),
    );
  });
});
