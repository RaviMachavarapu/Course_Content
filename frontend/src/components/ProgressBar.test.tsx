import { render, screen } from "@testing-library/react";
import { ProgressBar } from "./ProgressBar";

describe("ProgressBar", () => {
  it("exposes the rounded value via ARIA", () => {
    render(<ProgressBar value={42.6} />);
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "43");
  });

  it("clamps out-of-range values", () => {
    render(
      <>
        <ProgressBar value={-10} />
        <ProgressBar value={250} />
      </>,
    );
    const [low, high] = screen.getAllByRole("progressbar");
    expect(low).toHaveAttribute("aria-valuenow", "0");
    expect(high).toHaveAttribute("aria-valuenow", "100");
  });

  it("renders a percentage label when asked", () => {
    render(<ProgressBar value={75} showLabel />);
    expect(screen.getByText("75%")).toBeInTheDocument();
  });
});
