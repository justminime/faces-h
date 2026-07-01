import { Medallion } from "./Medallion";
import type { Person } from "../mocks/data";
import { useQueueStore } from "../store/queue";
import "./Sidebar.css";

interface SidebarProps {
  people: Person[];
  selectedPersonId: number | null;
  onPersonSelect: (id: number | null) => void;
  unnamedCount: number;
  scanProgress: number | null;
  onQueueClick?: () => void;
  onSearchClick?: () => void;
  onAddFolder?: () => void;
  onRescan?: () => void;
  onExport?: () => void;
  onImport?: () => void;
}

export function Sidebar({
  people,
  selectedPersonId,
  onPersonSelect,
  unnamedCount,
  scanProgress,
  onQueueClick,
  onSearchClick,
  onAddFolder,
  onRescan,
  onExport,
  onImport,
}: SidebarProps) {
  const queueCount = useQueueStore((s) => s.queueCount);

  return (
    <nav className="sidebar" aria-label="People">
      {scanProgress !== null && (
        <div className="sidebar__scan-progress" role="progressbar" aria-valuenow={Math.round(scanProgress * 100)} aria-valuemin={0} aria-valuemax={100}>
          <div
            className="sidebar__scan-progress-bar"
            style={{ width: `${scanProgress * 100}%` }}
          />
        </div>
      )}

      <h1 className="sidebar__app-name">faces-h</h1>

      <button
        type="button"
        className="sidebar__nav-btn"
        onClick={onSearchClick}
        aria-label="Search"
      >
        Search
      </button>

      <button
        type="button"
        className="sidebar__queue-btn"
        onClick={onQueueClick}
        aria-label={`Uncertain faces: ${queueCount}`}
      >
        <span className="sidebar__queue-label">To review</span>
        <span className="sidebar__queue-badge" aria-live="polite">
          {queueCount}
        </span>
      </button>

      <div className="sidebar__actions">
        <button
          type="button"
          className="sidebar__action-btn"
          onClick={onAddFolder}
          aria-label="Add folder"
          title="Add a folder to scan"
        >
          + Add folder
        </button>
        <button
          type="button"
          className="sidebar__action-btn sidebar__action-btn--icon"
          onClick={onRescan}
          disabled={scanProgress !== null}
          aria-label="Scan now"
          title="Re-scan all folders"
        >
          ↻
        </button>
      </div>

      <div className="sidebar__actions">
        <button
          type="button"
          className="sidebar__action-btn"
          onClick={onImport}
          aria-label="Import names"
          title="Import names from another library"
        >
          Import
        </button>
        <button
          type="button"
          className="sidebar__action-btn"
          onClick={onExport}
          aria-label="Export names"
          title="Export named people to a file"
        >
          Export
        </button>
      </div>

      <div className="sidebar__section-label">People</div>
      <ul className="sidebar__list">
        {people.map((person) => (
          <li key={person.id}>
            <button
              type="button"
              className={`sidebar__person${selectedPersonId === person.id ? " sidebar__person--active" : ""}`}
              onClick={() => onPersonSelect(person.id)}
            >
              <Medallion
                src={person.avatarSrc}
                alt={person.name ?? "Unknown"}
                size={32}
                selected={selectedPersonId === person.id}
              />
              <span className="sidebar__name">{person.name ?? "Unknown"}</span>
              <span className="sidebar__count">{person.photoCount}</span>
            </button>
          </li>
        ))}
        {unnamedCount > 0 && (
          <li>
            <button
              type="button"
              className="sidebar__person"
              onClick={() => onPersonSelect(null)}
            >
              <div className="sidebar__unnamed-avatar" aria-hidden="true" />
              <span className="sidebar__name">Unnamed</span>
              <span className="sidebar__count sidebar__count--accent">{unnamedCount}</span>
            </button>
          </li>
        )}
      </ul>
    </nav>
  );
}
