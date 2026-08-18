// Tool-routing tests: for a registered user, assert the agent selects the
// right tool (or no tool) based on the user's intent. Real Gemini model.
import {
  calledTool,
  calledNoTool,
  noHallucinatedTool,
  containsI,
  matchesRe,
  isPortuguese,
  whatsappFormat,
  doesNotSelfIdentifyAsBot,
} from "../assertions.mjs";
import { REGISTERED_USER_SESSION } from "../data/session-fixtures.mjs";

const runGee = process.env.RUN_GEE_TESTS === "1";

// Base session helper — every routing case starts as a registered user.
function registered(extra = {}) {
  return { ...REGISTERED_USER_SESSION, ...extra };
}

export const routingCases = [
  {
    description: "Routing: CAR registration intent triggers property registration",
    vars: {
      message:
        "Quero cadastrar minha fazenda pelo CAR GO-52089037-A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4E5F6A1B2",
      session_state: registered(),
    },
    assert: [
      { type: "javascript", value: isPortuguese() },
      { type: "javascript", value: noHallucinatedTool() },
      // Property flow starts: any of the register_property_by_* tools.
      {
        type: "javascript",
        value: (out, ctx) => {
          const calls = ctx?.providerResponse?.metadata?.toolCalls || [];
          const propertyTools = [
            "register_property_by_car",
            "register_property_by_coords",
            "register_property_by_url",
          ];
          const hit = calls.some((c) => propertyTools.includes(c?.name));
          return {
            pass: hit,
            score: hit ? 1 : 0,
            reason: hit
              ? `Property tool called: ${calls.map((c) => c.name).join(", ")}`
              : `No property tool called (got: ${calls.map((c) => c.name).join(", ") || "none"})`,
          };
        },
      },
    ],
  },
  {
    description: "Routing: small talk triggers no tool",
    vars: {
      message: "Oi, tudo bem por aí?",
      session_state: registered(),
    },
    assert: [
      { type: "javascript", value: isPortuguese() },
      { type: "javascript", value: whatsappFormat() },
      { type: "javascript", value: calledNoTool() },
      { type: "javascript", value: noHallucinatedTool() },
    ],
  },
  {
    description: "Routing: FAQ about data provenance triggers no tool",
    vars: {
      message: "De onde vêm os dados do Pasto Legal? Usa qual satélite?",
      session_state: registered(),
    },
    assert: [
      { type: "javascript", value: isPortuguese() },
      { type: "javascript", value: doesNotSelfIdentifyAsBot() },
      { type: "javascript", value: calledNoTool() },
      { type: "javascript", value: noHallucinatedTool() },
      // Should mention Sentinel-2 or LAPIG.
      {
        type: "javascript",
        value: (out) => {
          const ok = /sentinel|l a p i g|lapig/i.test(out || "");
          return {
            pass: ok,
            score: ok ? 1 : 0,
            reason: ok ? "Mentions Sentinel/LAPIG" : "Does not mention Sentinel/LAPIG",
          };
        },
      },
    ],
  },
  {
    description: "Routing: UA calculator question triggers ua_calculator (no GEE call)",
    vars: {
      message: "Como eu calculo a unidade animal do meu rebanho?",
      session_state: registered(),
    },
    assert: [
      { type: "javascript", value: isPortuguese() },
      { type: "javascript", value: noHallucinatedTool() },
      // ua_calculator is a skill, not a registered tool the pi extension
      // exposes — the agent should answer using the skill text without
      // invoking an external tool. So: no tool call expected.
      { type: "javascript", value: calledNoTool() },
      { type: "javascript", value: matchesRe(/UA|unidade animal|450|lota/i, "UA concept present") },
    ],
  },
  ...(runGee
    ? [
        {
          description: "Routing (GEE): satellite image request triggers generate_property_image",
          vars: {
            message: "Gere uma imagem de satélite da minha propriedade Fazenda Boa Vista",
            session_state: registered(),
          },
          assert: [
            { type: "javascript", value: isPortuguese() },
            { type: "javascript", value: noHallucinatedTool() },
            {
              type: "javascript",
              value: (out, ctx) => {
                const imgs = ctx?.providerResponse?.metadata?.images || [];
                const ok = imgs.length > 0;
                return {
                  pass: ok,
                  score: ok ? 1 : 0,
                  reason: ok ? `Got ${imgs.length} image(s)` : "No image returned",
                };
              },
            },
          ],
        },
        {
          description: "Routing (GEE): pasture stats request triggers get_pasture_stats",
          vars: {
            message: "Me dê as estatísticas de pastagem da Fazenda Boa Vista",
            session_state: registered(),
          },
          assert: [
            { type: "javascript", value: isPortuguese() },
            { type: "javascript", value: noHallucinatedTool() },
            { type: "javascript", value: calledTool("get_pasture_stats") },
          ],
        },
      ]
    : []),
];