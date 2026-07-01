import { Medallion } from "./Medallion";
import type { Photo } from "../mocks/data";
import "./PhotoGrid.css";

interface PhotoGridProps {
  photos: Photo[];
  thumbnailSize: number;
  onSizeChange: (size: number) => void;
  onSelect: (photoId: number) => void;
  selectedPhotoId: number | null;
  personName?: string | null;
  personAvatarSrc?: string;
  isNamed?: boolean;
  onRenamePerson?: () => void;
}

export function PhotoGrid({
  photos,
  thumbnailSize,
  onSizeChange,
  onSelect,
  selectedPhotoId,
  personName,
  personAvatarSrc,
  isNamed,
  onRenamePerson,
}: PhotoGridProps) {
  return (
    <div className="photo-grid-wrapper">
      <div className="photo-grid-toolbar">
        {personName != null && (
          <div className="photo-grid-toolbar__person">
            <Medallion src={personAvatarSrc ?? ""} alt={personName} size={36} />
            <span className="photo-grid-toolbar__person-name">{personName}</span>
            {onRenamePerson && (
              <button
                type="button"
                className="photo-grid-toolbar__rename-btn"
                onClick={onRenamePerson}
              >
                {isNamed ? "Rename" : "Name this person"}
              </button>
            )}
          </div>
        )}
        <label htmlFor="size-slider" className="photo-grid-toolbar__label">
          Size
        </label>
        <input
          id="size-slider"
          type="range"
          min={80}
          max={300}
          value={thumbnailSize}
          onChange={(e) => onSizeChange(parseInt(e.target.value, 10))}
          className="photo-grid-toolbar__slider"
        />
      </div>
      <div
        className="photo-grid"
        style={{
          gridTemplateColumns: `repeat(auto-fill, minmax(${thumbnailSize}px, 1fr))`,
        }}
      >
        {photos.map((photo) => (
          <button
            key={photo.id}
            type="button"
            className={`photo-thumb${selectedPhotoId === photo.id ? " photo-thumb--selected" : ""}`}
            onClick={() => onSelect(photo.id)}
            aria-label={photo.path}
            style={{ width: thumbnailSize, height: thumbnailSize }}
          >
            <img src={photo.src} alt={photo.path} />
          </button>
        ))}
      </div>
    </div>
  );
}
