// Shared assertion helpers, written as promptfoo AssertionValueFunction
// (output, context) => { pass, score, reason }.
//
// `context.providerResponse.metadata` is set by chat-provider.mjs and carries
// the parsed /chat payload (toolCalls, sessionState, metrics, ...).
//
// `output` is the assistant text (result.content).

function meta(context) {
  return context?.providerResponse?.metadata || {};
}

// Assert the agent called a tool whose name is in `expected` (string or array).
export function calledTool(expected) {
  const want = Array.isArray(expected) ? new Set(expected) : new Set([expected]);
  return (output, context) => {
    const calls = meta(context).toolCalls || [];
    const called = new Set(calls.map((c) => c?.name).filter(Boolean));
    const hits = [...want].filter((w) => called.has(w));
    const pass = hits.length > 0;
    return {
      pass,
      score: pass ? 1 : 0,
      reason: pass
        ? `Called expected tool(s): ${hits.join(", ")}`
        : `Expected one of [${[...want].join(", ")}] but called: [${[...called].join(", ")}]`,
    };
  };
}

// Assert the agent did NOT call any tool this turn.
export function calledNoTool() {
  return (output, context) => {
    const n = meta(context).nToolCalls || 0;
    const pass = n === 0;
    return {
      pass,
      score: pass ? 1 : 0,
      reason: pass ? "No tool called" : `Expected 0 tool calls, got ${n}`,
    };
  };
}

// Assert no tool outside the canonical allowlist was invoked (no hallucination).
export function noHallucinatedTool() {
  return (output, context) => {
    const bad = meta(context).hallucinated || [];
    const pass = bad.length === 0;
    return {
      pass,
      score: pass ? 1 : 0,
      reason: pass
        ? "All called tools are in the registry"
        : `Hallucinated tools: ${bad.join(", ")}`,
    };
  };
}

// Assert a key in the (merged) session state matches a value.
// `key` may be dotted: "feedback_mode". `expected` is compared with ===.
export function sessionStateEquals(key, expected) {
  return (output, context) => {
    const s = meta(context).sessionState || {};
    const actual = s[key];
    const pass = actual === expected;
    return {
      pass,
      score: pass ? 1 : 0,
      reason: pass
        ? `session.${key} === ${JSON.stringify(expected)}`
        : `session.${key} === ${JSON.stringify(actual)} (expected ${JSON.stringify(expected)})`,
    };
  };
}

// Assert the merged session state contains `key` with any truthy value.
export function sessionStateHasKey(key) {
  return (output, context) => {
    const s = meta(context).sessionState || {};
    const pass = Boolean(s[key]);
    return {
      pass,
      score: pass ? 1 : 0,
      reason: pass ? `session.${key} present` : `session.${key} missing`,
    };
  };
}

// Light Portuguese-language check: output contains common pt-BR diacritics
// or words, and is not obviously English. This is a heuristic — pair with
// the LLM-as-judge grader for tone/quality.
export function isPortuguese() {
  return (output, context) => {
    if (!output || typeof output !== "string" || !output.trim()) {
      return { pass: false, score: 0, reason: "Empty output" };
    }
    const ptHints = /(ç|ã|õ|é|ê|á|í|ó|ú|â|ô|à)|\b(olá|oi|bom dia|boa tarde|boa noite|obrigad|por favor|tudo bem|fazenda|pasto|gado|pastagem|você|estou|posso|vamos)\b/i;
    const enHints = /\b(yes|no|hello|how are you|please|thank you|the|and|with|for)\b/i;
    const pt = ptHints.test(output);
    const en = enHints.test(output) && !pt;
    const pass = pt && !en;
    return {
      pass,
      score: pass ? 1 : 0,
      reason: pass
        ? "Output looks like Brazilian Portuguese"
        : `Output did not clearly look like pt-BR (pt=${pt}, en=${en})`,
    };
  };
}

// Assert WhatsApp-style formatting: allows *bold* but no markdown headers
// (`# `, `## `) and no double-asterisk `**bold**`.
export function whatsappFormat() {
  return (output, context) => {
    const text = output || "";
    const hasMdHeader = /(^|\n)\s{0,3}#{1,6}\s/.test(text);
    const hasMdBold = /\*\*[^*]+\*\*/.test(text);
    const hasMarkdownList = /(^|\n)\s*[-*]\s/.test(text) && /(^|\n)\s*\d+\.\s/.test(text);
    const pass = !hasMdHeader && !hasMdBold;
    return {
      pass,
      score: pass ? 1 : 0,
      reason: pass
        ? "Output uses WhatsApp-style formatting"
        : `Markdown leakage detected (header=${hasMdHeader}, **bold**=${hasMdBold})`,
    };
  };
}

// Assert the agent never identifies itself as AI/robot/bot/model.
export function doesNotSelfIdentifyAsBot() {
  const bad = /\b(rob[oô]|bot\b|chatbot|I A|intelig[êe]ncia artificial|modelo de linguagem|language model|GPT|Gemini|LLM|sou uma IA|sou um assistant)\b/i;
  return (output, context) => {
    const text = output || "";
    const m = bad.test(text);
    return {
      pass: !m,
      score: m ? 0 : 1,
      reason: m ? "Self-identified as AI/bot/model" : "No self-identification as bot",
    };
  };
}

// Assert the output contains a substring (case-insensitive).
export function containsI(substring) {
  return (output, context) => {
    const pass = (output || "").toLowerCase().includes(substring.toLowerCase());
    return {
      pass,
      score: pass ? 1 : 0,
      reason: pass
        ? `Output contains "${substring}"`
        : `Output missing "${substring}"`,
    };
  };
}

// Assert the output contains a regex pattern.
export function matchesRe(pattern, label) {
  const re = new RegExp(pattern);
  return (output, context) => {
    const pass = re.test(output || "");
    return {
      pass,
      score: pass ? 1 : 0,
      reason: pass
        ? `Output matches ${label || pattern}`
        : `Output does not match ${label || pattern}`,
    };
  };
}