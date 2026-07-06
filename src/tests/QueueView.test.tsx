import { describe, beforeEach, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueueView } from "../components/QueueView";
import {
  confirmFace,
  dismissFace,
  fetchQueueCount,
  fetchUncertainQueue,
} from "../api/client";
import type { QueueItem } from "../api/types";

vi.mock("../api/client", () => ({
  confirmFace: vi.fn(),
  dismissFace: vi.fn(),
  fetchQueueCount: vi.fn(),
  fetchUncertainQueue: vi.fn(),
  faceCropUrl: (faceId: number) => `http://test/faces/${faceId}/crop`,
}));

const makeItem = (faceId: number, overrides: Partial<QueueItem> = {}): QueueItem => ({
  face_id: faceId,
  photo_id: faceId * 10,
  face_crop_url: `/faces/${faceId}/crop`,
  suggested_person_id: 1,
  suggested_person_name: "Alice",
  assign_conf: 0.62,
  ...overrides,
});

describe("QueueView", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchQueueCount).mockResolvedValue({ count: 2 });
    vi.mocked(confirmFace).mockResolvedValue({
      face_id: 1,
      person_id: 1,
      assign_status: "assigned",
    });
    vi.mocked(dismissFace).mockResolvedValue({
      face_id: 1,
      assign_status: "dismissed",
    });
  });

  it("fetches the queue on mount and renders a card per item", async () => {
    vi.mocked(fetchUncertainQueue).mockResolvedValue([makeItem(1), makeItem(2)]);
    render(<QueueView />);
    await waitFor(() => expect(screen.getAllByRole("article")).toHaveLength(2));
    expect(fetchUncertainQueue).toHaveBeenCalled();
  });

  it("confirming a face calls confirmFace and removes its card", async () => {
    vi.mocked(fetchUncertainQueue).mockResolvedValue([makeItem(1), makeItem(2)]);
    render(<QueueView />);
    await waitFor(() => expect(screen.getAllByRole("article")).toHaveLength(2));

    fireEvent.click(
      screen.getAllByRole("button", { name: /yes, this is alice/i })[0],
    );
    await waitFor(() => expect(confirmFace).toHaveBeenCalledWith(1, 1));
    await waitFor(() => expect(screen.getAllByRole("article")).toHaveLength(1));
  });

  it("marking a face 'not relevant' calls dismissFace and removes its card from view", async () => {
    vi.mocked(fetchUncertainQueue).mockResolvedValue([makeItem(1), makeItem(2)]);
    render(<QueueView />);
    await waitFor(() => expect(screen.getAllByRole("article")).toHaveLength(2));

    fireEvent.click(screen.getAllByRole("button", { name: /not relevant/i })[0]);
    await waitFor(() => expect(dismissFace).toHaveBeenCalledWith(1));
    await waitFor(() => expect(screen.getAllByRole("article")).toHaveLength(1));
    expect(screen.queryByTestId("queue-card-1")).not.toBeInTheDocument();
  });

  it("skipping removes the card without calling confirmFace, and a skipped face does not reappear on refetch", async () => {
    // First fetch: one item. After it is skipped the list empties, QueueView
    // refetches, and the server (where the face is still uncertain) returns it
    // again — the session skip-list must keep it hidden.
    vi.mocked(fetchUncertainQueue).mockResolvedValue([makeItem(7)]);
    render(<QueueView />);
    await waitFor(() => expect(screen.getAllByRole("article")).toHaveLength(1));

    fireEvent.click(screen.getByRole("button", { name: /skip/i }));
    await waitFor(() =>
      expect(screen.getByText(/no faces waiting for review/i)).toBeInTheDocument(),
    );
    expect(confirmFace).not.toHaveBeenCalled();
    expect(vi.mocked(fetchUncertainQueue).mock.calls.length).toBeGreaterThan(1);
  });

  it("shows the empty state when the queue is empty", async () => {
    vi.mocked(fetchUncertainQueue).mockResolvedValue([]);
    vi.mocked(fetchQueueCount).mockResolvedValue({ count: 0 });
    render(<QueueView />);
    await waitFor(() =>
      expect(screen.getByText(/no faces waiting for review/i)).toBeInTheDocument(),
    );
  });
});
