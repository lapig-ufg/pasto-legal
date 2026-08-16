/**
 * Pasto Legal custom tools — OpenClaw plugin.
 *
 * Ported from agent/extensions/pasto-legal-tools.js (the `pi` variant). Same
 * contract: every tool only calls the Python backend via HTTP
 * (fastapi_app:3000/tool) and forwards the result back to the model — no
 * domain logic lives here. See agent/docs/OPENCLAW_NOTES.md section 4/7 for the
 * plugin SDK shape this is built against (definePluginEntry + registerTool).
 *
 * Parameters are plain JSON Schema objects, not TypeBox: a locally installed
 * `openclaw` CLI (2026.7.1-2) fails to load a plugin that imports "typebox"
 * — that package isn't bundled/resolvable for external plugins (confirmed
 * via `openclaw doctor`: "Cannot find module 'typebox'"). JSON Schema is
 * accepted directly and needs no extra dependency.
 */

import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";

const TOOL_BACKEND = process.env.TOOL_BACKEND_URL || "http://localhost:3000";

// ── tiny JSON Schema helpers (replace the TypeBox builders from the pi variant) ──
const str = (description) => ({ type: "string", description });
const num = (description) => ({ type: "number", description });
const int = (description) => ({ type: "integer", description });
const arrOf = (items, description) => ({ type: "array", items, description });
function obj(properties, required) {
  return {
    type: "object",
    properties,
    required: required ?? Object.keys(properties),
    additionalProperties: false,
  };
}

async function callTool(tool, args = {}) {
  const url = `${TOOL_BACKEND}/tool`;
  console.error(`[tools] → POST ${url}  tool=${tool}  args=${JSON.stringify(args).slice(0, 200)}`);
  try {
    const resp = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tool, args }),
      signal: AbortSignal.timeout(120_000),
    });
    const result = await resp.json();
    console.error(`[tools] ← ${tool}  ok=${!result.error}  keys=${Object.keys(result).join(",")}`);
    return result;
  } catch (err) {
    console.error(`[tools] ← ${tool}  FAILED: ${err.message}`);
    return { error: err.message };
  }
}

function makeResult(result) {
  const content = [{ type: "text", text: result.message || "Pronto." }];
  if (result.images && result.images.length > 0) {
    for (const img of result.images) {
      content.push({ type: "image", data: img, mimeType: "image/png" });
    }
  }
  return {
    content,
    details: {
      imagePaths: result.images || [],
      audioPath: result.audio_path,
      sessionState: result.session_state,
    },
  };
}

function errorResult(result) {
  return { content: [{ type: "text", text: `Erro: ${result.error}` }], details: {} };
}

