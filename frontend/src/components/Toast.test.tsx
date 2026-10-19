import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useUIStore } from "@/lib/store";
import { Toaster } from "./Toast";

beforeEach(() => {
  act(() => useUIStore.setState({ toasts: [] }));
});

describe("Toaster", () => {
  it("renders queued toasts and dismisses them", async () => {
    render(<Toaster />);
    act(() => {
      useUIStore.getState().pushToast({ title: "Saved", tone: "success" });
    });
    const alert = await screen.findByRole("status");
    expect(alert).toHaveTextContent("Saved");

    await userEvent.click(screen.getByRole("button", { name: /dismiss notification/i }));
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});
