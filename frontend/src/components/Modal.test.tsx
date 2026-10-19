import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Modal } from "./Modal";

function open(onClose = vi.fn()) {
  render(
    <Modal open onClose={onClose} title="Confirm">
      <p>Body</p>
    </Modal>,
  );
  return onClose;
}

describe("Modal", () => {
  it("renders nothing when closed", () => {
    render(
      <Modal open={false} onClose={vi.fn()} title="Confirm">
        <p>Body</p>
      </Modal>,
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("renders a labelled dialog when open", () => {
    open();
    expect(screen.getByRole("dialog", { name: "Confirm" })).toBeInTheDocument();
  });

  it("closes on the close button, Escape, and backdrop click", async () => {
    const onClose = open();
    await userEvent.click(screen.getByRole("button", { name: /close dialog/i }));
    await userEvent.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalled();
  });
});
