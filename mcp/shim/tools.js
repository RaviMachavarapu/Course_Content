/**
 * One MCP tool call: forwards to the SDK client with a long per-request
 * timeout, turns an `isError` result into a thrown Error and unwraps the
 * payload. Kept free of express/SDK imports so it can be unit-tested.
 */

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
    throw new Error(`tool ${name} failed: ${JSON.stringify(result.content ?? result)}`);
  }
  return unwrapToolResult(result);
}
