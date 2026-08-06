/**
 * Pasto Legal custom tools — pi extension.
 *
 * Each tool calls the Python backend via HTTP (fastapi_app:3000/tool).
 * The Python backend executes the corresponding CLI script and returns results.
 *
 * Tool results carry image/audio file paths in details so the pi subprocess
 * can forward them back to the Python webhook for WhatsApp delivery.
 */

import { Type } from "typebox";

const TOOL_BACKEND = process.env.TOOL_BACKEND_URL || "http://localhost:3000";

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

export default function (pi) {
  // ── Property registration ──────────────────────────────────────────────

  pi.registerTool({
    name: "register_property_by_car",
    label: "Register Property by CAR",
    description: "Registra uma propriedade rural pelo código CAR/SICAR. Use quando o usuário fornecer um código CAR.",
    parameters: Type.Object({
      car_codes: Type.Array(Type.String(), { description: "Lista de códigos CAR (ex: ['GO-1234567-...'])" }),
      user_id: Type.String({ description: "User ID from session context" }),
    }),
    async execute(_toolCallId, params) {
      const result = await callTool("property", { action: "register_by_car", car_codes: params.car_codes, user_id: params.user_id });
      if (result.error) return errorResult(result);
      return {
        content: [{ type: "text", text: result.message }],
        details: { imagePaths: result.images || [], sessionState: result.session_state },
      };
    },
  });

  pi.registerTool({
    name: "register_property_by_coords",
    label: "Register Property by Coordinates",
    description: "Registra uma propriedade rural por coordenadas geográficas (latitude, longitude).",
    parameters: Type.Object({
      latitude: Type.Number({ description: "Latitude em graus decimais" }),
      longitude: Type.Number({ description: "Longitude em graus decimais" }),
      user_id: Type.String({ description: "User ID from session context" }),
    }),
    async execute(_toolCallId, params) {
      const result = await callTool("property", { action: "register_by_coords", latitude: params.latitude, longitude: params.longitude, user_id: params.user_id });
      if (result.error) return errorResult(result);
      return {
        content: [{ type: "text", text: result.message }],
        details: { imagePaths: result.images || [], sessionState: result.session_state },
      };
    },
  });

  pi.registerTool({
    name: "register_property_by_url",
    label: "Register Property by URL",
    description: "Registra uma propriedade rural a partir de um link de compartilhamento do Google Maps.",
    parameters: Type.Object({
      url: Type.String({ description: "URL de compartilhamento do Google Maps" }),
      user_id: Type.String({ description: "User ID from session context" }),
    }),
    async execute(_toolCallId, params) {
      const result = await callTool("property", { action: "register_by_url", url: params.url, user_id: params.user_id });
      if (result.error) return errorResult(result);
      return {
        content: [{ type: "text", text: result.message }],
        details: { imagePaths: result.images || [], sessionState: result.session_state },
      };
    },
  });

  pi.registerTool({
    name: "confirm_property_selection",
    label: "Confirm Property Selection",
    description: "Confirma a propriedade selecionada quando há apenas uma opção.",
    parameters: Type.Object({
      user_id: Type.String({ description: "User ID from session context" }),
    }),
    async execute(_toolCallId, params) {
      const result = await callTool("property", { action: "confirm_selection", user_id: params.user_id });
      if (result.error) return errorResult(result);
      return makeResult(result);
    },
  });

  pi.registerTool({
    name: "select_property_from_list",
    label: "Select Property from List",
    description: "Seleciona uma propriedade de uma lista de múltiplos resultados.",
    parameters: Type.Object({
      selection: Type.Integer({ description: "Número da opção escolhida (1, 2, 3...)" }),
      user_id: Type.String({ description: "User ID from session context" }),
    }),
    async execute(_toolCallId, params) {
      const result = await callTool("property", { action: "select_from_list", selection: params.selection, user_id: params.user_id });
      if (result.error) return errorResult(result);
      return makeResult(result);
    },
  });

  pi.registerTool({
    name: "complete_property_registration",
    label: "Complete Property Registration",
    description: "Conclui o cadastro da propriedade com o nome escolhido pelo usuário.",
    parameters: Type.Object({
      name: Type.String({ description: "Nome da propriedade (ex: Fazenda Primavera)" }),
      user_id: Type.String({ description: "User ID from session context" }),
    }),
    async execute(_toolCallId, params) {
      const result = await callTool("property", { action: "complete_registration", name: params.name, user_id: params.user_id });
      if (result.error) return errorResult(result);
      return makeResult(result);
    },
  });

  pi.registerTool({
    name: "cancel_property_registration",
    label: "Cancel Property Registration",
    description: "Cancela o processo de cadastro de propriedade em andamento.",
    parameters: Type.Object({
      user_id: Type.String({ description: "User ID from session context" }),
    }),
    async execute(_toolCallId, params) {
      const result = await callTool("property", { action: "cancel_registration", user_id: params.user_id });
      if (result.error) return errorResult(result);
      return makeResult(result);
    },
  });

  pi.registerTool({
    name: "remove_property",
    label: "Remove Property",
    description: "Remove uma propriedade registrada do sistema.",
    parameters: Type.Object({
      car_code: Type.String({ description: "Código CAR da propriedade a remover" }),
      user_id: Type.String({ description: "User ID from session context" }),
    }),
    async execute(_toolCallId, params) {
      const result = await callTool("property", { action: "remove", car_code: params.car_code, user_id: params.user_id });
      if (result.error) return errorResult(result);
      return makeResult(result);
    },
  });

  pi.registerTool({
    name: "remove_all_properties",
    label: "Remove All Properties",
    description: "Remove todas as propriedades registradas do sistema.",
    parameters: Type.Object({
      user_id: Type.String({ description: "User ID from session context" }),
    }),
    async execute(_toolCallId, params) {
      const result = await callTool("property", { action: "remove_all", user_id: params.user_id });
      if (result.error) return errorResult(result);
      return makeResult(result);
    },
  });

  pi.registerTool({
    name: "set_property_name",
    label: "Set Property Name",
    description: "Atualiza o nome de uma propriedade já registrada.",
    parameters: Type.Object({
      car_codes: Type.Array(Type.String(), { description: "Lista de códigos CAR da propriedade" }),
      name: Type.String({ description: "Novo nome da propriedade" }),
      user_id: Type.String({ description: "User ID from session context" }),
    }),
    async execute(_toolCallId, params) {
      const result = await callTool("property", { action: "set_name", car_codes: params.car_codes, name: params.name, user_id: params.user_id });
      if (result.error) return errorResult(result);
      return makeResult(result);
    },
  });

  // ── Pasture analysis ──────────────────────────────────────────────────

  pi.registerTool({
    name: "get_pasture_stats",
    label: "Pasture Statistics",
    description: "Recupera estatísticas de biomassa, vigor vegetativo, idade da pastagem e classificação de uso do solo.",
    parameters: Type.Object({
      car_codes: Type.Array(Type.String(), { description: "Lista de códigos CAR da propriedade" }),
      year: Type.Optional(Type.Integer({ description: "Ano de referência (default: 2026)" })),
      month: Type.Optional(Type.Integer({ description: "Mês de referência (default: 5)" })),
    }),
    async execute(_toolCallId, params) {
      const result = await callTool("gee", { action: "pasture_stats", car_codes: params.car_codes, year: params.year || 2026, month: params.month || 5 });
      if (result.error) return errorResult(result);
      return makeResult({ message: result.stats_text || JSON.stringify(result.stats) });
    },
  });

  pi.registerTool({
    name: "get_topographic_stats",
    label: "Topographic Statistics",
    description: "Recupera estatísticas de topografia (altimetria e declividade) de uma propriedade.",
    parameters: Type.Object({
      car_codes: Type.Array(Type.String(), { description: "Lista de códigos CAR da propriedade" }),
    }),
    async execute(_toolCallId, params) {
      const result = await callTool("gee", { action: "topographic_stats", car_codes: params.car_codes });
      if (result.error) return errorResult(result);
      return makeResult({ message: result.stats_text || JSON.stringify(result.stats) });
    },
  });

  pi.registerTool({
    name: "generate_property_image",
    label: "Property Satellite Image",
    description: "Gera uma imagem de satélite em alta resolução (RGB) da propriedade rural com delimitação geográfica.",
    parameters: Type.Object({
      car_codes: Type.Array(Type.String(), { description: "Lista de códigos CAR da propriedade" }),
    }),
    async execute(_toolCallId, params) {
      const result = await callTool("gee", { action: "property_image", car_codes: params.car_codes });
      if (result.error) return errorResult(result);
      return makeResult(result);
    },
  });

  pi.registerTool({
    name: "generate_biomass_image",
    label: "Biomass Map",
    description: "Gera um mapa temático da biomassa (matéria seca) sobre os limites da propriedade.",
    parameters: Type.Object({
      car_codes: Type.Array(Type.String(), { description: "Lista de códigos CAR da propriedade" }),
    }),
    async execute(_toolCallId, params) {
      const result = await callTool("gee", { action: "biomass_image", car_codes: params.car_codes });
      if (result.error) return errorResult(result);
      return makeResult(result);
    },
  });

  pi.registerTool({
    name: "generate_soil_texture_image",
    label: "Soil Texture Map",
    description: "Gera um mapa temático da textura do solo sobre os limites da propriedade (0-30cm).",
    parameters: Type.Object({
      car_codes: Type.Array(Type.String(), { description: "Lista de códigos CAR da propriedade" }),
    }),
    async execute(_toolCallId, params) {
      const result = await callTool("gee", { action: "soil_texture_image", car_codes: params.car_codes });
      if (result.error) return errorResult(result);
      return makeResult(result);
    },
  });

  pi.registerTool({
    name: "generate_pasture_classification_image",
    label: "Pasture Classification Map",
    description: "Gera o mapa de classificação de pastagem (pasto x não-pasto) calculado sob demanda.",
    parameters: Type.Object({
      car_codes: Type.Array(Type.String(), { description: "Lista de códigos CAR da propriedade" }),
    }),
    async execute(_toolCallId, params) {
      const result = await callTool("gee", { action: "pasture_classification_image", car_codes: params.car_codes });
      if (result.error) return errorResult(result);
      return makeResult(result);
    },
  });

  // ── TTS ────────────────────────────────────────────────────────────────

  pi.registerTool({
    name: "generate_speech",
    label: "Generate Speech",
    description: "Gera áudio falado a partir de um texto. Use APENAS quando o usuário solicitar explicitamente uma resposta em áudio.",
    parameters: Type.Object({
      text: Type.String({ description: "Texto completo para converter em fala" }),
      user_id: Type.String({ description: "User ID from session context" }),
    }),
    async execute(_toolCallId, params) {
      const result = await callTool("tts", { text: params.text, user_id: params.user_id });
      if (result.error) return errorResult(result);
      return makeResult(result);
    },
  });

  // ── Onboarding ────────────────────────────────────────────────────────

  pi.registerTool({
    name: "accept_terms_and_conditions",
    label: "Accept Terms",
    description: "Registra a aceitação formal dos Termos de Uso do Pasto Legal.",
    parameters: Type.Object({
      user_id: Type.String({ description: "User ID from session context" }),
    }),
    async execute(_toolCallId, params) {
      const result = await callTool("onboarding", { action: "accept_terms", user_id: params.user_id });
      if (result.error) return errorResult(result);
      return makeResult(result);
    },
  });

  // ── Version / changelog ───────────────────────────────────────────────

  pi.registerTool({
    name: "consult_update_notes",
    label: "Update Notes",
    description: "Lê e retorna as notas de atualização (patch notes) do sistema Pasto Legal.",
    parameters: Type.Object({}),
    async execute() {
      const result = await callTool("version", { action: "update_notes" });
      if (result.error) return errorResult(result);
      return makeResult({ message: result.notes });
    },
  });
}
