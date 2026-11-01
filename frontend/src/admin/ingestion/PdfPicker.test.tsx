import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { PdfPicker, type PickedFile } from "./PdfPicker";

function file(name: string, size = 1024): File {
  return new File([new Uint8Array(size)], name);
}

function picked(over: Partial<PickedFile> & { id: string; name: string }): PickedFile {
  const { name, ...rest } = over;
  return { file: file(name, 2048), sent: 0, total: 2048, state: "uploading", ...rest };
}

function drop(files: File[]) {
  fireEvent.drop(screen.getByTestId("pdf-dropzone"), { dataTransfer: { files } });
}

describe("PdfPicker", () => {
  it("adds dropped PDFs via onAdd", () => {
    const onAdd = vi.fn();
    render(<PdfPicker files={[]} onAdd={onAdd} onRemove={vi.fn()} onRetry={vi.fn()} />);
    const a = file("a.pdf");
    const b = file("B.PDF");
    drop([a, b]);
    expect(onAdd).toHaveBeenCalledWith([a, b]);
  });

  it("lists a row per file with name and size", () => {
    render(
      <PdfPicker
        files={[
          picked({ id: "1", name: "one.pdf", state: "done" }),
          picked({ id: "2", name: "two.pdf", sent: 1024 }),
        ]}
        onAdd={vi.fn()}
        onRemove={vi.fn()}
        onRetry={vi.fn()}
      />,
    );
    expect(screen.getByText("one.pdf")).toBeInTheDocument();
    expect(screen.getByText("two.pdf")).toBeInTheDocument();
    expect(screen.getAllByText("2 KB")).toHaveLength(2);
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "50");
  });

  it("refuses a non-PDF before upload with its name in the message", async () => {
    const onAdd = vi.fn();
    render(<PdfPicker files={[]} onAdd={onAdd} onRemove={vi.fn()} onRetry={vi.fn()} />);
    drop([file("notes.docx")]);
    expect(await screen.findByText("notes.docx is not a PDF")).toBeInTheDocument();
    expect(onAdd).not.toHaveBeenCalled();
  });

  it("still adds the PDFs from a mixed drop", () => {
    const onAdd = vi.fn();
    render(<PdfPicker files={[]} onAdd={onAdd} onRemove={vi.fn()} onRetry={vi.fn()} />);
    const ok = file("ok.pdf");
    drop([file("x.docx"), ok]);
    expect(onAdd).toHaveBeenCalledWith([ok]);
    expect(screen.getByText("x.docx is not a PDF")).toBeInTheDocument();
  });

  it("removes a row with the cross button", async () => {
    const onRemove = vi.fn();
    render(
      <PdfPicker
        files={[picked({ id: "1", name: "one.pdf", state: "done" })]}
        onAdd={vi.fn()}
        onRemove={onRemove}
        onRetry={vi.fn()}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Remove one.pdf" }));
    expect(onRemove).toHaveBeenCalledWith("1");
  });

  it("shows the error and a Retry button for a failed upload", async () => {
    const onRetry = vi.fn();
    render(
      <PdfPicker
        files={[
          picked({ id: "1", name: "bad.pdf", state: "error", error: "bad.pdf is not a PDF" }),
        ]}
        onAdd={vi.fn()}
        onRemove={vi.fn()}
        onRetry={onRetry}
      />,
    );
    expect(screen.getByText("bad.pdf is not a PDF")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(onRetry).toHaveBeenCalledWith("1");
  });

  it("shows no Retry button while uploading or done", () => {
    render(
      <PdfPicker
        files={[
          picked({ id: "1", name: "a.pdf" }),
          picked({ id: "2", name: "b.pdf", state: "done" }),
        ]}
        onAdd={vi.fn()}
        onRemove={vi.fn()}
        onRetry={vi.fn()}
      />,
    );
    expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
  });
});
