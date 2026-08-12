/**
 * Prompt dumper — pi extension.
 *
 * Subscribes to `before_provider_request` and writes the EXACT payload pi
 * sends to the LLM provider on every turn. This is the only source of
 * truth for the full prompt (system prompt + tool schemas + history),
 * because pi assembles all of that internally before the provider call.
 *
 * Output (per user, gated by PI_DUMP_PROMPT=1):
 *   <PI_DUMP_DIR>/last_prompt.json  — raw provider payload
 *   <PI_DUMP_DIR>/last_prompt.md    — readable transcript
 *
 * PI_DUMP_DIR and PI_DUMP_USER_ID are injected per-process by the Python
 * PiRpcClient (agent/pi_rpc.py) so each user's pi subprocess writes to its
 * own session dir with no cross-user contention.
 */
import { writeFileSync, mkdirSync } from "node:fs";
import { join } from "node:path";

const DUMP_ENABLED = ["1", "true", "yes"].includes(
  (process.env.PI_DUMP_PROMPT || "").toLowerCase(),
);
const DUMP_DIR = process.env.PI_DUMP_DIR || "";
const DUMP_USER_ID = process.env.PI_DUMP_USER_ID || "";

export default function (pi) {
  if (!DUMP_ENABLED || !DUMP_DIR) return;

  pi.on("before_provider_request", (event) => {
    try {
      mkdirSync(DUMP_DIR, { recursive: true });
      const payload = event.payload;

      writeFileSync(
        join(DUMP_DIR, "last_prompt.json"),
        JSON.stringify(payload, null, 2),
        "utf8",
      );
      writeFileSync(
        join(DUMP_DIR, "last_prompt.md"),
        renderMarkdown(payload, DUMP_USER_ID),
        "utf8",
      );
    } catch (e) {
      console.error(`[prompt-dumper] failed: ${e?.message || e}`);
    }
  });
}

// ── Markdown renderer ────────────────────────────────────────────────────

function renderMarkdown(payload, userId) {
  const lines = [];
  const provider = detectProvider(payload);

  lines.push(`# Full prompt sent to LLM`);
  lines.push("");
  lines.push(`- user: \`${userId || "?"}\``);
  lines.push(`- provider: \`${provider}\``);
  if (payload?.model) lines.push(`- model: \`${payload.model}\``);
  lines.push("");

  // ── System prompt ──────────────────────────────────────────────────────
  const system = extractSystem(payload);
  if (system) {
    lines.push("## System");
    lines.push("");
    lines.push(system);
    lines.push("");
  }

  // ── Messages ───────────────────────────────────────────────────────────
  const messages = extractMessages(payload);
  if (messages.length) {
    lines.push("## Messages");
    lines.push("");
    messages.forEach((m, i) => {
      const role = (m.role || "?").toUpperCase();
      lines.push(`### [${role}] #${i + 1}`);
      lines.push("");
      renderContent(m.content, lines);
      lines.push("");
    });
  }

  // ── Tools ─────────────────────────────────────────────────────────────
  const tools = extractTools(payload);
  if (tools.length) {
    lines.push("## Tools");
    lines.push("");
    lines.push(`Total: ${tools.length} tool definitions`);
    lines.push("");
    tools.forEach((t, i) => {
      const name =
        t.name || t.function?.name || t.functionDeclarations?.[0]?.name || `tool_${i}`;
      lines.push(`- \`${name}\``);
    });
    lines.push("");
    lines.push("### Full tool schemas");
    lines.push("");
    lines.push("```json");
    lines.push(JSON.stringify(tools, null, 2));
    lines.push("```");
    lines.push("");
  }

  return lines.join("\n").trim() + "\n";
}

// ── Provider shape detection ─────────────────────────────────────────────

function detectProvider(payload) {
  if (!payload || typeof payload !== "object") return "unknown";
  // Google: top-level `contents` (systemInstruction/tools may be under `config`)
  if (Array.isArray(payload.contents)) return "google";
  if (Array.isArray(payload.messages) && payload.system !== undefined) {
    return "anthropic";
  }
  if (Array.isArray(payload.messages)) return "openai";
  return "unknown";
}

function extractSystem(payload) {
  // Google: systemInstruction at top level OR nested under config
  const si = payload?.systemInstruction ?? payload?.config?.systemInstruction;
  if (si) {
    if (typeof si === "string") return si;
    if (Array.isArray(si.parts)) {
      return si.parts.map((p) => p?.text || "").join("\n");
    }
  }
  // Anthropic: system (string or array of content blocks)
  if (typeof payload?.system === "string") return payload.system;
  if (Array.isArray(payload?.system)) {
    return payload.system
      .map((b) => (b?.text ?? JSON.stringify(b, null, 2)))
      .join("\n");
  }
  // OpenAI: first message with role === "system"
  if (Array.isArray(payload?.messages)) {
    const sys = payload.messages.find((m) => m?.role === "system");
    if (sys) {
      if (typeof sys.content === "string") return sys.content;
      if (Array.isArray(sys.content)) {
        return sys.content
          .map((b) => (b?.text ?? JSON.stringify(b, null, 2)))
          .join("\n");
      }
    }
  }
  return "";
}

