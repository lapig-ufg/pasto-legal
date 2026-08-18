/**
 * Strip-history — pi extension.
 *
 * Problem: build_prompt() / build_onboarding_prompt() (agent/pi_rpc.py) pack
 * system instructions, tool-RAG list, skills, <session-state> and <user-message>
 * into the *user* message text. pi stores that whole text as the user role in
 * its in-memory history and replays it on every subsequent turn, so historical
 * user turns in the provider payload carry kilobytes of stale scaffolding.
 *
 * Fix: hook before_provider_request and, for every *historical* user-text
 * message (i.e. all but the last user-text message), replace parts[0].text
 * with just the inner content of the trailing <user-message>...</user-message>
 * tag. The current (last) user turn is left untouched — its scaffolding is
 * what makes the live turn work, since RPC mode has no per-turn system
 * channel for this content.
 *
 * Gated by PI_STRIP_HISTORY (default: on). Set PI_STRIP_HISTORY=0 to disable.
 * Works for Google (contents[]), OpenAI and Anthropic (messages[]) shapes.
 */
const STRIP_ENABLED = !["0", "false", "no"].includes(
  (process.env.PI_STRIP_HISTORY || "1").toLowerCase(),
);
const TAG_RE = /<user-message>([\s\S]*?)<\/user-message>/;

export default function (pi) {
  if (!STRIP_ENABLED) return;

  pi.on("before_provider_request", (event) => {
    try {
      const payload = event?.payload;
      if (!payload || typeof payload !== "object") return;

      // Google: payload.contents[] with { role, parts[] }
      if (Array.isArray(payload.contents)) {
        stripGoogle(payload.contents);
        return;
      }

      // OpenAI / Anthropic: payload.messages[] with { role, content }
      if (Array.isArray(payload.messages)) {
        stripOpenAI(payload.messages);
        return;
      }
    } catch (e) {
      console.error(`[strip-history] failed: ${e?.message || e}`);
    }
  });
}

// ── Google shape ─────────────────────────────────────────────────────────

function stripGoogle(contents) {
  // Indices of user-text entries (role=user, first part is a text block
  // containing a <user-message> tag).
  const userTextIdx = [];
  for (let i = 0; i < contents.length; i++) {
    const c = contents[i];
    if (c?.role !== "user") continue;
    const parts = c.parts;
    if (!Array.isArray(parts) || !parts.length) continue;
    const first = parts[0];
    if (first && typeof first === "object" && typeof first.text === "string" &&
        TAG_RE.test(first.text)) {
      userTextIdx.push(i);
    }
  }
  // Keep the last one (current turn); strip the rest.
  for (let k = 0; k < userTextIdx.length - 1; k++) {
    const i = userTextIdx[k];
    const m = TAG_RE.exec(contents[i].parts[0].text);
    if (m) contents[i].parts[0].text = m[1];
  }
}

// ── OpenAI / Anthropic shape ─────────────────────────────────────────────

function stripOpenAI(messages) {
  const userIdx = [];
  for (let i = 0; i < messages.length; i++) {
    const m = messages[i];
    if (m?.role !== "user") continue;
    const content = m.content;
    if (typeof content === "string") {
      if (TAG_RE.test(content)) userIdx.push(i);
    } else if (Array.isArray(content)) {
      const first = content[0];
      if (first && typeof first === "object" && typeof first.text === "string" &&
          TAG_RE.test(first.text)) {
        userIdx.push(i);
      }
    }
  }
  for (let k = 0; k < userIdx.length - 1; k++) {
    const i = userIdx[k];
    const m = messages[i];
    if (typeof m.content === "string") {
      const match = TAG_RE.exec(m.content);
      if (match) m.content = match[1];
    } else if (Array.isArray(m.content)) {
      const match = TAG_RE.exec(m.content[0].text || "");
      if (match) m.content[0].text = match[1];
    }
  }
}