import { describe, beforeEach, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { BackupsView } from "../components/BackupsView";
import { fetchBackups, restoreBackup } from "../api/client";

vi.mock("../api/client", () => ({
  fetchBackups: vi.fn(),
  restoreBackup: vi.fn(),
}));

const entries = [
  {
    backup: "nas/share/pic.jpg",
    original_path: "\\\\nas\\share\\pic.jpg",
    filename: "pic.jpg",
    folder: "\\\\nas\\share",
    file_size: 1_048_576,
    backed_up_at: 1_700_000_000,
    expires_in_days: 5,
  },
];

describe("BackupsView (#162)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchBackups).mockResolvedValue(entries);
    vi.mocked(restoreBackup).mockResolvedValue({ restored: "\\\\nas\\share\\pic.jpg" });
  });

  it("lists backups with filename, folder, size, and expiry", async () => {
    render(<BackupsView />);
    await waitFor(() => screen.getByText("pic.jpg"));
    expect(screen.getByText("\\\\nas\\share")).toBeInTheDocument();
    expect(screen.getByText("1.0 MB")).toBeInTheDocument();
    expect(screen.getByText(/5 days left/i)).toBeInTheDocument();
  });

  it("Restore calls restoreBackup with the backup key", async () => {
    render(<BackupsView />);
    await waitFor(() => screen.getByText("pic.jpg"));
    fireEvent.click(screen.getByRole("button", { name: /restore/i }));
    await waitFor(() =>
      expect(restoreBackup).toHaveBeenCalledWith("nas/share/pic.jpg"),
    );
  });

  it("shows the empty state when there are no backups", async () => {
    vi.mocked(fetchBackups).mockResolvedValue([]);
    render(<BackupsView />);
    await waitFor(() =>
      expect(screen.getByText(/nothing to restore right now/i)).toBeInTheDocument(),
    );
  });
});
