import { useEffect, useRef } from "react";
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
  hasMore?: boolean;
  isLoading?: boolean;
  onLoadMore?: () => void;
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
  hasMore = false,
  isLoading = false,
  onLoadMore,
}: PhotoGridProps) {
  const sentinelRef = useRef<HTMLDivElement>(null);

  // Fire onLoadMore when the sentinel div scrolls into view.
  // rootMargin of 300px starts the next-page fetch before the user
  // reaches the bottom, giving a seamless scroll experience.
  useEffect(() => {
    if (!hasMore || !onLoadMore) return;
    const sentinel = sentinelRef.current;
    if (!sentinel) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) onLoadMore();
      },
      { rootMargin: "300px" },
    );
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [hasMore, onLoadMore]);

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
            <img src={photo.src} alt={photo.path} loading="lazy" />
          </button>
        ))}
      </div>

      {/* Infinite-scroll sentinel — observed by IntersectionObserver above */}
      {hasMore && <div ref={sentinelRef} className="photo-grid__sentinel" />}

      {isLoading && (
        <div className="photo-grid__loading" aria-label="Loading more photos">
          <span className="photo-grid__spinner" />
        </div>
      )}
    </div>
  );
}
