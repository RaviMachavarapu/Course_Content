import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { mockFetch, renderAuthRoute } from "./authTestUtils";

afterEach(() => vi.unstubAllGlobals());

const user = {
  id: "1",
  email: "new@example.com",
  display_name: "New",
  role: "student",
  is_active: true,
  created_at: "",
};

async function fillValid(): Promise<void> {
  await userEvent.type(screen.getByLabelText("Display name"), "New Learner");
  await userEvent.type(screen.getByLabelText("Email"), "new@example.com");
  await userEvent.type(screen.getByLabelText("Password", { exact: true }), "strong-pw-2468");
  await userEvent.type(screen.getByLabelText("Confirm password"), "strong-pw-2468");
}

describe("RegisterPage", () => {
  it("wires BTN-SL1", () => {
    renderAuthRoute("/register");
    expect(screen.getByTestId("btn-sl1")).toHaveTextContent(/create account/i);
  });

  it("mirrors the server password rule and confirm match", async () => {
    const fetchMock = mockFetch();
    renderAuthRoute("/register");
    await userEvent.type(screen.getByLabelText("Display name"), "New Learner");
    await userEvent.type(screen.getByLabelText("Email"), "new@example.com");
    await userEvent.type(screen.getByLabelText("Password", { exact: true }), "short");
    await userEvent.type(screen.getByLabelText("Confirm password"), "different");
    await userEvent.click(screen.getByTestId("btn-sl1"));

    expect(await screen.findByText(/at least 10 characters/i)).toBeInTheDocument();
    expect(screen.getByText(/passwords do not match/i)).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("shows a duplicate-email server error on the email field", async () => {
    mockFetch({
      status: 409,
      body: { error: { code: "email_taken", message: "That email is already registered" } },
    });
    renderAuthRoute("/register");
    await fillValid();
    await userEvent.click(screen.getByTestId("btn-sl1"));
    expect(await screen.findByText(/already registered/i)).toBeInTheDocument();
  });

  it("redirects to /catalog on success", async () => {
    mockFetch({ status: 201, body: { user } });
    renderAuthRoute("/register");
    await fillValid();
    await userEvent.click(screen.getByTestId("btn-sl1"));
    await waitFor(() => expect(screen.getByText("CATALOG PAGE")).toBeInTheDocument());
  });

  it("explains a rate limit", async () => {
    mockFetch({
      status: 429,
      body: { error: { code: "rate_limited", message: "Too many attempts. Try again later." } },
    });
    renderAuthRoute("/register");
    await fillValid();
    await userEvent.click(screen.getByTestId("btn-sl1"));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Too many attempts — please try again later.",
    );
  });
});
