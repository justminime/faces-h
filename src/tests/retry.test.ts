import { describe, it, expect, vi } from "vitest";
import { withRetry } from "../api/retry";

describe("withRetry (#78 startup fetch resilience)", () => {
  it("retries a failing call until it succeeds and returns the value", async () => {
    const fn = vi
      .fn()
      .mockRejectedValueOnce(new Error("connection refused"))
      .mockRejectedValueOnce(new Error("connection refused"))
      .mockResolvedValueOnce("ok");

    const result = await withRetry(fn, { delayMs: 0 });

    expect(result).toBe("ok");
    expect(fn).toHaveBeenCalledTimes(3);
  });

  it("returns the value on first success without extra calls", async () => {
    const fn = vi.fn().mockResolvedValue(42);
    const result = await withRetry(fn, { delayMs: 0 });
    expect(result).toBe(42);
    expect(fn).toHaveBeenCalledTimes(1);
  });

  it("gives up after the attempt budget and returns undefined", async () => {
    const fn = vi.fn().mockRejectedValue(new Error("down"));
    const result = await withRetry(fn, { attempts: 4, delayMs: 0 });
    expect(result).toBeUndefined();
    expect(fn).toHaveBeenCalledTimes(4);
  });

  it("stops immediately when the cancel signal is set (e.g. unmount)", async () => {
    const fn = vi.fn().mockRejectedValue(new Error("down"));
    const result = await withRetry(fn, { delayMs: 0, signal: () => true });
    expect(result).toBeUndefined();
    expect(fn).not.toHaveBeenCalled();
  });
});
