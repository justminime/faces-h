import { describe, it, expect, beforeEach } from "vitest";
import { act, render, screen } from "@testing-library/react";
import { SweepBanner } from "../components/SweepBanner";
import { useSweepStore } from "../store/sweep";

beforeEach(() => {
  useSweepStore.getState().reset();
});

describe("SweepBanner (#184)", () => {
  it("renders nothing when idle", () => {
    render(<SweepBanner />);
    expect(screen.queryByTestId("sweep-banner")).not.toBeInTheDocument();
  });

  it("shows the looking-for-matches message with the person's name while sweeping", () => {
    useSweepStore.setState({ sweeping: { personId: 1, personName: "Alice" } });
    render(<SweepBanner />);
    expect(screen.getByTestId("sweep-banner")).toBeInTheDocument();
    expect(screen.getByText("Looking for more matches for Alice…")).toBeInTheDocument();
  });

  it("falls back to a generic message when the person's name isn't known yet", () => {
    useSweepStore.setState({ sweeping: { personId: 2, personName: null } });
    render(<SweepBanner />);
    expect(screen.getByText("Looking for more matches…")).toBeInTheDocument();
  });

  it("clears once the sweep store is reset (mirrors sweep_complete)", () => {
    useSweepStore.setState({ sweeping: { personId: 1, personName: "Alice" } });
    render(<SweepBanner />);
    expect(screen.getByTestId("sweep-banner")).toBeInTheDocument();

    act(() => {
      useSweepStore.getState().finish(1);
    });
    expect(screen.queryByTestId("sweep-banner")).not.toBeInTheDocument();
  });
});
