import { describe, it, expect, beforeEach } from "vitest";
import { useSweepStore } from "../store/sweep";

beforeEach(() => {
  useSweepStore.getState().reset();
});

describe("sweep store (#184)", () => {
  it("starts idle", () => {
    expect(useSweepStore.getState().sweeping).toBeNull();
  });

  it("start() records the person id and name", () => {
    useSweepStore.getState().start(1, "Alice");
    expect(useSweepStore.getState().sweeping).toEqual({
      personId: 1,
      personName: "Alice",
    });
  });

  it("start() accepts a null name (person not named yet, e.g. mid-merge)", () => {
    useSweepStore.getState().start(2, null);
    expect(useSweepStore.getState().sweeping).toEqual({
      personId: 2,
      personName: null,
    });
  });

  it("finish() clears the banner when it matches the currently-shown sweep", () => {
    useSweepStore.getState().start(1, "Alice");
    useSweepStore.getState().finish(1);
    expect(useSweepStore.getState().sweeping).toBeNull();
  });

  it("finish() for a stale/different person does not clear a newer sweep's banner", () => {
    // Two sweeps overlap: person 1 started, then person 2 started before
    // person 1's sweep_complete arrived. Only the most recent is shown, and
    // person 1's late completion must not clear person 2's still-in-progress banner.
    useSweepStore.getState().start(1, "Alice");
    useSweepStore.getState().start(2, "Bob");
    useSweepStore.getState().finish(1);
    expect(useSweepStore.getState().sweeping).toEqual({
      personId: 2,
      personName: "Bob",
    });
  });
});
