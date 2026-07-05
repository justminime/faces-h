import { useEffect, useRef, useState } from "react";
import { Medallion } from "./Medallion";
import type { Person } from "../types";
import { useQueueStore } from "../store/queue";
import { useTheme } from "../hooks/useTheme";
import type { Theme } from "../hooks/useTheme";
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
  appVersion?: string;
}

const THEME_OPTIONS: { value: Theme; label: string; icon: string }[] = [
  { value: "light",  label: "Light",         icon: "☀" },
  { value: "dark",   label: "Dark",           icon: "☽" },
  { value: "system", label: "Follow System",  icon: "⊟" },
];

const HELP_LINKS = [
  { label: "shifth.com",         url: "https://shifth.com" },
  { label: "About faces-h",      url: "https://shifth.com/faces-h" },
  { label: "User Guide",         url: "https://shifth.com/faces-h#guide" },
  { label: "Report an issue",    url: "https://github.com/justminime/faces-h/issues" },
  { label: "Release notes",      url: "https://github.com/justminime/faces-h/releases" },
];

const SHORTCUTS = [
  { keys: "Ctrl+O", desc: "Add folder" },
  { keys: "Ctrl+R", desc: "Rescan library" },
  { keys: "Ctrl+G", desc: "Gallery view" },
  { keys: "Ctrl+F", desc: "Search" },
];

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
  appVersion,
}: SidebarProps) {
  const queueCount = useQueueStore((s) => s.queueCount);
  const [theme, setTheme] = useTheme();
  const [menuOpen, setMenuOpen] = useState(false);
  const [showShortcuts, setShowShortcuts] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  // Close dropdown on outside click
  useEffect(() => {
    if (!menuOpen) return;
    function handleClick(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [menuOpen]);

  function action(fn?: () => void) {
    return () => { setMenuOpen(false); fn?.(); };
  }

  return (
    <nav className="sidebar" aria-label="People">
      {scanProgress !== null && (
        <div className="sidebar__scan-progress" role="progressbar" aria-valuenow={Math.round(scanProgress * 100)} aria-valuemin={0} aria-valuemax={100}>
          <div className="sidebar__scan-progress-bar" style={{ width: `${scanProgress * 100}%` }} />
        </div>
      )}

      {/* Header: brand + menu button */}
      <div className="sidebar__header">
        <img src="/icon.svg" alt="" className="sidebar__logo" aria-hidden="true" />
        <h1 className="sidebar__app-name">faces-h</h1>

        <div className="sidebar__menu-wrap" ref={menuRef}>
          <button
            type="button"
            className={`sidebar__menu-trigger${menuOpen ? " sidebar__menu-trigger--open" : ""}`}
            onClick={() => setMenuOpen((o) => !o)}
            aria-label="Menu"
            aria-expanded={menuOpen}
          >
            ···
          </button>

          {menuOpen && (
            <div className="sidebar__dropdown" role="menu">

              {/* Library section */}
              <div className="sidebar__menu-section">Library</div>
              <button type="button" className="sidebar__menu-item" role="menuitem" onClick={action(onAddFolder)}>
                <span className="sidebar__menu-icon">📁</span>
                Add Folder
                <span className="sidebar__menu-shortcut">Ctrl+O</span>
              </button>
              <button
                type="button"
                className="sidebar__menu-item"
                role="menuitem"
                onClick={action(onRescan)}
                disabled={scanProgress !== null}
              >
                <span className="sidebar__menu-icon">↺</span>
                Rescan Library
              </button>

              <div className="sidebar__menu-divider" />

              {/* Identity section */}
              <div className="sidebar__menu-section">Identity</div>
              <button type="button" className="sidebar__menu-item" role="menuitem" onClick={action(onExport)}>
                <span className="sidebar__menu-icon">↑</span>
                Export Named People
              </button>
              <button type="button" className="sidebar__menu-item" role="menuitem" onClick={action(onImport)}>
                <span className="sidebar__menu-icon">↓</span>
                Import Named People
              </button>

              <div className="sidebar__menu-divider" />

              {/* Appearance section */}
              <div className="sidebar__menu-section">Appearance</div>
              {THEME_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  className={`sidebar__menu-item${theme === opt.value ? " sidebar__menu-item--active" : ""}`}
                  role="menuitemradio"
                  aria-checked={theme === opt.value}
                  onClick={() => { setTheme(opt.value); setMenuOpen(false); }}
                >
                  <span className="sidebar__menu-icon">{opt.icon}</span>
                  {opt.label}
                  {theme === opt.value && <span className="sidebar__menu-check">✓</span>}
                </button>
              ))}

              <div className="sidebar__menu-divider" />

              {/* Help section */}
              <div className="sidebar__menu-section">Help</div>
              {HELP_LINKS.map((link) => (
                <a
                  key={link.url}
                  href={link.url}
                  target="_blank"
                  rel="noreferrer"
                  className="sidebar__menu-item sidebar__menu-item--link"
                  onClick={() => setMenuOpen(false)}
                >
                  <span className="sidebar__menu-icon">↗</span>
                  {link.label}
                </a>
              ))}
              <button
                type="button"
                className="sidebar__menu-item"
                onClick={() => { setShowShortcuts((s) => !s); }}
              >
                <span className="sidebar__menu-icon">⌨</span>
                Keyboard shortcuts
                <span className="sidebar__menu-check" style={{ opacity: 0.5, fontSize: 10 }}>
                  {showShortcuts ? "▴" : "▾"}
                </span>
              </button>
              {showShortcuts && (
                <div className="sidebar__shortcuts">
                  {SHORTCUTS.map((s) => (
                    <div key={s.keys} className="sidebar__shortcut-row">
                      <kbd className="sidebar__kbd">{s.keys}</kbd>
                      <span>{s.desc}</span>
                    </div>
                  ))}
                </div>
              )}
              {appVersion && (
                <div className="sidebar__menu-version">v{appVersion}</div>
              )}

            </div>
          )}
        </div>
      </div>

      {/* Nav */}
      <button type="button" className="sidebar__nav-btn" onClick={onSearchClick} aria-label="Search">
        Search
      </button>
      <button
        type="button"
        className="sidebar__queue-btn"
        onClick={onQueueClick}
        aria-label={`Uncertain faces: ${queueCount}`}
      >
        <span className="sidebar__queue-label">To review</span>
        <span className="sidebar__queue-badge" aria-live="polite">{queueCount}</span>
      </button>

      <div className="sidebar__divider" />
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
            <button type="button" className="sidebar__person" onClick={() => onPersonSelect(null)}>
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
