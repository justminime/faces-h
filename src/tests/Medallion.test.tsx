import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { Medallion } from "../components/Medallion";

const SRC = "face.jpg";
const ALT = "Alice";

describe("Medallion", () => {
  it("renders with src and alt", () => {
    render(<Medallion src={SRC} alt={ALT} />);
    const img = screen.getByAltText(ALT);
    expect(img).toBeInTheDocument();
    expect(img).toHaveAttribute("src", SRC);
  });

  it("has selected class when selected={true}", () => {
    const { container } = render(<Medallion src={SRC} alt={ALT} selected={true} />);
    const medallion = container.firstChild as HTMLElement;
    expect(medallion.classList.contains("medallion--selected")).toBe(true);
  });

  it("does not have selected class when selected={false}", () => {
    const { container } = render(<Medallion src={SRC} alt={ALT} selected={false} />);
    const medallion = container.firstChild as HTMLElement;
    expect(medallion.classList.contains("medallion--selected")).toBe(false);
  });

  it("applies custom size via inline style", () => {
    const { container } = render(<Medallion src={SRC} alt={ALT} size={96} />);
    const medallion = container.firstChild as HTMLElement;
    expect(medallion.style.width).toBe("96px");
    expect(medallion.style.height).toBe("96px");
  });
});
