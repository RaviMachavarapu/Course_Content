import { render, screen } from "@testing-library/react";
import { SourceSummary } from "./SourceSummary";

const file = (name: string, parts = 1) => ({ file_name: name, size_bytes: 10, part_count: parts });

describe("SourceSummary", () => {
  it("shows only the link when there are no PDFs", () => {
    render(<SourceSummary sourceUrl="https://example.com/a" files={[]} />);
    expect(screen.getByText("https://example.com/a")).toBeInTheDocument();
    expect(screen.queryByText(/PDF/)).not.toBeInTheDocument();
  });

  it("shows a singular PDF count", () => {
    render(<SourceSummary sourceUrl={null} files={[file("a.pdf")]} />);
    expect(screen.getByText("📄 1 PDF")).toHaveAttribute("title", "a.pdf");
  });

  it("shows a plural count with the names in the title", () => {
    render(
      <SourceSummary
        sourceUrl="https://example.com/a"
        files={[file("a.pdf"), file("b.pdf"), file("c.pdf")]}
      />,
    );
    expect(screen.getByText("📄 3 PDFs")).toHaveAttribute("title", "a.pdf, b.pdf, c.pdf");
    expect(screen.getByText("https://example.com/a")).toBeInTheDocument();
  });

  it("detailed mode lists names and split parts", () => {
    render(
      <SourceSummary sourceUrl={null} files={[file("book.pdf", 3), file("n.pdf")]} detailed />,
    );
    expect(screen.getByText("book.pdf (split into 3 parts)")).toBeInTheDocument();
    expect(screen.getByText("n.pdf")).toBeInTheDocument();
  });
});
