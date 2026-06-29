import { Medallion } from "./Medallion";
import type { Person } from "../mocks/data";
import "./Sidebar.css";

interface SidebarProps {
  people: Person[];
  selectedPersonId: number | null;
  onPersonSelect: (id: number | null) => void;
  unnamedCount: number;
}

export function Sidebar({ people, selectedPersonId, onPersonSelect, unnamedCount }: SidebarProps) {
  return (
    <nav className="sidebar" aria-label="People">
      <h1 className="sidebar__app-name">faces-h</h1>

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
