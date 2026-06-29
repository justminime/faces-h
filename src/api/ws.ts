import { useUIStore } from "../store/ui";

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
    typeof payload === "object" &&
    payload !== null &&
    "type" in payload &&
    (payload as { type: unknown }).type === "scan_progress"
  ) {
    const { progress } = payload as { type: string; progress: number };
    useUIStore.getState().setScanProgress(progress);
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
