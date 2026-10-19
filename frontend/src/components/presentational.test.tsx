import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { Card, CardBody, CardHeader } from "./Card";
import { EmptyState } from "./EmptyState";
import { ErrorState } from "./ErrorState";
import { SidebarNav } from "./SidebarNav";
import { Skeleton } from "./Skeleton";
import { TopBar } from "./TopBar";

describe("presentational components render", () => {
  it("Card with header + body", () => {
    render(
      <Card>
        <CardHeader>Title</CardHeader>
        <CardBody>Content</CardBody>
      </Card>,
    );
    expect(screen.getByText("Title")).toBeInTheDocument();
    expect(screen.getByText("Content")).toBeInTheDocument();
  });

  it("Skeleton multi-line", () => {
    const { container } = render(<Skeleton lines={3} />);
    expect(container.querySelectorAll(".animate-pulse")).toHaveLength(3);
  });

  it("EmptyState shows title, description, action", () => {
    render(
      <EmptyState title="Nothing here" description="Add something" action={<button>Add</button>} />,
    );
    expect(screen.getByText("Nothing here")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add" })).toBeInTheDocument();
  });

  it("ErrorState is an alert with a retry", () => {
    render(<ErrorState onRetry={() => undefined} />);
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
  });

  it("SidebarNav marks the active route", () => {
    render(
      <MemoryRouter initialEntries={["/admin/review"]}>
        <SidebarNav
          title="Shikshak Dp"
          items={[
            { to: "/admin", label: "Ingestion", icon: "upload_file", end: true },
            { to: "/admin/review", label: "Review", icon: "fact_check" },
          ]}
        />
      </MemoryRouter>,
    );
    expect(screen.getByRole("link", { name: /review/i })).toHaveAttribute("aria-current", "page");
  });

  it("TopBar renders title, back link and right slot", () => {
    render(
      <MemoryRouter>
        <TopBar title="Course X" backTo="/" backLabel="Back" right={<span>right-slot</span>} />
      </MemoryRouter>,
    );
    expect(screen.getByRole("heading", { name: "Course X" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back" })).toBeInTheDocument();
    expect(screen.getByText("right-slot")).toBeInTheDocument();
  });
});
