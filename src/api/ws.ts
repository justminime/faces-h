import { useUIStore } from "../store/ui";
import { useToastStore } from "../store/toast";
import { useLogStore } from "../store/log";

const RECONNECT_MS = 3_000;

let _ws: WebSocket | null = null;
let _wsUrl = "";

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
    useUIStore.getState().bumpScanVersion();
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
    useUIStore.getState().bumpScanVersion();
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
      useUIStore.getState().bumpScanVersion();
    }
  }
}

function connect(): void {
  if (!_wsUrl) return;
  try {
    _ws = new WebSocket(_wsUrl);
    _ws.onmessage = handleMessage;
    _ws.onclose = () => {
      setTimeout(connect, RECONNECT_MS);
    };
  } catch {
    // not in a WebSocket-capable context (e.g., tests)
  }
}

export function initWs(sidecarUrl: string): void {
  _wsUrl = sidecarUrl.replace(/^http/, "ws") + "/ws";
  connect();
}

export function closeWs(): void {
  _ws?.close();
  _ws = null;
}
