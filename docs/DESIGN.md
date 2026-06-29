# Design Direction: Warm Archive

**Version:** 1.0
**Status:** Draft
**Last updated:** 2026-06-28

---

## Overview

The structural clarity of Notion/Linear — sidebar navigation, clean panels, deliberate spacing, subtle dividers — but every neutral surface carries quiet warmth. This is not a productivity tool that happens to hold your family's memories. It's a personal archive that happens to be well-organized.

**Mood:** Warm and intimate
**Reference:** Notion / Linear
**Color mode:** Light + dark, follows system setting
**Typography:** All sans-serif
**Accent:** Warm terracotta

---

## Color Tokens

| Role | Light mode | Dark mode |
|------|-----------|-----------|
| Background | `#F6F4F1` | `#1C1917` |
| Surface (cards / panels) | `#FFFFFF` | `#26211E` |
| Border | `#E3DFDA` | `#3D3733` |
| Text primary | `#1C1917` | `#F6F4F1` |
| Text secondary | `#78716C` | `#A8A29E` |
| Accent | `#C2522A` | `#E8714A` |

The accent is used sparingly: interactive states, person-name badges, the hover ring on person medallions. Not applied to every button.

---

## Typography

**Typeface:** DM Sans — humanist, softer than Inter, warmer than Geist, equally clean and legible. A quiet personality that reads modern but not cold.

| Role | Weight | Notes |
|------|--------|-------|
| Body text | 400 | Default UI copy |
| Labels / metadata | 500 | Dates, file paths, counts |
| Person names | 600 | Used wherever a person is named |
| Display / headings | 700 | Rare; section titles only |

All text in a single typeface family. No mixed personalities.

---

## Layout

Three-panel structure (Notion-pattern):

```
┌─────────────┬───────────────────────────┬──────────────┐
│             │                           │              │
│  Sidebar    │     Main content          │  Detail      │
│             │     (adaptive grid)       │  panel       │
│  Person     │                           │  (contextual)│
│  list +     │                           │              │
│  navigation │                           │  Photo meta  │
│             │                           │  Who's here  │
└─────────────┴───────────────────────────┴──────────────┘
```

- **Left sidebar:** Person list with face medallions, navigation (Browse, Search, Unnamed queue)
- **Main content:** Photo grid with user-controlled density (slider for thumbnail size)
- **Right panel:** Contextual — photo detail, metadata, face assignments, correction actions

---

## Signature Element: Person Medallions

Every person in the app is represented by a **circular crop of their most characteristic face** — not a generic avatar, not a name chip with an initial.

This medallion is used consistently everywhere:
- Sidebar person list
- Search result tags overlaid on photos
- "Who's in this photo" panel
- The naming and correction workflow
- Multi-person AND search query chips

On hover or selection, a thin terracotta ring (`#C2522A` / `#E8714A`) appears around the medallion.

**Rationale for the risk:** The app's primary navigation object is a human face, not a folder name or a label. This is unusual for desktop software. The justification: the app's entire purpose is helping you find *people*, not files. Making faces the primary UI atom makes that truth visible in the structure.

---

## Grid Density

The photo grid is user-controlled via a size slider. Three informal breakpoints:

| Setting | Thumbnail size | Feel |
|---------|---------------|------|
| Small | ~80px | Scanning a large library quickly |
| Medium | ~160px | Default workhorse view |
| Large | ~240px+ | Gallery mode, one photo gets space |

Slider is persistent per-session and lives in the toolbar above the grid.

---

## Motion Principles

- Minimal animation — avoid the feeling of AI-generated UI through excessive effects
- Transitions: panel opens and grid reflows use subtle easing (150–200ms), nothing longer
- The terracotta ring on medallion hover is the one deliberate interactive moment
- Scan progress: a thin ambient progress bar at the top of the sidebar, not a modal blocker
- Re-evaluation jobs: a distinct secondary progress indicator (different from initial scan) so users always know what is happening

---

## Open Design Questions

| # | Question |
|---|----------|
| DQ-01 | Implementation target (Electron / Tauri / WPF / WinUI) — determines what can be built and how |
| DQ-02 | UX for merging two person clusters (PRD OQ-03): drag-and-drop medallion merge, or explicit merge button? |
| DQ-03 | How to present the "uncertain faces" confirmation queue — inline in the grid vs. a dedicated review mode? |
| DQ-04 | Onboarding flow design: folder picker → scan estimate → first faces surfaced |
