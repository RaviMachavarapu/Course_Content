import { vncUrl } from "./NotebookLmTab";

describe("vncUrl", () => {
  it("uses the configured URL when set", () => {
    expect(vncUrl("https://ops.example/vnc.html", { protocol: "https:", hostname: "app" })).toBe(
      "https://ops.example/vnc.html",
    );
  });
  it("otherwise points at port 6080 on the host serving the app", () => {
    expect(vncUrl(undefined, { protocol: "http:", hostname: "devbox.local" })).toBe(
      "http://devbox.local:6080/vnc.html",
    );
  });
});
