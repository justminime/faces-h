import { describe, beforeEach, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { DismissedView } from "../components/DismissedView";
import { fetchDismissedQueue, restoreDismissedFace } from "../api/client";

vi.mock("../api/client", () => ({
  fetchDismissedQueue: vi.fn(),
  restoreDismissedFace: vi.fn(),
}));

const items = [
  { face_id: 1, photo_id: 10, face_crop_url: "/faces/1/crop" },
  { face_id: 2, photo_id: 11, face_crop_url: "/faces/2/crop" },
];

describe("DismissedView (#168)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchDismissedQueue).mockResolvedValue(items);
    vi.mocked(restoreDismissedFace).mockResolvedValue({
      face_id: 1,
      assign_status: "unreviewed",
    });
  });

  it("lists dismissed faces", async () => {
    render(<DismissedView />);
    await waitFor(() =>
      expect(screen.getByText(/2 faces marked not relevant/i)).toBeInTheDocument(),
    );
    expect(screen.getAllByRole("button", { name: /restore for review/i })).toHaveLength(2);
  });

  it("Restore calls restoreDismissedFace and removes the card", async () => {
    render(<DismissedView />);
    await waitFor(() => screen.getAllByRole("button", { name: /restore for review/i }));
    fireEvent.click(screen.getAllByRole("button", { name: /restore for review/i })[0]);
    await waitFor(() => expect(restoreDismissedFace).toHaveBeenCalledWith(1));
    await waitFor(() =>
      expect(screen.getAllByRole("button", { name: /restore for review/i })).toHaveLength(1),
    );
  });

  it("shows the empty state when nothing is dismissed", async () => {
    vi.mocked(fetchDismissedQueue).mockResolvedValue([]);
    render(<DismissedView />);
    await waitFor(() =>
      expect(screen.getByText(/nothing dismissed right now/i)).toBeInTheDocument(),
    );
  });
});
