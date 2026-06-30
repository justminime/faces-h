import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { PhotoGrid } from "../components/PhotoGrid";
import { MOCK_PHOTOS } from "../mocks/data";

function renderGrid(overrides?: Partial<Parameters<typeof PhotoGrid>[0]>) {
  return render(
    <PhotoGrid
      photos={MOCK_PHOTOS}
      thumbnailSize={160}
      onSizeChange={vi.fn()}
      onSelect={vi.fn()}
      selectedPhotoId={null}
      {...overrides}
    />,
  );
}

describe("PhotoGrid", () => {
  it("renders correct number of thumbnails from mock data", () => {
    renderGrid();
    expect(screen.getAllByRole("img")).toHaveLength(MOCK_PHOTOS.length);
  });

  it("calls onSizeChange when slider moves", () => {
    const onSizeChange = vi.fn();
    renderGrid({ onSizeChange });
    fireEvent.change(screen.getByRole("slider"), { target: { value: "200" } });
    expect(onSizeChange).toHaveBeenCalledWith(200);
  });

  it("clicking a photo calls onSelect with its id", () => {
    const onSelect = vi.fn();
    renderGrid({ onSelect });
    fireEvent.click(screen.getAllByRole("img")[0]);
    expect(onSelect).toHaveBeenCalledWith(MOCK_PHOTOS[0].id);
  });

  it("renders each thumbnail with its src (regression: thumbnails were blank)", () => {
    const photos = [
      { ...MOCK_PHOTOS[0], id: 1, src: "http://127.0.0.1:51423/photos/1/thumbnail?size=256" },
    ];
    renderGrid({ photos });
    const img = screen.getByRole("img");
    expect(img).toHaveAttribute(
      "src",
      "http://127.0.0.1:51423/photos/1/thumbnail?size=256",
    );
  });
});
