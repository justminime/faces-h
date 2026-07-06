import { describe, beforeEach, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { BlurryView } from "../components/BlurryView";
import { fetchBlurryPhotos, trashPhotos } from "../api/client";

vi.mock("../api/client", () => ({
  fetchBlurryPhotos: vi.fn(),
  trashPhotos: vi.fn(),
  photoThumbUrl: (id: number) => `http://t/photos/${id}/thumbnail`,
}));

const photos = [
  { id: 1, path: "/g/a.jpg", taken_at: null, blur_score: 5 },
  { id: 2, path: "/g/b.jpg", taken_at: null, blur_score: 40 },
];

describe("BlurryView (#154)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchBlurryPhotos).mockResolvedValue(photos);
    vi.mocked(trashPhotos).mockResolvedValue({ trashed: 1, failed: [] });
  });

  it("lists blurry photos with their scores", async () => {
    render(<BlurryView />);
    await waitFor(() =>
      expect(screen.getByLabelText(/photo 1, blur score 5/i)).toBeInTheDocument(),
    );
    expect(screen.getByText(/2 photos at or below the cutoff/i)).toBeInTheDocument();
  });

  it("delete requires selection, opens confirmation, and calls trashPhotos", async () => {
    render(<BlurryView />);
    await waitFor(() => screen.getByLabelText(/photo 1/i));

    const deleteBtn = screen.getByRole("button", { name: /delete.*selected/i });
    expect(deleteBtn).toBeDisabled();

    fireEvent.click(screen.getByLabelText(/photo 1/i));
    expect(deleteBtn).toBeEnabled();
    fireEvent.click(deleteBtn);

    expect(screen.getByRole("dialog", { name: /confirm delete/i })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /move to recycle bin/i }));
    await waitFor(() => expect(trashPhotos).toHaveBeenCalledWith([1]));
  });

  it("slider refetches with a threshold", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    render(<BlurryView />);
    await waitFor(() => screen.getByLabelText(/photo 1/i));

    fireEvent.change(screen.getByLabelText(/blur cutoff/i), { target: { value: "20" } });
    vi.advanceTimersByTime(400);
    await waitFor(() =>
      expect(vi.mocked(fetchBlurryPhotos)).toHaveBeenLastCalledWith(0, 200, 24),
    );
    vi.useRealTimers();
  });
});
