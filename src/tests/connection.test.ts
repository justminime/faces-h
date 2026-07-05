import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { useConnectionStore, LOST_DEBOUNCE_MS } from "../store/connection";

const phase = () => useConnectionStore.getState().phase;

beforeEach(() => {
  vi.useFakeTimers();
  useConnectionStore.getState().reset();
});

afterEach(() => {
  useConnectionStore.getState().reset();
  vi.useRealTimers();
});

describe("connection store (#118 startup state machine)", () => {
  it("starts in engine-starting", () => {
    expect(phase()).toBe("engine-starting");
  });

  it("follows the happy path: engine-starting → connecting → loading-library → connected", () => {
    const s = useConnectionStore.getState();
    s.engineReady();
    expect(phase()).toBe("connecting");
    s.loadingLibrary();
    expect(phase()).toBe("loading-library");
    s.connected();
    expect(phase()).toBe("connected");
  });

  it("keeps the engine-starting message during early retries, but records the attempt", () => {
    const s = useConnectionStore.getState();
    s.retryAttempt(3);
    expect(phase()).toBe("engine-starting");
    expect(useConnectionStore.getState().attempt).toBe(3);
  });

  it("shows connecting with the attempt count once the engine is up", () => {
    const s = useConnectionStore.getState();
    s.engineReady();
    s.retryAttempt(5);
    expect(phase()).toBe("connecting");
    expect(useConnectionStore.getState().attempt).toBe(5);
  });

  it("downgrades loading-library back to connecting when a retry starts", () => {
    const s = useConnectionStore.getState();
    s.engineReady();
    s.loadingLibrary();
    s.retryAttempt(2);
    expect(phase()).toBe("connecting");
  });

  it("engineReady is a no-op once past startup", () => {
    const s = useConnectionStore.getState();
    s.engineReady();
    s.loadingLibrary();
    s.connected();
    s.engineReady();
    expect(phase()).toBe("connected");
  });

  it("can reach connected straight from engine-starting (dev mode: no sidecar-ready event)", () => {
    useConnectionStore.getState().connected();
    expect(phase()).toBe("connected");
  });

  describe("lost debounce", () => {
    it("shows lost only after the WebSocket stays closed for the debounce window", () => {
      const s = useConnectionStore.getState();
      s.connected();
      s.wsClosed();
      vi.advanceTimersByTime(LOST_DEBOUNCE_MS - 1);
      expect(phase()).toBe("connected");
      vi.advanceTimersByTime(1);
      expect(phase()).toBe("lost");
    });

    it("does not flash on a brief reconnect (<3s)", () => {
      const s = useConnectionStore.getState();
      s.connected();
      s.wsClosed();
      vi.advanceTimersByTime(2_000);
      s.wsOpened();
      vi.advanceTimersByTime(10_000);
      expect(phase()).toBe("connected");
    });

    it("recovers from lost when the WebSocket reopens", () => {
      const s = useConnectionStore.getState();
      s.connected();
      s.wsClosed();
      vi.advanceTimersByTime(LOST_DEBOUNCE_MS);
      expect(phase()).toBe("lost");
      s.wsOpened();
      expect(phase()).toBe("connected");
    });

    it("does not show lost during startup — the startup banner already explains", () => {
      const s = useConnectionStore.getState();
      s.engineReady();
      s.wsClosed();
      vi.advanceTimersByTime(LOST_DEBOUNCE_MS + 1_000);
      expect(phase()).toBe("connecting");
    });
  });

  describe("failed", () => {
    it("enters failed on sidecar-error from any phase", () => {
      const s = useConnectionStore.getState();
      s.engineReady();
      s.failed();
      expect(phase()).toBe("failed");
    });

    it("is persistent — later startup signals do not clear it", () => {
      const s = useConnectionStore.getState();
      s.failed();
      s.engineReady();
      s.loadingLibrary();
      s.connected();
      expect(phase()).toBe("failed");
    });
  });
});
