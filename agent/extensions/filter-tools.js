/**
 * Filter-tools — pi extension.
 *
 * Problem: Tool-RAG (agent/tool_rag.py) selects a handful of relevant tools
 * per turn and injects their names/descriptions into the user message text,
 * but pi still assembles the provider payload with ALL ~40 registered tool
 * schemas (name + description + full JSON-schema parameters) every turn.
 * The LLM therefore receives irrelevant tool schemas and can call tools that
 * were not RAG-selected.
 *
 * Fix: build_prompt / build_onboarding_prompt (agent/pi_rpc.py) emit an
 * `<active-tools>name1,name2,...</active-tools>` marker in the user message
 * text. This extension hooks before_provider_request, reads the marker from
 * the LAST user-text message, filters payload.tools down to that allowlist,
 * and strips the marker from the message text so the LLM never sees it.
 *
 * Fail-open: no marker / empty allowlist → tools left untouched.
 *
 * Historical turns carry no marker: strip-history.js already reduces old
 * user messages to the inner <user-message>...</user-message> content, and
 * the <active-tools> marker lives outside that tag, so only the current turn
 * drives filtering — each turn filters independently based on its own RAG
 * results.
 *
 * Gated by PI_FILTER_TOOLS (default: on). Set PI_FILTER_TOOLS=0 to disable.
 * Works for Google (contents[] + tools/config.tools/functionDeclarations),
 * OpenAI (messages[] + tools[].function.name) and Anthropic (messages[] +
 * tools[].name).
 */
const FILTER_ENABLED = !["0", "false", "no"].includes(
  (process.env.PI_FILTER_TOOLS || "1").toLowerCase(),
);
const MARKER_RE = /<active-tools>\s*([^\n]*?)\s*<\/active-tools>/;

export default function (pi) {
  if (!FILTER_ENABLED) return;

  pi.on("before_provider_request", (event) => {
    try {
      const payload = event?.payload;
      if (!payload || typeof payload !== "object") return;

      // Google: payload.contents[] with { role, parts[] }
      if (Array.isArray(payload.contents)) {
        filterGoogle(payload);
        return;
      }

      // OpenAI / Anthropic: payload.messages[] with { role, content }
      if (Array.isArray(payload.messages)) {
        filterOpenAI(payload);
        return;
      }
    } catch (e) {
      console.error(`[filter-tools] failed: ${e?.message || e}`);
    }
  });
}

// ── Google shape ─────────────────────────────────────────────────────────

function filterGoogle(payload) {
  const { allowlist, lastIdx } = scanUserTextGoogle(payload.contents);
  if (allowlist === null) return; // no marker → fail-open
  if (allowlist.size === 0) return; // empty → fail-open

  // Tools live at top-level `tools` OR nested under `config.tools`.
  // Each entry is a container with `functionDeclarations[]`.
  const containers = [];
  if (Array.isArray(payload.tools)) containers.push(payload.tools);
  if (payload.config && Array.isArray(payload.config.tools)) {
    containers.push(payload.config.tools);
  }

  let kept = 0;
  let total = 0;
  for (const arr of containers) {
    for (const container of arr) {
      if (!container || !Array.isArray(container.functionDeclarations)) continue;
      total += container.functionDeclarations.length;
      container.functionDeclarations = container.functionDeclarations.filter(
        (fd) => {
          if (!fd || typeof fd.name !== "string") return true; // keep unknown shapes
          return allowlist.has(fd.name);
        },
      );
      kept += container.functionDeclarations.length;
    }
  }

  // Strip the marker from the last user-text message so the LLM never sees it.
  if (lastIdx >= 0) {
    const text = payload.contents[lastIdx].parts[0].text;
    if (typeof text === "string") {
      payload.contents[lastIdx].parts[0].text = text.replace(MARKER_RE, "").trim();
    }
  }

  console.error(
    `[filter-tools] google  kept=${kept}/${total}  active=${[...allowlist].join(",")}`,
  );
}

// ── OpenAI / Anthropic shape ─────────────────────────────────────────────

function filterOpenAI(payload) {
  const { allowlist, lastIdx } = scanUserTextOpenAI(payload.messages);
  if (allowlist === null) return;
  if (allowlist.size === 0) return;

  if (!Array.isArray(payload.tools)) return;

  let kept = 0;
  let total = payload.tools.length;
  payload.tools = payload.tools.filter((t) => {
    // OpenAI: { function: { name } } — Anthropic: { name }
    const name = t?.function?.name || t?.name;
    if (typeof name !== "string") return true; // keep unknown shapes
    return allowlist.has(name);
  });
  kept = payload.tools.length;

  // Strip the marker from the last user-text message.
  if (lastIdx >= 0) {
    const m = payload.messages[lastIdx];
    if (typeof m.content === "string") {
      m.content = m.content.replace(MARKER_RE, "").trim();
    } else if (Array.isArray(m.content)) {
      const first = m.content[0];
      if (first && typeof first === "object" && typeof first.text === "string") {
        first.text = first.text.replace(MARKER_RE, "").trim();
      }
    }
  }

  console.error(
    `[filter-tools] openai  kept=${kept}/${total}  active=${[...allowlist].join(",")}`,
  );
}

// ── Marker scanning ──────────────────────────────────────────────────────

/**
 * Walk user-text messages, collect those carrying the <active-tools> marker,
 * and return the allowlist derived from the LAST one (current turn) plus the
 * index of that message. Returns { allowlist: null } when no marker is found
 * (fail-open), or { allowlist: Set, lastIdx } otherwise.
 *
 * Historical user turns won't carry the marker (strip-history.js reduced them
 * to inner <user-message> content), so in practice only the last user message
 * has it — but we scan all to be robust.
 */
function scanUserTextGoogle(contents) {
  let lastMatch = null;
  let lastIdx = -1;
  for (let i = 0; i < contents.length; i++) {
    const c = contents[i];
    if (c?.role !== "user") continue;
    const parts = c.parts;
    if (!Array.isArray(parts) || !parts.length) continue;
    const first = parts[0];
    if (!first || typeof first !== "object" || typeof first.text !== "string") continue;
    const m = MARKER_RE.exec(first.text);
    if (m) {
      lastMatch = m;
      lastIdx = i;
    }
  }
  if (lastMatch === null) return { allowlist: null, lastIdx: -1 };
  return { allowlist: parseNames(lastMatch[1]), lastIdx };
}

function scanUserTextOpenAI(messages) {
  let lastMatch = null;
  let lastIdx = -1;
  for (let i = 0; i < messages.length; i++) {
    const m = messages[i];
    if (m?.role !== "user") continue;
    const content = m.content;
    let text = null;
    if (typeof content === "string") text = content;
    else if (Array.isArray(content)) {
      const first = content[0];
      if (first && typeof first === "object" && typeof first.text === "string") {
        text = first.text;
      }
    }
    if (typeof text !== "string") continue;
    const match = MARKER_RE.exec(text);
    if (match) {
      lastMatch = match;
      lastIdx = i;
    }
  }
  if (lastMatch === null) return { allowlist: null, lastIdx: -1 };
  return { allowlist: parseNames(lastMatch[1]), lastIdx };
}

/**
 * Parse the comma-separated tool-name list inside <active-tools> into a Set.
 * Empty/whitespace-only → empty Set (caller treats as fail-open).
 */
function parseNames(raw) {
  if (!raw) return new Set();
  return new Set(
    raw
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean),
  );
}