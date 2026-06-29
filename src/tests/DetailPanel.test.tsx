import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { DetailPanel } from "../components/DetailPanel";
import { MOCK_PHOTOS } from "../mocks/data";

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
});
