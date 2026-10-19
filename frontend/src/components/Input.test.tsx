import { render, screen } from "@testing-library/react";
import { Input } from "./Input";
import { Select } from "./Select";

describe("Input", () => {
  it("associates the label with the field", () => {
    render(<Input label="Email" />);
    expect(screen.getByLabelText("Email")).toBeInstanceOf(HTMLInputElement);
  });

  it("shows an error and marks the field invalid", () => {
    render(<Input label="Email" error="Required" />);
    const field = screen.getByLabelText("Email");
    expect(field).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByText("Required")).toBeInTheDocument();
  });

  it("renders a hint when there is no error", () => {
    render(<Input label="Email" hint="No spam" />);
    expect(screen.getByText("No spam")).toBeInTheDocument();
  });
});

describe("Select", () => {
  it("renders options and a disabled placeholder", () => {
    render(
      <Select
        label="Voice"
        placeholder="Pick one"
        options={[
          { value: "f", label: "Female" },
          { value: "m", label: "Male" },
        ]}
      />,
    );
    expect(screen.getByRole("option", { name: "Pick one" })).toBeDisabled();
    expect(screen.getByRole("option", { name: "Female" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Male" })).toBeInTheDocument();
  });
});
