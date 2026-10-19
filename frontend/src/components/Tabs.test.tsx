import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { TabPanel, Tabs } from "./Tabs";

function Harness(): JSX.Element {
  const [value, setValue] = useState("a");
  return (
    <>
      <Tabs
        tabs={[
          { id: "a", label: "First" },
          { id: "b", label: "Second" },
        ]}
        value={value}
        onChange={setValue}
      />
      <TabPanel id="a" active={value === "a"}>
        Panel A
      </TabPanel>
      <TabPanel id="b" active={value === "b"}>
        Panel B
      </TabPanel>
    </>
  );
}

describe("Tabs", () => {
  it("switches the selected tab and visible panel", async () => {
    render(<Harness />);
    expect(screen.getByRole("tab", { name: "First" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("Panel A")).toBeVisible();
    expect(screen.getByText("Panel B")).not.toBeVisible();

    await userEvent.click(screen.getByRole("tab", { name: "Second" }));

    expect(screen.getByRole("tab", { name: "Second" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("Panel B")).toBeVisible();
    expect(screen.getByText("Panel A")).not.toBeVisible();
  });
});
