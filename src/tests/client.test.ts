import { describe, expect, it, vi, afterEach } from "vitest";
import {
  initClient,
  photoThumbUrl,
  faceCropUrl,
  exportLibrary,
  importLibrary,
} from "../api/client";

describe("image URL helpers", () => {
  it("builds an absolute photo thumbnail URL pointing at the sidecar", () => {
    initClient("http://127.0.0.1:51423");
    expect(photoThumbUrl(5)).toBe(
      "http://127.0.0.1:51423/photos/5/thumbnail?size=256",
    );
  });

  it("honours a custom thumbnail size", () => {
    initClient("http://127.0.0.1:51423");
    expect(photoThumbUrl(5, 512)).toBe(
      "http://127.0.0.1:51423/photos/5/thumbnail?size=512",
    );
  });

  it("builds an absolute face crop URL pointing at the sidecar", () => {
    initClient("http://127.0.0.1:51423");
    expect(faceCropUrl(9)).toBe("http://127.0.0.1:51423/faces/9/crop");
  });

  it("reflects the base URL set by initClient", () => {
    initClient("http://localhost:9999");
    expect(photoThumbUrl(1)).toBe(
      "http://localhost:9999/photos/1/thumbnail?size=256",
    );
    expect(faceCropUrl(1)).toBe("http://localhost:9999/faces/1/crop");
  });
});

describe("library import/export (#80)", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("exportLibrary GETs /export against the sidecar", async () => {
    initClient("http://127.0.0.1:51423");
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ version: 1, exported_at: 0, people: [] }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const bundle = await exportLibrary();
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:51423/export",
      expect.anything(),
    );
    expect(bundle.version).toBe(1);
  });

  it("importLibrary POSTs the bundle to /import", async () => {
    initClient("http://127.0.0.1:51423");
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ applied: 2, unmatched: [], conflicts: [], total: 2 }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const summary = await importLibrary({ version: 1, people: [] });
    const [url, opts] = fetchMock.mock.calls[0];
    expect(url).toBe("http://127.0.0.1:51423/import");
    expect(opts.method).toBe("POST");
    expect(summary.applied).toBe(2);
  });
});
