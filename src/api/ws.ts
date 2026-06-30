import { useUIStore } from "../store/ui";
import { useToastStore } from "../store/toast";

const RECONNECT_MS = 3_000;

let _ws: WebSocket | null = null;
let _wsUrl = "";

function handleMessage(event: MessageEvent): void {
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
  if (p.type === "scan_progress") {
    // Backend sends scanned/total (not a precomputed progress fraction).
    const scanned = p.scanned as number | undefined;
    const total = p.total as number | undefined;
    if (typeof scanned === "number" && typeof total === "number" && total > 0) {
      useUIStore.getState().setScanProgress(scanned / total);
    }
    // Refresh the sidebar live as faces are detected — don't wait for the whole
    // scan to finish before showing anything.
    useUIStore.getState().bumpScanVersion();
  } else if (p.type === "model_download_progress") {
    useUIStore.getState().setModelDownloadProgress(p.progress as number);
  } else if (p.type === "scan_complete") {
    const scanned = p.scanned as number | undefined;
    const msg =
      scanned != null && scanned > 0
        ? `Scan complete — ${scanned} new photo${scanned !== 1 ? "s" : ""} added`
        : "Scan complete";
    useToastStore.getState().addToast(msg);
    useUIStore.getState().setScanProgress(null);
    useUIStore.getState().bumpScanVersion();
  } else if (p.type === "reeval_complete") {
    const moved = p.moved as number;
    const uncertain = p.newly_uncertain as number;
    const name = (p.person_name as string | null) ?? "Unknown";
    const parts: string[] = [`${moved} photo${moved !== 1 ? "s" : ""} moved from ${name}`];
    if (uncertain > 0) parts.push(`${uncertain} flagged for review`);
    useToastStore.getState().addToast(parts.join(", "));
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
