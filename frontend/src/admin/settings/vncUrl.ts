/** noVNC for the mcp auth browser: `VITE_VNC_URL` when the build sets it,
 * else port 6080 on the host this app is served from (compose publishes it
 * there; it was hardcoded to localhost, which only worked on the dev host). */
export function vncUrl(
  configured: string | undefined,
  loc: { protocol: string; hostname: string },
): string {
  return configured || `${loc.protocol}//${loc.hostname}:6080/vnc.html`;
}