function extractMessages(payload) {
  // Google: contents[] each with role + parts[]
  if (Array.isArray(payload?.contents)) {
    return payload.contents.map((c) => ({
      role: c.role === "model" ? "assistant" : c.role,
      content: c.parts,
    }));
  }
  // Anthropic / OpenAI: messages[]
  if (Array.isArray(payload?.messages)) {
    return payload.messages
      .filter((m) => m?.role !== "system") // system handled separately
      .map((m) => ({
        role: m.role,
        content: m.content,
      }));
  }
  return [];
}

function extractTools(payload) {
  // Google: tools at top level OR nested under config; each has functionDeclarations[]
  // Anthropic / OpenAI: tools[] at top level (each has .name or .function.name)
  const tools = payload?.tools ?? payload?.config?.tools;
  if (!Array.isArray(tools)) return [];
  const out = [];
  for (const t of tools) {
    if (Array.isArray(t?.functionDeclarations)) {
      out.push(...t.functionDeclarations);
    } else {
      out.push(t?.function || t);
    }
  }
  return out;
}

// ── Content rendering (per provider shape) ──────────────────────────────

function renderContent(content, lines) {
  if (content == null) {
    lines.push("_(no content)_");
    return;
  }
  if (typeof content === "string") {
    lines.push(content);
    return;
  }
  if (!Array.isArray(content)) {
    lines.push("```json");
    lines.push(JSON.stringify(content, null, 2));
    lines.push("```");
    return;
  }

  for (const block of content) {
    renderBlock(block, lines);
  }
}

function renderBlock(block, lines) {
  if (block == null) return;

  // Google parts: { text } / { functionCall } / { functionResponse } / { inlineData }
  if (typeof block.text === "string") {
    lines.push(block.text);
    lines.push("");
    return;
  }
  if (block.functionCall) {
    const fc = block.functionCall;
    const name = fc?.name || "?";
    const args = JSON.stringify(fc?.args ?? {}, null, 2);
    lines.push(`**tool-call**: \`${name}\``);
    lines.push("```json");
    lines.push(truncate(args, 800));
    lines.push("```");
    lines.push("");
    return;
  }
  if (block.functionResponse) {
    const fr = block.functionResponse;
    const name = fr?.name || "?";
    const resp = JSON.stringify(fr?.response ?? {}, null, 2);
    lines.push(`**tool-result**: \`${name}\``);
    lines.push("```json");
    lines.push(truncate(resp, 500));
    lines.push("```");
    lines.push("");
    return;
  }
  if (block.inlineData) {
    const mime = block.inlineData.mimeType || "image/?";
    const kb = Math.max(
      1,
      Math.round((block.inlineData.data?.length || 0) * 3 / 4 / 1024),
    );
    lines.push(`[image: ${mime}, ~${kb}kb]`);
    lines.push("");
    return;
  }

  // Anthropic / OpenAI blocks: { type, text } / { type, thinking, thinking } /
  // { type, name, input } / { type, tool_use_id, content } / { type, source }
  const t = block.type;
  if (t === "text" && typeof block.text === "string") {
    lines.push(block.text);
    lines.push("");
    return;
  }
  if (t === "thinking") {
    lines.push("<details><summary>thinking</summary>");
    lines.push("");
    lines.push(block.thinking || "");
    lines.push("");
    lines.push("</details>");
    lines.push("");
    return;
  }
  if (t === "tool_use") {
    lines.push(`**tool-call**: \`${block.name || "?"}\``);
    lines.push("```json");
    lines.push(truncate(JSON.stringify(block.input ?? {}, null, 2), 800));
    lines.push("```");
    lines.push("");
    return;
  }
  if (t === "tool_result") {
    lines.push(`**tool-result**: \`${block.tool_use_id || "?"}\``);
    lines.push("```json");
    lines.push(
      truncate(
        JSON.stringify(block.content ?? "", null, 2),
        500,
      ),
    );
    lines.push("```");
    lines.push("");
    return;
  }
  if (t === "image") {
    const src = block.source;
    const mime = src?.media_type || "image/?";
    lines.push(`[image: ${mime}]`);
    lines.push("");
    return;
  }

  // Unknown block — dump as JSON
  lines.push("```json");
  lines.push(truncate(JSON.stringify(block, null, 2), 500));
  lines.push("```");
  lines.push("");
}

function truncate(s, max) {
  if (s.length <= max) return s;
  return s.slice(0, max) + "…";
}