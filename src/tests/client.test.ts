import { describe, expect, it } from "vitest";
import { initClient, photoThumbUrl, faceCropUrl } from "../api/client";

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
