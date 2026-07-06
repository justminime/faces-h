import { useCallback, useEffect, useState } from "react";
import { fetchBackups, restoreBackup, type BackupEntry } from "../api/client";
import { useToastStore } from "../store/toast";
import { useUIStore } from "../store/ui";
import "./BackupsView.css";

function fmtSize(bytes: number): string {
  if (bytes >= 1_048_576) return `${(bytes / 1_048_576).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

/** Lists pre-deletion backups of files that had no Recycle Bin (network
 *  folders) and lets the user restore one to its original location (#162). */
export function BackupsView() {
  const [entries, setEntries] = useState<BackupEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [restoring, setRestoring] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    fetchBackups()
      .then(setEntries)
      .catch(() => setEntries([]))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function doRestore(entry: BackupEntry) {
    if (restoring) return;
    setRestoring(entry.backup);
    try {
      await restoreBackup(entry.backup);
      useToastStore.getState().addToast(`Restored ${entry.filename}`);
      load();
      useUIStore.getState().bumpScanVersion();
    } catch {
      useToastStore.getState().addToast(`Could not restore ${entry.filename}`);
    } finally {
      setRestoring(null);
    }
  }

  return (
    <div className="backups-view">
      <header className="backups-view__header">
        <h2 className="backups-view__title">Backups</h2>
        <p className="backups-view__subtitle">
          {loading
            ? "Loading…"
            : entries.length === 0
              ? "No backups — network files that were deleted or rotated appear here for 7 days"
              : `${entries.length} backup${entries.length === 1 ? "" : "s"} from network-folder deletes and rotations`}
        </p>
      </header>

      {!loading && entries.length === 0 ? (
        <div className="backups-view__empty">
          <p>Nothing to restore right now.</p>
          <p className="backups-view__hint">
            Local files you delete or rotate go to the Windows Recycle Bin
            instead — restore those from there. This list is only for network
            folders, which have no Recycle Bin.
          </p>
        </div>
      ) : (
        <ul className="backups-view__list">
          {entries.map((e) => (
            <li key={e.backup} className="backups-view__row">
              <span className="backups-view__fileinfo">
                <span className="backups-view__filename">{e.filename}</span>
                <span className="backups-view__folder" title={e.folder}>
                  {e.folder}
                </span>
              </span>
              <span className="backups-view__size">{fmtSize(e.file_size)}</span>
              <span className="backups-view__expiry">
                {e.expires_in_days <= 1
                  ? "expires today"
                  : `${Math.round(e.expires_in_days)} days left`}
              </span>
              <button
                type="button"
                className="backups-view__restore-btn"
                onClick={() => void doRestore(e)}
                disabled={restoring === e.backup}
              >
                {restoring === e.backup ? "Restoring…" : "Restore"}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
