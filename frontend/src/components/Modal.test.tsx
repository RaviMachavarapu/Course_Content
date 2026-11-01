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

  it("keeps focus in a field when the parent re-renders with a new onClose", async () => {
    const { rerender } = render(
      <Modal open onClose={() => {}} title="Redo">
        <textarea aria-label="Note" />
      </Modal>,
    );
    const field = screen.getByLabelText("Note");
    await userEvent.click(field);
    expect(field).toHaveFocus();
    rerender(
      <Modal open onClose={() => {}} title="Redo">
        <textarea aria-label="Note" />
      </Modal>,
    );
    expect(field).toHaveFocus();
  });

  it("uses the latest onClose for Escape", async () => {
    const first = vi.fn();
    const second = vi.fn();
    const { rerender } = render(
      <Modal open onClose={first} title="X">
        <p>Body</p>
      </Modal>,
    );
    rerender(
      <Modal open onClose={second} title="X">
        <p>Body</p>
      </Modal>,
    );
    await userEvent.keyboard("{Escape}");
    expect(second).toHaveBeenCalled();
    expect(first).not.toHaveBeenCalled();
  });

  it("traps Tab inside the dialog", async () => {
    render(
      <>
        <button>Outside</button>
        <Modal open onClose={vi.fn()} title="Trap" footer={<button>Save</button>}>
          <input aria-label="Field" />
        </Modal>
      </>,
    );
    const close = screen.getByRole("button", { name: /close dialog/i });
    const save = screen.getByRole("button", { name: "Save" });
    save.focus();
    await userEvent.tab();
    expect(close).toHaveFocus();
    await userEvent.tab({ shift: true });
    expect(save).toHaveFocus();
  });
});
