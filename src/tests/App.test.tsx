import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import App from "../App";

describe("App", () => {
  it("renders without throwing", () => {
    render(<App />);
  });

  it("displays the app name", () => {
    render(<App />);
    expect(screen.getByText("faces-h")).toBeInTheDocument();
  });
});
