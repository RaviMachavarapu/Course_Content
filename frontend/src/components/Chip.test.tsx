import { render } from "@testing-library/react";
import { Chip, type ChipStatus } from "./Chip";

const cases: Array<[ChipStatus, RegExp]> = [
  ["processing", /processing/i],
  ["ready", /ready/i],
  ["error", /error/i],
  ["published", /published/i],
  ["pending", /pending review/i],
];

describe("Chip", () => {
  it.each(cases)("renders the %s status with its default label", (status, label) => {
    const { container } = render(<Chip status={status} />);
    const chip = container.querySelector("[data-status]");
    expect(chip?.getAttribute("data-status")).toBe(status);
    expect(chip).toHaveTextContent(label);
  });

  it("allows overriding the label", () => {
    const { container } = render(<Chip status="ready">Approved</Chip>);
    expect(container.querySelector("[data-status]")).toHaveTextContent("Approved");
  });
});
