// promptfoo runner — assembles the test suite and calls promptfoo.evaluate().
//
// Prereqs:
//   1. The Pasto Legal FastAPI app must be running on CHAT_URL
//      (default http://localhost:3000). See README.md.
//   2. GOOGLE_API_KEY must be set so the pi subprocess can call Gemini.
//   3. npm install (installs promptfoo + dotenv).
//
// Run:
//   npm test
//
// This file uses the promptfoo Node API per:
//   https://www.promptfoo.dev/docs/usage/node/
//
// We pass:
//   - prompts: a single function prompt that echoes vars.message. The real
//     prompt assembly happens server-side by /chat (system prompt from
//     agent/AGENTS.md + RAG-selected tools + session-state XML). promptfoo
//     is therefore evaluating the agent as a black box via /chat.
//   - providers: our custom chat-provider.mjs (a ProviderFunction).
//   - tests: every case from cases/*.mjs.
//   - Optional LLM-as-judge grader using JUDGE_MODEL (google:gemini-2.5-flash
//     by default; set JUDGE_MODEL="" to disable).

import "dotenv/config";
import promptfoo from "promptfoo";

import chatProvider from "./providers/chat-provider.mjs";
import { routingCases } from "./cases/routing.mjs";
import { feedbackCases } from "./cases/feedback.mjs";

const judgeModel = process.env.JUDGE_MODEL || "google:gemini-2.5-flash";
const useJudge = Boolean(judgeModel);

// A judge assertion appended to a small subset of cases where tone matters.
// Uses promptfoo's built-in model-graded-closedqa assertion type.
function judgeAssert(rubric) {
  return {
    type: "model-graded-closedqa",
    value: rubric,
    ...(useJudge ? { provider: judgeModel } : {}),
  };
}

// Pick a few representative cases to LLM-judge for tone/quality. Keeping this
// small because the judge calls Gemini again (extra tokens / latency).
// model-graded-closedqa sends (input=prompt, criteria=value, output=agent
// reply) to a Y/N grader. We set `value` to the criteria and rely on the
// provider response's `prompt` (the user message) as `input`.
const toneRubric = `O texto abaixo é a resposta do assistente "Pasto Legal" (em português brasileiro) para um pecuarista.
Avalie se a resposta atende a TODOS estes critérios:
1. Tom acolhedor, simpático, simples e respeitoso.
2. Clareza: direto ao ponto, sem jargão técnico de software.
3. Nunca se apresenta como IA/robô/chatbot/modelo de linguagem.
4. Usa formatação WhatsApp (*negrito* com asteriscos, sem markdown).
Responda Y se todos os critérios forem atendidos, ou N caso contrário, seguido de uma breve justificativa em português.`;

function withToneJudge(test) {
  if (!useJudge) return test;
  return {
    ...test,
    assert: [...(test.assert || []), judgeAssert(toneRubric)],
  };
}

const allTests = [
  ...routingCases.map(withToneJudge),
  ...feedbackCases.map(withToneJudge),
];

// The prompt is a no-op renderer — we just forward vars.message to the
// provider. The provider builds the /chat request body from context.vars.
// The prompt function receives { vars, provider } and returns the rendered
// prompt string. This rendered prompt is also what model-graded assertions
// receive as `input` (e.g. for model-graded-closedqa).
const promptFn = (ctx) => ctx.vars?.message || "";

const suite = {
  prompts: [promptFn],
  providers: [chatProvider],
  tests: allTests,
  writeLatestResults: true,
  sharing: false,
};

const options = {
  maxConcurrency: parseInt(process.env.MAX_CONCURRENCY || "1", 10),
};

console.log(`[promptfoo] ${allTests.length} tests | judge=${useJudge ? judgeModel : "off"} | chat=${process.env.CHAT_URL || "http://localhost:3000"}`);

async function main() {
  const evalRecord = await promptfoo.evaluate(suite, options);
  const results = await evalRecord.toEvaluateSummary();

  // Print a compact summary table.
  const { stats, results: rows } = results;
  let failures = 0;
  console.log("\n── promptfoo results ──────────────────────────────────────");
  for (const r of rows || []) {
    const ok = r.success;
    if (!ok) failures++;
    const name = r.test?.description || r.vars?.message || r.prompt?.label || "(unnamed)";
    const flag = ok ? "PASS" : "FAIL";
    console.log(`${flag}  ${name}`);
    if (!ok && r.error) console.log(`        error: ${r.error}`);
    if (!ok && Array.isArray(r.assertionResults)) {
      for (const a of r.assertionResults) {
        if (!a.pass) {
          const reason = (a.reason || "").replace(/\s+/g, " ").slice(0, 200);
          console.log(`        ✗ ${a.assertion?.type || "?"}: ${reason}`);
        }
      }
    }
  }
  console.log("\n── stats ─────────────────────────────────────────────────");
  console.log(JSON.stringify(stats, null, 2));

  return failures;
}

main()
  .then((failures) => process.exit(failures === 0 ? 0 : 1))
  .catch((e) => {
    console.error("[promptfoo] evaluate failed:", e);
    process.exit(2);
  });