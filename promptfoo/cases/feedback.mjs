// Feedback remediation tests.
//
// Two-step flow:
//   1. User shows frustration → agent apologizes, rewrites response,
//      calls `request_feedback` (session.feedback_mode = "awaiting_rating").
//   2. Next turn (with feedback_mode set), user says "sim" or "não" →
//      agent calls `save_feedback` with the right verdict.
//
// We model these as independent single-turn tests against /chat, each with
// the appropriate session_state fixture.
import {
  calledTool,
  noHallucinatedTool,
  sessionStateEquals,
  containsI,
  matchesRe,
  isPortuguese,
  doesNotSelfIdentifyAsBot,
} from "../assertions.mjs";
import { REGISTERED_USER_SESSION, AWAITING_FEEDBACK_SESSION } from "../data/session-fixtures.mjs";

export const feedbackCases = [
  {
    description: "Feedback: frustration triggers request_feedback (feedback_mode=awaiting_rating)",
    vars: {
      message: "Não gostei dessa resposta, ficou péssimo. Tenta de novo.",
      session_state: { ...REGISTERED_USER_SESSION },
    },
    assert: [
      { type: "javascript", value: isPortuguese() },
      { type: "javascript", value: doesNotSelfIdentifyAsBot() },
      { type: "javascript", value: calledTool("request_feedback") },
      { type: "javascript", value: noHallucinatedTool() },
      // request_feedback sets feedback_mode in the session delta.
      { type: "javascript", value: sessionStateEquals("feedback_mode", "awaiting_rating") },
      // Should ask the "Ficou melhor? SIM ou NÃO" question.
      { type: "javascript", value: matchesRe(/ficou melhor\??|sim ou n/i, "asks SIM/NÃO") },
    ],
  },
  {
    description: "Feedback: positive reply → save_feedback(verdict=positive)",
    vars: {
      message: "Sim, ficou melhor agora. Obrigado!",
      session_state: { ...AWAITING_FEEDBACK_SESSION },
    },
    assert: [
      { type: "javascript", value: isPortuguese() },
      { type: "javascript", value: calledTool("save_feedback") },
      { type: "javascript", value: noHallucinatedTool() },
      // Verify the verdict arg was "positive".
      {
        type: "javascript",
        value: (out, ctx) => {
          const calls = ctx?.providerResponse?.metadata?.toolCalls || [];
          const sf = calls.find((c) => c?.name === "save_feedback");
          const verdict = sf?.args?.verdict;
          const pass = verdict === "positive";
          return {
            pass,
            score: pass ? 1 : 0,
            reason: pass
              ? "save_feedback.verdict === positive"
              : `save_feedback.verdict = ${JSON.stringify(verdict)} (expected "positive")`,
          };
        },
      },
    ],
  },
  {
    description: "Feedback: negative reply → save_feedback(verdict=negative)",
    vars: {
      message: "Não, piorou. Continua errado.",
      session_state: { ...AWAITING_FEEDBACK_SESSION },
    },
    assert: [
      { type: "javascript", value: isPortuguese() },
      { type: "javascript", value: calledTool("save_feedback") },
      { type: "javascript", value: noHallucinatedTool() },
      {
        type: "javascript",
        value: (out, ctx) => {
          const calls = ctx?.providerResponse?.metadata?.toolCalls || [];
          const sf = calls.find((c) => c?.name === "save_feedback");
          const verdict = sf?.args?.verdict;
          const pass = verdict === "negative";
          return {
            pass,
            score: pass ? 1 : 0,
            reason: pass
              ? "save_feedback.verdict === negative"
              : `save_feedback.verdict = ${JSON.stringify(verdict)} (expected "negative")`,
          };
        },
      },
    ],
  },
  {
    description: "Feedback: no frustration → agent does NOT trigger request_feedback",
    vars: {
      message: "Muito obrigado pela ajuda, foi ótimo!",
      session_state: { ...REGISTERED_USER_SESSION },
    },
    assert: [
      { type: "javascript", value: isPortuguese() },
      { type: "javascript", value: noHallucinatedTool() },
      {
        type: "javascript",
        value: (out, ctx) => {
          const calls = ctx?.providerResponse?.metadata?.toolCalls || [];
          const hit = calls.some((c) => c?.name === "request_feedback");
          return {
            pass: !hit,
            score: !hit ? 1 : 0,
            reason: hit
              ? "Unexpectedly called request_feedback on gratitude"
              : "Did not call request_feedback on gratitude",
          };
        },
      },
    ],
  },
];