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

describe("Sidebar import/export (#80)", () => {
  it("renders Export and Import actions and invokes their callbacks", () => {
    const onExport = vi.fn();
    const onImport = vi.fn();
    render(<Sidebar {...base} onExport={onExport} onImport={onImport} />);

    fireEvent.click(screen.getByRole("button", { name: /export names/i }));
    fireEvent.click(screen.getByRole("button", { name: /import names/i }));

    expect(onExport).toHaveBeenCalledTimes(1);
    expect(onImport).toHaveBeenCalledTimes(1);
  });
});
