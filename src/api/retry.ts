/**
 * Run `fn`, retrying on any thrown/rejected error with a fixed backoff until it
 * succeeds or `attempts` is exhausted. Used for the initial data load: the
 * sidecar URL is known immediately but the process can take up to ~100s to
 * start on a fresh install (Windows Defender scans the new binary), so a
 * one-shot fetch would race ahead and leave the UI empty (#78).
 *
 * Returns the resolved value on success, or `undefined` if every attempt failed
 * or `signal()` requested cancellation (e.g. component unmounted).
 */
export async function withRetry<T>(
  fn: () => Promise<T>,
  opts: { attempts?: number; delayMs?: number; signal?: () => boolean } = {},
): Promise<T | undefined> {
  const { attempts = 150, delayMs = 2000, signal } = opts;
  for (let i = 0; i < attempts; i++) {
    if (signal?.()) return undefined;
    try {
      return await fn();
    } catch {
      if (i < attempts - 1) {
        await new Promise((resolve) => setTimeout(resolve, delayMs));
      }
    }
  }
  return undefined;
}
