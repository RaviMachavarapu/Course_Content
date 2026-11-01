import { newToastId, useUIStore } from "./store";

afterEach(() => {
  vi.unstubAllGlobals();
  useUIStore.setState({ toasts: [] });
});

describe("toasts outside a secure context", () => {
  it("still get unique ids when crypto.randomUUID is missing (plain http on a LAN IP)", () => {
    vi.stubGlobal("crypto", { getRandomValues: crypto.getRandomValues.bind(crypto) });
    const a = useUIStore.getState().pushToast({ title: "A", tone: "info" });
    const b = useUIStore.getState().pushToast({ title: "B", tone: "error" });
    expect(a).not.toBe(b);
    expect(useUIStore.getState().toasts.map((t) => t.title)).toEqual(["A", "B"]);
    useUIStore.getState().dismissToast(a);
    expect(useUIStore.getState().toasts.map((t) => t.title)).toEqual(["B"]);
  });

  it("uses randomUUID when it exists", () => {
    vi.stubGlobal("crypto", { randomUUID: () => "uuid-1" });
    expect(newToastId()).toBe("uuid-1");
  });
});
