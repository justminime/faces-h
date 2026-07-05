import { useState, useCallback } from "react";
import { invoke } from "@tauri-apps/api/core";
import { searchPhotos, photoThumbUrl } from "../api/client";
import type { ApiPhoto } from "../api/types";
import type { Person } from "../types";
import "./SearchView.css";

interface SearchViewProps {
  people: Person[];
}

interface PersonChip {
  id: number;
  name: string;
}

export function SearchView({ people }: SearchViewProps) {
  const [chips, setChips] = useState<PersonChip[]>([]);
  const [inputValue, setInputValue] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [matchMode, setMatchMode] = useState<"contains" | "exact">("contains");
  const [results, setResults] = useState<ApiPhoto[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [contextMenu, setContextMenu] = useState<{
    x: number;
    y: number;
    path: string;
  } | null>(null);

  const suggestions = people.filter(
    (p) =>
      p.name &&
      !chips.find((c) => c.id === p.id) &&
      p.name.toLowerCase().includes(inputValue.toLowerCase()),
  );

  function addChip(person: Person) {
    if (!person.name) return;
    setChips((prev) => [...prev, { id: person.id, name: person.name! }]);
    setInputValue("");
    setResults(null);
  }

  function removeChip(id: number) {
    setChips((prev) => prev.filter((c) => c.id !== id));
    setResults(null);
  }

  const runSearch = useCallback(async () => {
    if (chips.length === 0) return;
    setBusy(true);
    try {
      const photos = await searchPhotos({
        people_ids: chips.map((c) => c.id),
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
        match: matchMode,
      });
      setResults(photos);
    } catch {
      setResults([]);
    } finally {
      setBusy(false);
    }
  }, [chips, dateFrom, dateTo, matchMode]);

  async function handleDoubleClick(path: string) {
    try {
      await invoke("open_in_viewer", { path });
    } catch {
      // not in Tauri — no-op
    }
  }

  async function handleRevealInExplorer(path: string) {
    try {
      await invoke("reveal_in_explorer", { path });
    } catch {
      // not in Tauri — no-op
    }
    setContextMenu(null);
  }

  function handleCopyPath(path: string) {
    void navigator.clipboard.writeText(path);
    setContextMenu(null);
  }

  return (
    <div
      className="search-view"
      onClick={() => setContextMenu(null)}
      onKeyDown={(e) => e.key === "Escape" && setContextMenu(null)}
    >
      <div className="search-view__controls">
        <div className="search-view__chips-input">
          {chips.map((chip) => (
            <span key={chip.id} className="search-chip">
              {chip.name}
              <button
                className="search-chip__remove"
                aria-label={`Remove ${chip.name}`}
                onClick={() => removeChip(chip.id)}
              >
                ×
              </button>
            </span>
          ))}
          <div className="search-view__autocomplete">
            <input
              className="search-view__text-input"
              type="text"
              placeholder={chips.length === 0 ? "Add a person…" : "Add another…"}
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              aria-label="Add person to search"
            />
            {inputValue.length > 0 && suggestions.length > 0 && (
              <ul className="search-view__suggestions" role="listbox">
                {suggestions.map((p) => (
                  <li key={p.id}>
                    <button
                      className="search-view__suggestion-item"
                      role="option"
                      aria-selected={false}
                      onClick={() => addChip(p)}
                    >
                      {p.name}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>

        <div className="search-view__dates">
          <label className="search-view__date-label">
            From
            <input
              type="date"
              className="search-view__date-input"
              value={dateFrom}
              onChange={(e) => { setDateFrom(e.target.value); setResults(null); }}
              aria-label="Date from"
            />
          </label>
          <label className="search-view__date-label">
            To
            <input
              type="date"
              className="search-view__date-input"
              value={dateTo}
              onChange={(e) => { setDateTo(e.target.value); setResults(null); }}
              aria-label="Date to"
            />
          </label>
        </div>

        <div
          className="search-view__match"
          role="radiogroup"
          aria-label="Match mode"
        >
          <button
            type="button"
            role="radio"
            aria-checked={matchMode === "contains"}
            className={`search-view__match-btn${matchMode === "contains" ? " search-view__match-btn--active" : ""}`}
            onClick={() => { setMatchMode("contains"); setResults(null); }}
          >
            Contains
          </button>
          <button
            type="button"
            role="radio"
            aria-checked={matchMode === "exact"}
            className={`search-view__match-btn${matchMode === "exact" ? " search-view__match-btn--active" : ""}`}
            onClick={() => { setMatchMode("exact"); setResults(null); }}
          >
            Only these people
          </button>
        </div>

        <button
          className="search-view__search-btn"
          disabled={chips.length === 0 || busy}
          onClick={() => void runSearch()}
        >
          {busy ? "Searching…" : "Search"}
        </button>
      </div>

      {results !== null && (
        <div className="search-view__results">
          {results.length === 0 ? (
            <p className="search-view__empty">No photos found.</p>
          ) : (
            <ul className="search-grid" aria-label="Search results">
              {results.map((photo) => (
                <li key={photo.id} className="search-grid__item">
                  <button
                    className="search-grid__thumb-btn"
                    onDoubleClick={() => void handleDoubleClick(photo.path)}
                    onContextMenu={(e) => {
                      e.preventDefault();
                      setContextMenu({ x: e.clientX, y: e.clientY, path: photo.path });
                    }}
                    aria-label={photo.path}
                    data-testid={`search-result-${photo.id}`}
                  >
                    <img
                      className="search-grid__img"
                      src={photoThumbUrl(photo.id)}
                      alt={photo.path}
                      loading="lazy"
                    />
                  </button>
                </li>
              ))}
            </ul>
          )}
          <p className="search-view__count">
            {results.length} photo{results.length !== 1 ? "s" : ""}
          </p>
        </div>
      )}

      {contextMenu && (
        <ul
          className="search-context-menu"
          style={{ top: contextMenu.y, left: contextMenu.x }}
          role="menu"
        >
          <li>
            <button
              className="search-context-menu__item"
              role="menuitem"
              onClick={() => void handleRevealInExplorer(contextMenu.path)}
            >
              Show in Explorer
            </button>
          </li>
          <li>
            <button
              className="search-context-menu__item"
              role="menuitem"
              onClick={() => handleCopyPath(contextMenu.path)}
            >
              Copy path
            </button>
          </li>
        </ul>
      )}
    </div>
  );
}
