import "./TrashConfirmDialog.css";

export interface TrashItem {
  id: number;
  filename: string;
  folder: string;
  fileSize: number | null;
  /** Thumbnail URL so the user sees the actual photo before deleting. */
  thumbSrc: string;
  /** Network shares typically have no Recycle Bin, so these usually end up
   *  app-backed-up rather than Bin-recycled — every file gets an app backup
   *  either way (#164), so this is informational, not a different outcome. */
  isNetwork: boolean;
}

interface TrashConfirmDialogProps {
  items: TrashItem[];
  busy: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}

function fmtSize(bytes: number | null): string {
  if (bytes === null) return "—";
  if (bytes >= 1_073_741_824) return `${(bytes / 1_073_741_824).toFixed(2)} GB`;
  if (bytes >= 1_048_576) return `${(bytes / 1_048_576).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

/** Full-manifest delete confirmation (#158): every file's name, folder, and
 *  size plus the total, so the user knows exactly what leaves their library
 *  before anything moves to the Recycle Bin. */
export function TrashConfirmDialog({
  items,
  busy,
  onCancel,
  onConfirm,
}: TrashConfirmDialogProps) {
  const totalBytes = items.reduce((n, i) => n + (i.fileSize ?? 0), 0);
  const knownSizes = items.some((i) => i.fileSize !== null);
  const networkCount = items.filter((i) => i.isNetwork).length;

  return (
    <div className="trash-dialog__overlay" role="dialog" aria-label="Confirm delete">
      <div className="trash-dialog">
        <h3 className="trash-dialog__title">
          Delete {items.length} photo{items.length === 1 ? "" : "s"}?
        </h3>
        <p className="trash-dialog__summary">
          These files will be <strong>removed from your library folders</strong>
          {knownSizes ? (
            <>
              , freeing <strong>{fmtSize(totalBytes)}</strong>
            </>
          ) : null}
          . Every file is also <strong>backed up inside the app for 7 days</strong>{" "}
          before removal — local files also go to the Windows Recycle Bin when
          possible; restore any of them anytime from Restore Backups (··· menu)
          or the Recycle Bin.
        </p>
        {networkCount > 0 && (
          <p className="trash-dialog__network-warning" role="alert">
            ℹ {networkCount} file{networkCount === 1 ? " is" : "s are"} on a
            network folder (marked below) — those typically skip the Windows
            Recycle Bin, but the app backup covers them the same way.
          </p>
        )}

        <ul className="trash-dialog__list" aria-label="Files to delete">
          {items.map((item) => (
            <li key={item.id} className="trash-dialog__item">
              <img
                className="trash-dialog__thumb"
                src={item.thumbSrc}
                alt={item.filename}
                loading="lazy"
              />
              <span className="trash-dialog__filename">{item.filename}</span>
              <span className="trash-dialog__folder" title={item.folder}>
                {item.folder}
              </span>
              {item.isNetwork && (
                <span className="trash-dialog__network-tag">network</span>
              )}
              <span className="trash-dialog__size">{fmtSize(item.fileSize)}</span>
            </li>
          ))}
        </ul>

        <div className="trash-dialog__actions">
          <button
            type="button"
            className="trash-dialog__btn trash-dialog__btn--ghost"
            onClick={onCancel}
            disabled={busy}
          >
            Cancel
          </button>
          <button
            type="button"
            className="trash-dialog__btn trash-dialog__btn--danger"
            onClick={onConfirm}
            disabled={busy}
          >
            {busy
              ? "Moving…"
              : `Move ${items.length} file${items.length === 1 ? "" : "s"} to Recycle Bin`}
          </button>
        </div>
      </div>
    </div>
  );
}
