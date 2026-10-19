import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { AppProviders } from "./providers";
import { StyleGuide } from "./StyleGuide";

describe("StyleGuide", () => {
  it("renders every UI-kit section and all chip statuses", () => {
    render(
      <AppProviders>
        <MemoryRouter>
          <StyleGuide />
        </MemoryRouter>
      </AppProviders>,
    );

    expect(screen.getByRole("heading", { name: /UI Kit/i })).toBeInTheDocument();
    for (const title of [
      "Typography",
      "Button",
      "Card",
      "Chip — status",
      "Input & Select",
      "Tabs",
      "Progress",
      "Skeleton",
      "Modal & Toast",
      "Empty & Error states",
      "TopBar",
      "SidebarNav",
    ]) {
      expect(screen.getByRole("heading", { name: title })).toBeInTheDocument();
    }

    for (const status of ["Processing", "Ready", "Error", "Published", "Pending Review"]) {
      expect(screen.getAllByText(status).length).toBeGreaterThan(0);
    }
  });
});
