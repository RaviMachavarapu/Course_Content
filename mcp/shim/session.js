/**
 * The stdio session with the `notebooklm-mcp-server` child process.
 *
 * - Calls run one at a time (a promise queue): the connector holds one browser
 *   session, and every caller (the backend's locked calls, /health, Studio
 *   status polls) shares it, so nothing can interleave on stdio.
 * - When the child exits the SDK closes the transport (`onclose`): the client is
 *   dropped and the next call spawns a new child. A call that finds the client
 *   already disconnected ("Not connected": nothing was sent) reconnects and
 *   retries once; a connection lost mid-call is not retried (it may have run).
 *
 * `connect()` returns a connected SDK Client; injected so this is unit-testable.
 */

import { callMcpTool } from "./tools.js";

const NOT_CONNECTED = /not connected/i;
const CONNECTION_LOST = /connection closed|not connected|EPIPE|ECONNRESET/i;

export function createSession(connect) {
  let client = null;
  let connecting = null;
  let queue = Promise.resolve();
  let pending = 0;

  function drop(c) {
    if (client === c) client = null;
  }

  async function getClient() {
    if (client) return client;
    if (!connecting) {
      connecting = (async () => {
        const c = await connect();
        c.onclose = () => drop(c);
        client = c;
        return c;
      })().finally(() => {
        connecting = null;
      });
    }
    return connecting;
  }

  async function callOnce(name, args) {
    const c = await getClient();
    try {
      return await callMcpTool(c, name, args);
    } catch (err) {
      const message = String(err?.message ?? err);
      if (!CONNECTION_LOST.test(message)) throw err;
      drop(c);
      c.close?.().catch?.(() => {});
      if (!NOT_CONNECTED.test(message)) throw err;
      return callMcpTool(await getClient(), name, args);
    }
  }

  function exclusive(fn) {
    pending += 1;
    const run = queue.then(fn);
    queue = run.then(
      () => {},
      () => {},
    );
    return run.finally(() => {
      pending -= 1;
    });
  }

  async function closeClient() {
    const c = client;
    client = null;
    if (c) await c.close().catch(() => {});
  }

  return {
    /** One tool call, after any call already in progress. */
    call: (name, args) => exclusive(() => callOnce(name, args)),
    /** A call is running or waiting. */
    busy: () => pending > 0,
    /** Start the child now (after the current call) if it isn't running. */
    connect: () => exclusive(getClient),
    /** Close the child (after the current call); the next call starts a new one. */
    reset: () => exclusive(closeClient),
    close: () => exclusive(closeClient),
  };
}
