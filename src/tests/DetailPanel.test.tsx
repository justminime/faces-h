import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { DetailPanel } from "../components/DetailPanel";
import { MOCK_PHOTOS } from "../mocks/data";
import type { Photo } from "../mocks/data";

const PHOTO_WITH_IDS: Photo = {
  id: 99,
  src: "http://test/photos/99/thumbnail?size=256",
  path: "/photos/group.jpg",
  takenAt: "2026-01-01",
  faces: [
    { faceId: 1, personId: 5, personName: null, faceSrc: "http://test/faces/1/crop" },
    { faceId: 2, personId: 7, personName: null, faceSrc: "http://test/faces/2/crop" },
  ],
};

describe("DetailPanel", () => {
  it("renders photo path and date", () => {
    render(<DetailPanel photo={MOCK_PHOTOS[0]} />);
    expect(screen.getByText(MOCK_PHOTOS[0].path)).toBeInTheDocument();
    expect(screen.getByText(MOCK_PHOTOS[0].takenAt)).toBeInTheDocument();
  });

  it("shows correction button on face hover", () => {
    render(<DetailPanel photo={MOCK_PHOTOS[0]} onCorrectionRequest={vi.fn()} />);
    fireEvent.mouseEnter(screen.getByTestId("face-entry-1"));
    expect(
      screen.getByRole("button", { name: /this person is wrong/i }),
    ).toBeInTheDocument();
  });

  it("renders Unknown for unnamed faces", () => {
    render(<DetailPanel photo={MOCK_PHOTOS[1]} />);
    expect(screen.getByText("Unknown")).toBeInTheDocument();
  });

  it("resolves each face's person name via resolvePersonName", () => {
    render(
      <DetailPanel
        photo={PHOTO_WITH_IDS}
        resolvePersonName={(id) => (id === 5 ? "Alice" : "Unnamed")}
      />,
    );
    expect(screen.getByText("Alice")).toBeInTheDocument();
    expect(screen.getByText("Unnamed")).toBeInTheDocument();
  });

  it("highlights the face belonging to the currently-viewed person", () => {
    render(
      <DetailPanel
        photo={PHOTO_WITH_IDS}
        resolvePersonName={() => "Unnamed"}
        highlightPersonId={5}
      />,
    );
    const highlighted = screen.getByTestId("face-entry-1");
    const other = screen.getByTestId("face-entry-2");
    expect(highlighted.className).toContain("face-entry--highlighted");
    expect(other.className).not.toContain("face-entry--highlighted");
    expect(screen.getByText("this person")).toBeInTheDocument();
  });
});
