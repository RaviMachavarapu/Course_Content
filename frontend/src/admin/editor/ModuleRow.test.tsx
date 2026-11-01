import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import type { ModuleSummary } from "../api";
import { ModuleRow } from "./ModuleRow";

it("renders a PDF-only module without a link", () => {
  const module: ModuleSummary = {
    id: "m1",
    order_index: 0,
    title: "From files",
    source_url: null,
    source_files: [
      { file_name: "a.pdf", size_bytes: 1, part_count: 1 },
      { file_name: "b.pdf", size_bytes: 1, part_count: 1 },
    ],
    source_type: "pdf",
    status: "ready",
    artifacts: [],
  };
  render(
    <MemoryRouter>
      <ModuleRow
        module={module}
        index={0}
        isFirst
        isLast
        busy={false}
        onRename={() => {}}
        onMove={() => {}}
        onRegenerate={() => {}}
        onDelete={() => {}}
      />
    </MemoryRouter>,
  );
  expect(screen.getByText("📄 2 PDFs")).toHaveAttribute("title", "a.pdf, b.pdf");
});