export default definePluginEntry({
  id: "pasto-legal-tools",
  name: "Pasto Legal Tools",
  register(api) {
    // ── Property registration ────────────────────────────────────────────

    api.registerTool({
      name: "register_property_by_car",
      label: "Register Property by CAR",
      description: "Registra uma propriedade rural pelo código CAR/SICAR. Use quando o usuário fornecer um código CAR.",
      parameters: obj({
        car_codes: arrOf(str(), "Lista de códigos CAR (ex: ['GO-1234567-...'])"),
        user_id: str("User ID from session context"),
      }),
      async execute(_toolCallId, params) {
        const result = await callTool("property", { action: "register_by_car", car_codes: params.car_codes, user_id: params.user_id });
        if (result.error) return errorResult(result);
        return {
          content: [{ type: "text", text: result.message }],
          details: { imagePaths: result.images || [], sessionState: result.session_state },
        };
      },
    }, { optional: true });

    api.registerTool({
      name: "register_property_by_coords",
      label: "Register Property by Coordinates",
      description: "Registra uma propriedade rural por coordenadas geográficas (latitude, longitude).",
      parameters: obj({
        latitude: num("Latitude em graus decimais"),
        longitude: num("Longitude em graus decimais"),
        user_id: str("User ID from session context"),
      }),
      async execute(_toolCallId, params) {
        const result = await callTool("property", { action: "register_by_coords", latitude: params.latitude, longitude: params.longitude, user_id: params.user_id });
        if (result.error) return errorResult(result);
        return {
          content: [{ type: "text", text: result.message }],
          details: { imagePaths: result.images || [], sessionState: result.session_state },
        };
      },
    }, { optional: true });

    api.registerTool({
      name: "register_property_by_url",
      label: "Register Property by URL",
      description: "Registra uma propriedade rural a partir de um link de compartilhamento do Google Maps.",
      parameters: obj({
        url: str("URL de compartilhamento do Google Maps"),
        user_id: str("User ID from session context"),
      }),
      async execute(_toolCallId, params) {
        const result = await callTool("property", { action: "register_by_url", url: params.url, user_id: params.user_id });
        if (result.error) return errorResult(result);
        return {
          content: [{ type: "text", text: result.message }],
          details: { imagePaths: result.images || [], sessionState: result.session_state },
        };
      },
    }, { optional: true });

    api.registerTool({
      name: "confirm_property_selection",
      label: "Confirm Property Selection",
      description: "Confirma a propriedade selecionada quando há apenas uma opção.",
      parameters: obj({
        user_id: str("User ID from session context"),
      }),
      async execute(_toolCallId, params) {
        const result = await callTool("property", { action: "confirm_selection", user_id: params.user_id });
        if (result.error) return errorResult(result);
        return makeResult(result);
      },
    }, { optional: true });

    api.registerTool({
      name: "select_property_from_list",
      label: "Select Property from List",
      description: "Seleciona uma propriedade de uma lista de múltiplos resultados.",
      parameters: obj({
        selection: int("Número da opção escolhida (1, 2, 3...)"),
        user_id: str("User ID from session context"),
      }),
      async execute(_toolCallId, params) {
        const result = await callTool("property", { action: "select_from_list", selection: params.selection, user_id: params.user_id });
        if (result.error) return errorResult(result);
        return makeResult(result);
      },
    }, { optional: true });

    api.registerTool({
      name: "complete_property_registration",
      label: "Complete Property Registration",
      description: "Conclui o cadastro da propriedade com o nome escolhido pelo usuário.",
      parameters: obj({
        name: str("Nome da propriedade (ex: Fazenda Primavera)"),
        user_id: str("User ID from session context"),
      }),
      async execute(_toolCallId, params) {
        const result = await callTool("property", { action: "complete_registration", name: params.name, user_id: params.user_id });
        if (result.error) return errorResult(result);
        return makeResult(result);
      },
    }, { optional: true });

    api.registerTool({
      name: "cancel_property_registration",
      label: "Cancel Property Registration",
      description: "Cancela o processo de cadastro de propriedade em andamento.",
      parameters: obj({
        user_id: str("User ID from session context"),
      }),
      async execute(_toolCallId, params) {
        const result = await callTool("property", { action: "cancel_registration", user_id: params.user_id });
        if (result.error) return errorResult(result);
        return makeResult(result);
      },
    }, { optional: true });

    api.registerTool({
      name: "remove_property",
      label: "Remove Property",
      description: "Remove uma propriedade registrada do sistema.",
      parameters: obj({
        car_code: str("Código CAR da propriedade a remover"),
        user_id: str("User ID from session context"),
      }),
      async execute(_toolCallId, params) {
        const result = await callTool("property", { action: "remove", car_code: params.car_code, user_id: params.user_id });
        if (result.error) return errorResult(result);
        return makeResult(result);
      },
    }, { optional: true });

    api.registerTool({
      name: "remove_all_properties",
      label: "Remove All Properties",
      description: "Remove todas as propriedades registradas do sistema.",
      parameters: obj({
        user_id: str("User ID from session context"),
      }),
      async execute(_toolCallId, params) {
        const result = await callTool("property", { action: "remove_all", user_id: params.user_id });
        if (result.error) return errorResult(result);
        return makeResult(result);
      },
    }, { optional: true });

    api.registerTool({
      name: "set_property_name",
      label: "Set Property Name",
      description: "Atualiza o nome de uma propriedade já registrada.",
      parameters: obj({
        car_codes: arrOf(str(), "Lista de códigos CAR da propriedade"),
        name: str("Novo nome da propriedade"),
        user_id: str("User ID from session context"),
      }),
      async execute(_toolCallId, params) {
        const result = await callTool("property", { action: "set_name", car_codes: params.car_codes, name: params.name, user_id: params.user_id });
        if (result.error) return errorResult(result);
        return makeResult(result);
      },
    }, { optional: true });

    // ── Pasture analysis ────────────────────────────────────────────────

    api.registerTool({
      name: "get_pasture_stats",
      label: "Pasture Statistics",
      description: "Recupera estatísticas de biomassa, vigor vegetativo, idade da pastagem e classificação de uso do solo.",
      parameters: obj({
        car_codes: arrOf(str(), "Lista de códigos CAR da propriedade"),
        year: int("Ano de referência (default: 2026)"),
        month: int("Mês de referência (default: 5)"),
      }, ["car_codes"]),
      async execute(_toolCallId, params) {
        const result = await callTool("gee", { action: "pasture_stats", car_codes: params.car_codes, year: params.year || 2026, month: params.month || 5 });
        if (result.error) return errorResult(result);
        return makeResult({ message: result.stats_text || JSON.stringify(result.stats) });
      },
    }, { optional: true });

    api.registerTool({
      name: "get_topographic_stats",
      label: "Topographic Statistics",
      description: "Recupera estatísticas de topografia (altimetria e declividade) de uma propriedade.",
      parameters: obj({
        car_codes: arrOf(str(), "Lista de códigos CAR da propriedade"),
      }),
      async execute(_toolCallId, params) {
        const result = await callTool("gee", { action: "topographic_stats", car_codes: params.car_codes });
        if (result.error) return errorResult(result);
        return makeResult({ message: result.stats_text || JSON.stringify(result.stats) });
      },
    }, { optional: true });

    api.registerTool({
      name: "generate_property_image",
      label: "Property Satellite Image",
      description: "Gera uma imagem de satélite em alta resolução (RGB) da propriedade rural com delimitação geográfica.",
      parameters: obj({
        car_codes: arrOf(str(), "Lista de códigos CAR da propriedade"),
      }),
      async execute(_toolCallId, params) {
        const result = await callTool("gee", { action: "property_image", car_codes: params.car_codes });
        if (result.error) return errorResult(result);
        return makeResult(result);
      },
    }, { optional: true });

    api.registerTool({
      name: "generate_biomass_image",
      label: "Biomass Map",
      description: "Gera um mapa temático da biomassa (matéria seca) sobre os limites da propriedade.",
      parameters: obj({
        car_codes: arrOf(str(), "Lista de códigos CAR da propriedade"),
      }),
      async execute(_toolCallId, params) {
        const result = await callTool("gee", { action: "biomass_image", car_codes: params.car_codes });
        if (result.error) return errorResult(result);
        return makeResult(result);
      },
    }, { optional: true });

    api.registerTool({
      name: "generate_soil_texture_image",
      label: "Soil Texture Map",
      description: "Gera um mapa temático da textura do solo sobre os limites da propriedade (0-30cm).",
      parameters: obj({
        car_codes: arrOf(str(), "Lista de códigos CAR da propriedade"),
      }),
      async execute(_toolCallId, params) {
        const result = await callTool("gee", { action: "soil_texture_image", car_codes: params.car_codes });
        if (result.error) return errorResult(result);
        return makeResult(result);
      },
    }, { optional: true });

    api.registerTool({
      name: "generate_pasture_classification_image",
      label: "Pasture Classification Map",
      description: "Gera o mapa de classificação de pastagem (pasto x não-pasto) calculado sob demanda.",
      parameters: obj({
        car_codes: arrOf(str(), "Lista de códigos CAR da propriedade"),
      }),
      async execute(_toolCallId, params) {
        const result = await callTool("gee", { action: "pasture_classification_image", car_codes: params.car_codes });
        if (result.error) return errorResult(result);
        return makeResult(result);
      },
    }, { optional: true });

    // ── TTS ──────────────────────────────────────────────────────────────

    api.registerTool({
      name: "generate_speech",
      label: "Generate Speech",
      description: "Gera áudio falado a partir de um texto. Use APENAS quando o usuário solicitar explicitamente uma resposta em áudio.",
      parameters: obj({
        text: str("Texto completo para converter em fala"),
        user_id: str("User ID from session context"),
      }),
      async execute(_toolCallId, params) {
        const result = await callTool("tts", { text: params.text, user_id: params.user_id });
        if (result.error) return errorResult(result);
        return makeResult(result);
      },
    }, { optional: true });

    // ── Onboarding ───────────────────────────────────────────────────────

    api.registerTool({
      name: "accept_terms_and_conditions",
      label: "Accept Terms",
      description: "Registra a aceitação formal dos Termos de Uso do Pasto Legal.",
      parameters: obj({
        user_id: str("User ID from session context"),
      }),
      async execute(_toolCallId, params) {
        const result = await callTool("onboarding", { action: "accept_terms", user_id: params.user_id });
        if (result.error) return errorResult(result);
        return makeResult(result);
      },
    }, { optional: true });

    // ── Version / changelog ─────────────────────────────────────────────

    api.registerTool({
      name: "consult_update_notes",
      label: "Update Notes",
      description: "Lê e retorna as notas de atualização (patch notes) do sistema Pasto Legal.",
      parameters: obj({}, []),
      async execute() {
        const result = await callTool("version", { action: "update_notes" });
        if (result.error) return errorResult(result);
        return makeResult({ message: result.notes });
      },
    }, { optional: true });

    // ── Feedback (frustration remediation loop) ─────────────────────────

    api.registerTool({
      name: "request_feedback",
      label: "Request Feedback",
      description: "Ativa o modo de aguardo de feedback do usuário. Chame APENAS após entregar uma resposta reformulada (remediação) por frustração do usuário, junto da pergunta 'Ficou melhor? Responda SIM ou NÃO'.",
      parameters: obj({
        user_id: str("User ID from session context"),
      }),
      async execute(_toolCallId, params) {
        const result = await callTool("feedback", { action: "request_feedback", user_id: params.user_id });
        if (result.error) return errorResult(result);
        return makeResult(result);
      },
    }, { optional: true });

    api.registerTool({
      name: "save_feedback",
      label: "Save Feedback",
      description: "Registra o feedback do usuário (positivo ou negativo) sobre a resposta reformulada e encerra o modo de feedback. Chame ao classificar a resposta do usuário à pergunta 'Ficou melhor?'.",
      parameters: obj({
        user_id: str("User ID from session context"),
        verdict: str("Avaliação do usuário: 'positive' se a resposta melhorou, 'negative' se piorou ou não resolveu"),
        user_message: str("Mensagem do usuário que respondeu à pergunta de feedback"),
        assistant_response: str("A resposta reformulada que foi avaliada pelo usuário"),
        reason: str("Justificativa do veredito (opcional)"),
      }, ["user_id", "verdict", "user_message", "assistant_response"]),
      async execute(_toolCallId, params) {
        const result = await callTool("feedback", {
          action: "save_feedback",
          user_id: params.user_id,
          verdict: params.verdict,
          user_message: params.user_message,
          assistant_response: params.assistant_response,
          reason: params.reason || "",
        });
        if (result.error) return errorResult(result);
        return makeResult(result);
      },
    }, { optional: true });
  },
});
