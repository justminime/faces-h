import { useUIStore } from "../store/ui";
import { useToastStore } from "../store/toast";
import { useLogStore } from "../store/log";
import { useConnectionStore } from "../store/connection";

const RECONNECT_MS = 3_000;

let _ws: WebSocket | null = null;
let _wsUrl = "";
let _wsToken = "";

// ── scan_progress refetch throttle (#110) ────────────────────────────────────
// The sidecar broadcasts scan_progress every ~10 photos; bumping scanVersion on
// every event made App.tsx refetch the full people list + queue count each time
// (~10,000 refetches on a 100k-photo scan). Bump at most once per window during
// a scan; scan_complete / sweep_complete always bump immediately.
const SCAN_BUMP_THROTTLE_MS = 5_000;
let _lastScanBump = 0;

function bumpScanVersionThrottled(): void {
  const now = Date.now();
  if (now - _lastScanBump >= SCAN_BUMP_THROTTLE_MS) {
    _lastScanBump = now;
    useUIStore.getState().bumpScanVersion();
  }
}

function bumpScanVersionNow(): void {
  _lastScanBump = Date.now();
  useUIStore.getState().bumpScanVersion();
}

/** Reset the scan_progress bump throttle (exported for tests). */
export function resetScanBumpThrottle(): void {
  _lastScanBump = 0;
}

// Exported for unit testing; also used as the WebSocket onmessage handler.
export function handleMessage(event: MessageEvent): void {
  let payload: unknown;
  try {
    payload = JSON.parse(event.data as string);
  } catch {
    return;
  }
  if (
    typeof payload !== "object" ||
    payload === null ||
    !("type" in payload)
  ) {
    return;
  }
  const p = payload as { type: string; [k: string]: unknown };
  const log = useLogStore.getState();

  if (p.type === "scan_progress") {
    const scanned = p.scanned as number | undefined;
    const total = p.total as number | undefined;
    const currentFile = p.current_file as string | undefined;
    if (typeof scanned === "number" && typeof total === "number" && total > 0) {
      useUIStore.getState().setScanProgress(scanned / total);
      const pct = Math.round((scanned / total) * 100);
      log.upsertLast(`Scanning… ${scanned.toLocaleString()} / ${total.toLocaleString()} (${pct}%)`, "progress");
      if (currentFile) {
        log.push(`Processing: ${currentFile}`, "debug");
      }
    }
    bumpScanVersionThrottled();
  } else if (p.type === "model_download_progress") {
    const pct = Math.round((p.progress as number) * 100);
    log.upsertLast(`Downloading face model… ${pct}%`, "progress");
    useUIStore.getState().setModelDownloadProgress(p.progress as number);
  } else if (p.type === "scan_complete") {
    const scanned = p.scanned as number | undefined;
    const msg =
      scanned != null && scanned > 0
        ? `Scan complete — ${scanned} new photo${scanned !== 1 ? "s" : ""} added`
        : "Scan complete — no new photos";
    useToastStore.getState().addToast(msg);
    log.push(msg, "success");
    useUIStore.getState().setScanProgress(null);
    bumpScanVersionNow();
  } else if (p.type === "reeval_complete") {
    const moved = p.moved as number;
    const uncertain = p.newly_uncertain as number;
    const name = (p.person_name as string | null) ?? "Unknown";
    const parts: string[] = [`${moved} photo${moved !== 1 ? "s" : ""} moved from ${name}`];
    if (uncertain > 0) parts.push(`${uncertain} flagged for review`);
    const msg = parts.join(", ");
    useToastStore.getState().addToast(msg);
    log.push(msg, "info");
  } else if (p.type === "drive_offline") {
    const rawPath = p.path as string;
    const label = rawPath.startsWith("\\\\") || rawPath.startsWith("//")
      ? rawPath.split(/[/\\]/).filter(Boolean).slice(0, 2).join("\\")
      : rawPath;
    const msg = `Network folder "${label}" is offline — showing existing data`;
    useToastStore.getState().addToast(msg);
    log.push(msg, "warn");
  } else if (p.type === "sweep_complete") {
    const moved = p.moved as number;
    if (moved > 0) {
      const msg = `Found ${moved} more photo${moved !== 1 ? "s" : ""} — refreshing`;
      useToastStore.getState().addToast(msg);
      log.push(msg, "success");
      bumpScanVersionNow();
    }
  } else if (p.type === "log") {
    // Engine log records forwarded by the sidecar's WsLogHandler (#126).
    const message = p.message as string | undefined;
    if (message) {
      const level = (p.level as string | undefined) ?? "info";
      const kind =
        level === "error" || level === "critical" || level === "warning"
          ? "warn"
          : level === "debug"
            ? "debug"
            : "info";
      log.push(`[engine] ${message}`, kind);
    }
  }
}

function connect(): void {
  if (!_wsUrl) return;
  try {
    const url = _wsToken ? `${_wsUrl}?token=${encodeURIComponent(_wsToken)}` : _wsUrl;
    _ws = new WebSocket(url);
    _ws.onmessage = handleMessage;
    _ws.onopen = () => {
      useConnectionStore.getState().wsOpened();
      useLogStore.getState().push("Connected to faces-h sidecar", "success");
    };
    _ws.onclose = () => {
      // The user-facing state lives in the connection banner (#118); this raw
      // line stays in the activity log at debug level only.
      useConnectionStore.getState().wsClosed();
      useLogStore.getState().push("Sidecar disconnected — reconnecting…", "debug");
      setTimeout(connect, RECONNECT_MS);
    };
  } catch {
    // not in a WebSocket-capable context (e.g., tests)
  }
}

export function initWs(sidecarUrl: string, token = ""): void {
  _wsUrl = sidecarUrl.replace(/^http/, "ws") + "/ws";
  _wsToken = token;
  connect();
}

export function closeWs(): void {
  _ws?.close();
  _ws = null;
}
