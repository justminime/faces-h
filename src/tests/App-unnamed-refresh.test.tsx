import { describe, beforeEach, expect, it, vi } from "vitest";
import { render, waitFor, act } from "@testing-library/react";
import App from "../App";
import { ONBOARDING_KEY } from "../components/Onboarding";
import { fetchPeople, fetchPersonPhotos, fetchQueueCount } from "../api/client";
import type { ApiPerson, ApiPhoto } from "../api/types";
import { useUIStore } from "../store/ui";

vi.mock("../api/client", () => ({
  initClient: vi.fn(),
  fetchPeople: vi.fn(),
  fetchPersonPhotos: vi.fn(),
  fetchQueueCount: vi.fn(),
  fetchModelsStatus: vi.fn(),
  startScan: vi.fn(),
  rescan: vi.fn(),
  photoThumbUrl: (photoId: number) => `http://test/photos/${photoId}/thumbnail`,
  faceCropUrl: (faceId: number) => `http://test/faces/${faceId}/crop`,
  exportLibrary: vi.fn(),
  importLibrary: vi.fn(),
}));

const makePerson = (id: number, name = ""): ApiPerson => ({
  id,
  name,
  photo_count: 3,
  medallion_face_id: null,
});

const makePhoto = (id: number): ApiPhoto => ({
  id,
  path: `C:/photos/${id}.jpg`,
  taken_at: null,
  faces: [{ face_id: id * 10, person_id: 1, assign_conf: 0.9, assign_status: "assigned" }],
});

describe("App — selected person's photo grid refreshes after a background sweep (#185)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.setItem(ONBOARDING_KEY, "1");
    useUIStore.setState({
      scanVersion: 0,
      selectedPersonId: null,
      selectedPhotoId: null,
      people: [],
    });
    vi.mocked(fetchPeople).mockResolvedValue([makePerson(1, "")]);
    vi.mocked(fetchQueueCount).mockResolvedValue({ count: 0 });
    vi.mocked(fetchPersonPhotos).mockResolvedValue([makePhoto(1), makePhoto(2)]);
  });

  it("refetches the selected (e.g. unnamed cluster's) photos when scanVersion bumps", async () => {
    render(<App />);

    // Select an (unnamed) person — mirrors clicking it in the Sidebar.
    act(() => {
      useUIStore.getState().setSelectedPerson(1);
    });
    await waitFor(() => expect(fetchPersonPhotos).toHaveBeenCalledTimes(1));
    expect(fetchPersonPhotos).toHaveBeenLastCalledWith(1, 0, 50, "random", expect.any(Number));

    // A background sweep (#169), triggered by naming/confirming a face
    // elsewhere, may have just moved some of this cluster's faces into a
    // different, named person. scanVersion is bumped when that completes.
    vi.mocked(fetchPersonPhotos).mockResolvedValueOnce([makePhoto(1)]);
    act(() => {
      useUIStore.getState().bumpScanVersion();
    });

    await waitFor(() => expect(fetchPersonPhotos).toHaveBeenCalledTimes(2));
    expect(fetchPersonPhotos).toHaveBeenLastCalledWith(1, 0, 50, "random", expect.any(Number));
  });

  it("does not refetch photos on mount before a person is ever selected", async () => {
    render(<App />);
    act(() => {
      useUIStore.getState().bumpScanVersion();
    });
    await waitFor(() => expect(fetchQueueCount).toHaveBeenCalled());
    expect(fetchPersonPhotos).not.toHaveBeenCalled();
  });
});
