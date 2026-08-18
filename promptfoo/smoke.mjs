// Standalone smoke test for the chat provider — runs one test case and
// prints the raw provider response. Useful to confirm wiring without
// running the full promptfoo suite.
//
// Usage:
//   node smoke.mjs
//
// Requires the FastAPI app running on CHAT_URL (default http://localhost:3000).

import "dotenv/config";
import chatProvider from "./providers/chat-provider.mjs";

const chatUrl = process.env.CHAT_URL || "http://localhost:3000";

const fakeContext = {
  vars: {
    message: "Oi, bom dia!",
    session_state: { terms_accepted: true },
  },
  test: { description: "smoke-test-greeting" },
};

console.log(`[smoke] chatUrl=${chatUrl}`);
console.log("[smoke] calling provider...");

try {
  const resp = await chatProvider("(rendered prompt ignored)", fakeContext);
  console.log("[smoke] provider returned:");
  console.log(JSON.stringify(resp, null, 2).slice(0, 2000));
} catch (e) {
  console.error("[smoke] provider threw:", e);
  process.exit(1);
}