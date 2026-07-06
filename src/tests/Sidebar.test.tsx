import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { Sidebar } from "../components/Sidebar";

const base = {
  people: [],
  selectedPersonId: null,
  onPersonSelect: vi.fn(),
  unnamedCount: 0,
  scanProgress: null,
};

function openMenu() {
  fireEvent.click(screen.getByRole("button", { name: /menu/i }));
}

describe("Sidebar import/export (#80)", () => {
  it("renders Export and Import actions inside the menu and invokes their callbacks", () => {
    const onExport = vi.fn();
    const onImport = vi.fn();
    render(<Sidebar {...base} onExport={onExport} onImport={onImport} />);

    // Export and Import are inside the ··· dropdown — open it first.
    openMenu();
    fireEvent.click(screen.getByRole("menuitem", { name: /export named people/i }));

    openMenu();
    fireEvent.click(screen.getByRole("menuitem", { name: /import named people/i }));

    expect(onExport).toHaveBeenCalledTimes(1);
    expect(onImport).toHaveBeenCalledTimes(1);
  });
});

describe("Sidebar help menu", () => {
  it("shows help links when menu is open", () => {
    render(<Sidebar {...base} appVersion="0.1.0" />);

    openMenu();

    expect(screen.getByRole("link", { name: /shifth\.com/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /user guide/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /report an issue/i })).toBeInTheDocument();
  });

  it("shows keyboard shortcuts panel when toggled", () => {
    render(<Sidebar {...base} />);

    openMenu();
    fireEvent.click(screen.getByRole("button", { name: /keyboard shortcuts/i }));

    // The shortcuts panel renders kbd elements — there will be at least one Ctrl+O
    // (Add Folder badge uses a span, kbd elements are distinct).
    const kbdElements = document.querySelectorAll("kbd");
    const keys = Array.from(kbdElements).map((el) => el.textContent);
    expect(keys).toContain("Ctrl+O");
    expect(keys).toContain("Ctrl+R");
  });

  it("shows version when appVersion is provided", () => {
    render(<Sidebar {...base} appVersion="1.2.3" />);

    openMenu();

    expect(screen.getByText("v1.2.3")).toBeInTheDocument();
  });
});

describe("Sidebar singleton clusters (#141)", () => {
  const people = [
    { id: 1, name: "Alice", avatarSrc: "", photoCount: 12 },
    { id: 2, name: "Unnamed", avatarSrc: "", photoCount: 5 },
    { id: 3, name: "Unnamed", avatarSrc: "", photoCount: 1 },
    { id: 4, name: "Unnamed", avatarSrc: "", photoCount: 1 },
  ];

  it("collapses one-photo unnamed clusters into a counted section", () => {
    render(<Sidebar {...base} people={people} />);
    // Named + multi-photo unnamed stay as top-level rows.
    expect(screen.getByRole("button", { name: /alice/i })).toBeInTheDocument();
    // The two singletons are hidden behind the toggle showing their count.
    const toggle = screen.getByRole("button", { name: /single-face clusters: 2/i });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    // Exactly one visible multi-photo Unnamed row (id 2) besides the summary.
    expect(screen.getAllByText("Unnamed").length).toBeLessThan(3);
  });

  it("expanding the section reveals selectable singleton rows", () => {
    const onPersonSelect = vi.fn();
    render(<Sidebar {...base} people={people} onPersonSelect={onPersonSelect} />);
    fireEvent.click(screen.getByRole("button", { name: /single-face clusters/i }));
    const rows = screen.getAllByText("Unnamed");
    expect(rows.length).toBeGreaterThanOrEqual(3);
    fireEvent.click(rows[rows.length - 1]);
    expect(onPersonSelect).toHaveBeenCalled();
  });

  it("keeps the section open when a singleton is the selected person", () => {
    render(<Sidebar {...base} people={people} selectedPersonId={3} />);
    expect(
      screen.getByRole("button", { name: /single-face clusters/i }),
    ).toHaveAttribute("aria-expanded", "true");
  });
});
