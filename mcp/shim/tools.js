/**
 * One MCP tool call: forwards to the SDK client with a long per-request
 * timeout, turns an `isError` result into a thrown ToolError and unwraps the
 * payload. Kept free of express/SDK imports so it can be unit-tested.
 */

import { StudioError } from "./studio.js";

/** The connector ran the tool and reported a failure (`isError`): retrying won't help. */
export class ToolError extends Error {
  constructor(tool, detail) {
    super(`tool ${tool} failed: ${detail}`);
    this.tool = tool;
  }
}

const SIGN_IN_HINT =
  /\b(auth(entication|enticate|orization)?|sign(ed)?[ -]?in|log(ged)?[ -]?in|cookies?|credentials?|unauthori[sz]ed)\b/i;

/**
 * HTTP status for a failure: 401 = the Google session needs attention; 422 =
 * NotebookLM or the connector rejected the request itself (the backend doesn't
 * retry); 502 = transport trouble (child exited, timeout, network: worth a retry).
 */
export function failStatus(err) {
  if (err?.auth) return 401;
  if (err instanceof ToolError) return SIGN_IN_HINT.test(err.message) ? 401 : 422;
  if (err instanceof StudioError) return 422;
  return 502;
}

// notebook_query/chat answers can exceed the SDK's 60 s default; the Python
// provider allows 300 s per call.
export const TOOL_TIMEOUT_MS = 300_000;

export function unwrapToolResult(result) {
  if (result && result.structuredContent !== undefined) return result.structuredContent;
  if (result && Array.isArray(result.content)) {
    const textBlock = result.content.find((c) => c.type === "text");
    if (textBlock) {
      try {
        return JSON.parse(textBlock.text);
      } catch {
        return { text: textBlock.text };
      }
    }
  }
  return result;
}

export async function callMcpTool(client, name, args) {
  const result = await client.callTool({ name, arguments: args ?? {} }, undefined, { timeout: TOOL_TIMEOUT_MS });
  if (result?.isError) {
    throw new ToolError(name, JSON.stringify(result.content ?? result));
  }
  return unwrapToolResult(result);
}
