import { describe, beforeEach, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { ScanRootsView } from "../components/ScanRootsView";
import { fetchScanRoots, deleteScanRoot } from "../api/client";

vi.mock("../api/client", () => ({
  fetchScanRoots: vi.fn(),
  deleteScanRoot: vi.fn(),
}));

const roots = [
  {
    id: 1,
    path: "C:/Users/me/Pictures",
    added_at: 1_700_000_000,
    is_network: false,
    last_seen_at: 1_700_000_500,
    reachable: true,
  },
  {
    id: 2,
    path: "\\\\nas\\share\\photos",
    added_at: 1_700_000_000,
    is_network: true,
    last_seen_at: null,
    reachable: false,
  },
];

describe("ScanRootsView (#186)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchScanRoots).mockResolvedValue(roots);
    vi.mocked(deleteScanRoot).mockResolvedValue({ status: "removed", id: 1 });
  });

  it("lists configured roots with path, network/local tag, and last-seen info", async () => {
    render(<ScanRootsView onAddFolder={vi.fn()} />);
    await waitFor(() => screen.getByText("C:/Users/me/Pictures"));
    expect(screen.getByText("\\\\nas\\share\\photos")).toBeInTheDocument();
    expect(screen.getByText("local")).toBeInTheDocument();
    expect(screen.getByText("network")).toBeInTheDocument();
    expect(screen.getByText(/unreachable/i)).toBeInTheDocument();
  });

  it("Add Folder triggers the existing add-folder flow", async () => {
    const onAddFolder = vi.fn();
    render(<ScanRootsView onAddFolder={onAddFolder} />);
    await waitFor(() => screen.getByText("C:/Users/me/Pictures"));
    fireEvent.click(screen.getByRole("button", { name: /add folder/i }));
    expect(onAddFolder).toHaveBeenCalledTimes(1);
  });

  it("Remove requires confirmation, then calls deleteScanRoot and removes the row", async () => {
    render(<ScanRootsView onAddFolder={vi.fn()} />);
    await waitFor(() => screen.getByText("C:/Users/me/Pictures"));

    const removeButtons = screen.getAllByRole("button", { name: /^remove$/i });
    fireEvent.click(removeButtons[0]);

    expect(screen.getByText(/remove this folder from scanning/i)).toBeInTheDocument();
    expect(deleteScanRoot).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: /confirm/i }));
    await waitFor(() => expect(deleteScanRoot).toHaveBeenCalledWith(1));
    await waitFor(() =>
      expect(screen.queryByText("C:/Users/me/Pictures")).not.toBeInTheDocument(),
    );
    expect(screen.getByText("\\\\nas\\share\\photos")).toBeInTheDocument();
  });

  it("Cancel dismisses the confirmation without deleting", async () => {
    render(<ScanRootsView onAddFolder={vi.fn()} />);
    await waitFor(() => screen.getByText("C:/Users/me/Pictures"));

    fireEvent.click(screen.getAllByRole("button", { name: /^remove$/i })[0]);
    fireEvent.click(screen.getByRole("button", { name: /cancel/i }));

    expect(deleteScanRoot).not.toHaveBeenCalled();
    expect(screen.getByText("C:/Users/me/Pictures")).toBeInTheDocument();
  });

  it("shows the empty state when there are no roots configured", async () => {
    vi.mocked(fetchScanRoots).mockResolvedValue([]);
    render(<ScanRootsView onAddFolder={vi.fn()} />);
    await waitFor(() =>
      expect(screen.getByText(/no folders configured yet/i)).toBeInTheDocument(),
    );
  });
});
