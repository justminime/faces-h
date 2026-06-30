import { describe, beforeEach, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { UncertainQueue } from "../components/UncertainQueue";
import { confirmFace } from "../api/client";
import type { QueueItem } from "../api/types";

vi.mock("../api/client", () => ({
  confirmFace: vi.fn(),
  faceCropUrl: (faceId: number) => `http://test/faces/${faceId}/crop`,
}));

vi.mock("../store/ui", () => ({
  useUIStore: (selector: (s: { people: { id: number; name: string | null }[] }) => unknown) =>
    selector({
      people: [
        { id: 1, name: "Alice" },
        { id: 2, name: "Bob" },
      ],
    }),
}));

const makeItem = (overrides: Partial<QueueItem> = {}): QueueItem => ({
  face_id: 1,
  photo_id: 10,
  face_crop_url: "/faces/1/crop",
  suggested_person_id: 1,
  suggested_person_name: "Alice",
  assign_conf: 0.62,
  ...overrides,
});

describe("UncertainQueue", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(confirmFace).mockResolvedValue({
      face_id: 1,
      person_id: 1,
      assign_status: "assigned",
    });
  });

  it("renders N cards for N items", () => {
    const items = [makeItem({ face_id: 1 }), makeItem({ face_id: 2, face_crop_url: "/faces/2/crop" })];
    render(<UncertainQueue items={items} onReviewed={vi.fn()} />);
    expect(screen.getAllByRole("article")).toHaveLength(2);
  });

  it("Yes button calls confirmFace with suggested_person_id", async () => {
    const onReviewed = vi.fn();
    render(<UncertainQueue items={[makeItem()]} onReviewed={onReviewed} />);
    fireEvent.click(screen.getByRole("button", { name: /yes, this is alice/i }));
    await waitFor(() => expect(confirmFace).toHaveBeenCalledWith(1, 1));
    await waitFor(() => expect(onReviewed).toHaveBeenCalledWith(1));
  });

  it("No button opens person picker", () => {
    render(<UncertainQueue items={[makeItem()]} onReviewed={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /no, someone else/i }));
    expect(screen.getByRole("dialog", { name: /choose a person/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Alice" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Bob" })).toBeInTheDocument();
  });

  it("count badge reflects number of items rendered", () => {
    const items = [
      makeItem({ face_id: 1 }),
      makeItem({ face_id: 2, face_crop_url: "/faces/2/crop" }),
      makeItem({ face_id: 3, face_crop_url: "/faces/3/crop" }),
    ];
    render(<UncertainQueue items={items} onReviewed={vi.fn()} />);
    expect(screen.getAllByRole("article")).toHaveLength(items.length);
  });
});
