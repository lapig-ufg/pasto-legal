// Custom promptfoo ProviderFunction that talks to the Pasto Legal FastAPI
// /chat endpoint. The agent (pi coding agent subprocess) is spawned and
// managed by the app — this provider just forwards the user message and
// returns the full /chat JSON for assertions to inspect.
//
// The provider expects the following vars on the test case:
//   - vars.message       (string)  user message sent to the agent
//   - vars.session_state (object)  initial session_state (see data/session-fixtures.mjs)
//   - vars.reset_before  (boolean, default true) — POST /reset before /chat
//       so each test starts from a clean pi session (deterministic, no
//       cross-test history contamination).
//
// No warmup is needed: /chat only checks the DB for terms acceptance when
// `session_state.terms_accepted` is falsy (api/main.py:200). Sending
// `terms_accepted: true` in the session_state bypasses the onboarding gate
// directly and routes to the normal flow.
//
// Output: the agent's text response (result.content). The full /chat JSON is
// available to assertions via context.providerResponse.metadata.
//
// The provider also sets `metadata.toolCalls` (array of {name, args}) and
// `metadata.sessionState` (merged) so assertions can use them directly.

const ALLOWED_TOOLS = (await import("../data/tools-allowed.mjs")).ALLOWED_TOOLS;

function makeUserId(prefix, testName) {
  // Stable, unique per test: prefix + slugified test description.
  const slug = String(testName || "case")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 48);
  return `${prefix}-${slug}`;
}

async function postJson(url, body, timeoutMs = 180_000) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(url, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
      signal: ctrl.signal,
    });
    const text = await res.text();
    let json;
    try {
      json = JSON.parse(text);
    } catch {
      json = { _parseError: text };
    }
    if (!res.ok) {
      throw new Error(`${url} -> HTTP ${res.status}: ${text.slice(0, 400)}`);
    }
    return json;
  } finally {
    clearTimeout(timer);
  }
}

export default async function chatProvider(prompt, context) {
  // prompt is the rendered prompt string (we use a function-prompt in run.mjs
  // that returns vars.message, so prompt === vars.message). context.vars
  // carries the test vars.
  const vars = context?.vars || {};
  const message = vars.message ?? (typeof prompt === "string" ? prompt : "");
  if (!message) {
    throw new Error("chatProvider: vars.message is required");
  }
  const sessionState = vars.session_state || {};
  const resetBefore = vars.reset_before !== false;
  const userId =
    vars.user_id || makeUserId(String(context?.test?.description || "promptfoo"), String(context?.test?.description || ""));

  const chatUrl = process.env.CHAT_URL || "http://localhost:3000";

  if (resetBefore) {
    try {
      await postJson(`${chatUrl}/reset`, { user_id: userId }, 10_000);
    } catch (e) {
      // Reset is best-effort; if the pool doesn't have the user yet it's fine.
    }
  }

  // ── Real test message ──────────────────────────────────────────────
  const chatBody = {
    user_id: userId,
    message,
    session_state: sessionState,
    images: [],
    audio: [],
    recent_queries: [],
  };

  let result;
  try {
    result = await postJson(`${chatUrl}/chat`, chatBody, 180_000);
  } catch (e) {
    return {
      error: String(e?.message || e),
      output: "",
      prompt: message,
      metadata: { userId, chatUrl, phase: "test" },
    };
  }

  // Defensive normalization — the app always returns these keys.
  const toolCalls = Array.isArray(result.tool_calls) ? result.tool_calls : [];
  const sessionStateUpdates = Array.isArray(result.session_state_updates)
    ? result.session_state_updates
    : [];
  // Merge session_state (top-level final state set by /chat) + updates.
  const mergedSession = {
    ...(result.session_state || {}),
    ...sessionStateUpdates.reduce((acc, u) => ({ ...acc, ...u }), {}),
  };

  // Hallucination check at provider level — flagged in metadata so tests
  // can assert "no hallucinated tool" cheaply.
  const hallucinated = toolCalls
    .map((tc) => tc?.name)
    .filter((n) => n && !ALLOWED_TOOLS.has(n));

  return {
    output: result.content || "",
    // `prompt` is consumed by model-graded assertions (e.g. closedqa) as the
    // "input" the grader compares against the criteria. Set it to the user
    // message so the judge sees what the user asked.
    prompt: message,
    // promptfoo surfaces `providerResponse` to assertions; we also stash
    // the full payload under `metadata` so transforms/asserts can read it.
    metadata: {
      chatResult: result,
      toolCalls,
      sessionState: mergedSession,
      nToolCalls: toolCalls.length,
      hallucinated,
      images: result.images || [],
      audio: result.audio || [],
      metrics: result.metrics || {},
      userId,
      phase: "test",
    },
  };
}