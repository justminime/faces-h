import { describe, beforeEach, afterEach, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { NamingModal } from "../components/NamingModal";
import { CorrectionModal } from "../components/CorrectionModal";
import { QueueView } from "../components/QueueView";
import { useFamilyStore } from "../store/family";
import {
  fetchCandidates,
  linkPersonToMember,
  mergePeople,
  personForMember,
  correctFace,
  fetchReviewQueue,
  fetchReviewProgress,
  fetchQueueCount,
  type MemberCandidate,
} from "../api/client";

vi.mock("../api/client", () => ({
  fetchCandidates: vi.fn(),
  linkPersonToMember: vi.fn(),
  mergePeople: vi.fn(),
  renamePerson: vi.fn(),
  personForMember: vi.fn(),
  correctFace: vi.fn(),
  fetchReviewQueue: vi.fn(),
  fetchReviewProgress: vi.fn(),
  fetchUncertainQueue: vi.fn(),
  fetchQueueCount: vi.fn(),
  confirmFace: vi.fn(),
  dismissFace: vi.fn(),
  faceCropUrl: (id: number) => `/faces/${id}/crop`,
}));

const member = (
  id: number,
  name: string,
  similarity: number | null,
  person_id: number | null,
  extra: Partial<MemberCandidate> = {},
): MemberCandidate => ({
  id,
  name,
  heb_name: null,
  birth_year: null,
  death_year: null,
  person_id,
  similarity,
  current: false,
  ...extra,
});

// Server order: closest first, then no-centroid members by name.
const CANDIDATES = [
  member(13, "Ayelet Heilweil", 0.87, 2, { heb_name: "איילת" }),
  member(12, "Daniel Heilweil", 0.41, 3, { birth_year: 2007 }),
  member(14, "Ziv Heilweil", null, null),
];

describe("family list naming (#198)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useFamilyStore.setState({ loaded: true, members: [] });
    vi.mocked(fetchCandidates).mockResolvedValue(CANDIDATES);
    vi.mocked(linkPersonToMember).mockResolvedValue({ id: 1, name: "Ziv Heilweil", member_id: 14 });
    vi.mocked(mergePeople).mockResolvedValue({ surviving_id: 2, merged_count: 4 });
    vi.mocked(personForMember).mockResolvedValue(50);
    vi.mocked(correctFace).mockResolvedValue({ status: "queued", face_id: 10 });
  });
  afterEach(() => {
    useFamilyStore.setState({ loaded: false, members: [] });
  });

  it("offers a ranked dropdown with the best match first and no free-text field", async () => {
    render(
      <NamingModal personId={1} sampleFaceSrcs={[]} existingPeople={[]} onSaved={vi.fn()} onSkip={vi.fn()} />,
    );
    const select = await screen.findByLabelText(/family member/i);
    expect(screen.queryByRole("textbox")).toBeNull();
    const labels = Array.from(select.querySelectorAll("option")).map((o) => o.textContent);
    expect(labels.slice(1)).toEqual([
      "★ Ayelet Heilweil · איילת — 87%",
      "★ Daniel Heilweil · 2007 — 41%",
      "Ziv Heilweil",
    ]);
    expect(fetchCandidates).toHaveBeenCalledWith({ personId: 1 });
  });

  it("links the cluster to a member that has no group yet", async () => {
    const onSaved = vi.fn();
    render(
      <NamingModal personId={1} sampleFaceSrcs={[]} existingPeople={[]} onSaved={onSaved} onSkip={vi.fn()} />,
    );
    fireEvent.change(await screen.findByLabelText(/family member/i), { target: { value: "14" } });
    fireEvent.click(screen.getByRole("button", { name: /save/i }));
    await waitFor(() => expect(linkPersonToMember).toHaveBeenCalledWith(1, 14));
    expect(onSaved).toHaveBeenCalledWith("Ziv Heilweil");
  });

  it("merges into the existing group when the member already has one", async () => {
    render(
      <NamingModal personId={1} sampleFaceSrcs={[]} existingPeople={[]} onSaved={vi.fn()} onSkip={vi.fn()} />,
    );
    fireEvent.change(await screen.findByLabelText(/family member/i), { target: { value: "13" } });
    expect(screen.getByText(/will merge/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /merge/i }));
    await waitFor(() => expect(mergePeople).toHaveBeenCalledWith(1, 2));
    expect(linkPersonToMember).not.toHaveBeenCalled();
  });

  it("corrects a face to a member with no group by creating it first", async () => {
    const onCorrected = vi.fn();
    render(
      <CorrectionModal faceId={10} photoId={100} people={[]} onCorrected={onCorrected} onClose={vi.fn()} />,
    );
    fireEvent.change(await screen.findByLabelText(/family member/i), { target: { value: "14" } });
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));
    await waitFor(() => expect(correctFace).toHaveBeenCalledWith(100, 10, 50));
    expect(personForMember).toHaveBeenCalledWith(14);
    expect(fetchCandidates).toHaveBeenCalledWith({ faceId: 10 });
    expect(onCorrected).toHaveBeenCalled();
  });

  it("guided review uses the review queue and shows per-person progress", async () => {
    vi.mocked(fetchQueueCount).mockResolvedValue({ count: 3 });
    vi.mocked(fetchReviewQueue).mockResolvedValue([]);
    vi.mocked(fetchReviewProgress).mockResolvedValue({
      people: [
        { member_id: 12, name: "Daniel Heilweil", heb_name: "דניאל", person_id: 3, assigned: 40, uncertain: 2 },
        { member_id: 13, name: "Ayelet Heilweil", heb_name: null, person_id: 2, assigned: 12, uncertain: 0 },
      ],
      remaining: 2,
      members_without_faces: 1,
      done: false,
    });
    render(<QueueView guided />);
    expect(await screen.findByText(/2 faces left to confirm/i)).toBeInTheDocument();
    expect(screen.getByText("Daniel Heilweil · דניאל")).toBeInTheDocument();
    expect(screen.getByText(/1 family member has no faces yet/i)).toBeInTheDocument();
    expect(fetchReviewQueue).toHaveBeenCalled();
  });
});
