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
}

export function Sidebar({
  people,
  selectedPersonId,
  onPersonSelect,
  unnamedCount,
  scanProgress,
  onQueueClick,
  onSearchClick,
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
