import { useState } from "react";
import { Medallion } from "./Medallion";
import type { Photo, FaceInfo } from "../mocks/data";
import "./DetailPanel.css";

interface FaceEntryProps {
  face: FaceInfo;
  onCorrectionRequest?: (faceId: number) => void;
  resolvePersonName?: (personId: number | null) => string;
  highlighted?: boolean;
}

function FaceEntry({
  face,
  onCorrectionRequest,
  resolvePersonName,
  highlighted = false,
}: FaceEntryProps) {
  const [hovered, setHovered] = useState(false);
  const displayName =
    face.personName ?? resolvePersonName?.(face.personId) ?? "Unknown";

  return (
    <div
      className={`face-entry${highlighted ? " face-entry--highlighted" : ""}`}
      data-testid={`face-entry-${face.faceId}`}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <Medallion src={face.faceSrc} alt={displayName} size={48} selected={highlighted} />
      <span className="face-entry__name">
        {displayName}
        {highlighted && <span className="face-entry__badge">this person</span>}
      </span>
      {hovered && (
        <button
          type="button"
          className="face-entry__correction-btn"
          onClick={() => onCorrectionRequest?.(face.faceId)}
        >
          This person is wrong
        </button>
      )}
    </div>
  );
}

interface DetailPanelProps {
  photo: Photo | null;
  onCorrectionRequest?: (faceId: number) => void;
  resolvePersonName?: (personId: number | null) => string;
  highlightPersonId?: number | null;
}

export function DetailPanel({
  photo,
  onCorrectionRequest,
  resolvePersonName,
  highlightPersonId = null,
}: DetailPanelProps) {
  if (photo === null) {
    return (
      <aside className="detail-panel detail-panel--empty">
        <p className="detail-panel__empty-msg">Select a photo</p>
      </aside>
    );
  }

  return (
    <aside className="detail-panel">
      <div className="detail-panel__preview">
        <img src={photo.src} alt={photo.path} className="detail-panel__img" />
      </div>
      <div className="detail-panel__meta">
        <p className="detail-panel__path">{photo.path}</p>
        <p className="detail-panel__date">{photo.takenAt}</p>
      </div>
      {photo.faces.length > 0 && (
        <div className="detail-panel__faces">
          <div className="detail-panel__faces-label">People in this photo</div>
          {photo.faces.map((face) => (
            <FaceEntry
              key={face.faceId}
              face={face}
              onCorrectionRequest={onCorrectionRequest}
              resolvePersonName={resolvePersonName}
              highlighted={
                highlightPersonId !== null && face.personId === highlightPersonId
              }
            />
          ))}
        </div>
      )}
    </aside>
  );
}
