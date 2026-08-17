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

  // ── Feedback (frustration remediation loop) ───────────────────────────

  pi.registerTool({
    name: "request_feedback",
    label: "Request Feedback",
    description: "Ativa o modo de aguardo de feedback do usuário. Chame APENAS após entregar uma resposta reformulada (remediação) por frustração do usuário, junto da pergunta 'Ficou melhor? Responda SIM ou NÃO'.",
    parameters: Type.Object({
      user_id: Type.String({ description: "User ID from session context" }),
    }),
    async execute(_toolCallId, params) {
      const result = await callTool("feedback", { action: "request_feedback", user_id: params.user_id });
      if (result.error) return errorResult(result);
      return makeResult(result);
    },
  });

  pi.registerTool({
    name: "save_feedback",
    label: "Save Feedback",
    description: "Registra o feedback do usuário (positivo ou negativo) sobre a resposta reformulada e encerra o modo de feedback. Chame ao classificar a resposta do usuário à pergunta 'Ficou melhor?'.",
    parameters: Type.Object({
      user_id: Type.String({ description: "User ID from session context" }),
      verdict: Type.String({ description: "Avaliação do usuário: 'positive' se a resposta melhorou, 'negative' se piorou ou não resolveu" }),
      user_message: Type.String({ description: "Mensagem do usuário que respondeu à pergunta de feedback" }),
      assistant_response: Type.String({ description: "A resposta reformulada que foi avaliada pelo usuário" }),
      reason: Type.Optional(Type.String({ description: "Justificativa do veredito (opcional)" })),
    }),
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
  });

  // ── Alert Schedulers (benchmark — mocked) ───────────────────────────────
  //
  // Mocked alert-scheduler tools used to grow the tool registry for the
  // single-agent benchmark (see BENCHMARK.md). Each alert type exposes a
  // `request_*` (plans the scheduler, asks for confirmation) and a
  // `confirm_*` (registers the scheduler when the user says yes). All calls
  // go to the Python `benchmark` tool, which returns canned JSON without
  // hitting any real backend. The two-step confirm flow mirrors
  // request_feedback / save_feedback and the property registration flow.

  // ── Biomass alert (dry-matter, kg/ha — all logic operators) ────────────

  pi.registerTool({
    name: "request_biomass_alert",
    label: "Request Biomass Alert",
    description: "Planeja um alerta via WhatsApp que dispara quando a biomassa (matéria seca, kg/ha) atinge uma condição definida por operador lógico (gt, lt, le, ge, eq, neq) e um valor de referência. Retorna o plano e pede confirmação.",
    parameters: Type.Object({
      operator: Type.String({ description: "Operador lógico: 'gt' (maior que), 'lt' (menor que), 'le' (menor ou igual), 'ge' (maior ou igual), 'eq' (igual), 'neq' (diferente de)" }),
      threshold: Type.Number({ description: "Valor de referência da biomassa em kg/ha (ex: 2500)" }),
      car_codes: Type.Optional(Type.Array(Type.String(), { description: "Lista de códigos CAR da propriedade (opcional, usa a atual se omitido)" })),
      user_id: Type.String({ description: "User ID from session context" }),
    }),
    async execute(_toolCallId, params) {
      const result = await callTool("benchmark", { action: "request_biomass_alert", operator: params.operator, threshold: params.threshold, car_codes: params.car_codes || [], user_id: params.user_id });
      if (result.error) return errorResult(result);
      return makeResult(result);
    },
  });

  pi.registerTool({
    name: "confirm_biomass_alert",
    label: "Confirm Biomass Alert",
    description: "Confirma o cadastro do alerta de biomassa planejado. Chame APENAS quando o usuário concordar com o plano apresentado por request_biomass_alert (ex: 'sim', 'pode sim', 'confirma'). Retorna a confirmação do agendamento e a condição definida.",
    parameters: Type.Object({
      user_id: Type.String({ description: "User ID from session context" }),
    }),
    async execute(_toolCallId, params) {
      const result = await callTool("benchmark", { action: "confirm_biomass_alert", user_id: params.user_id });
      if (result.error) return errorResult(result);
      return makeResult(result);
    },
  });

  // ── Rain alert (accumulated rainfall, mm) ──────────────────────────────

  pi.registerTool({
    name: "request_rain_alert",
    label: "Request Rain Alert",
    description: "Planeja um alerta via WhatsApp que dispara quando a chuva acumulada (mm) em uma janela de dias atinge uma condição definida por operador lógico (gt, lt, le, ge, eq, neq) e um valor de referência. Retorna o plano e pede confirmação.",
    parameters: Type.Object({
      operator: Type.String({ description: "Operador lógico: 'gt', 'lt', 'le', 'ge', 'eq', 'neq'" }),
      threshold: Type.Number({ description: "Valor de referência de chuva acumulada em mm (ex: 80)" }),
      window_days: Type.Optional(Type.Integer({ description: "Janela de acumulação em dias (default: 7)" })),
      car_codes: Type.Optional(Type.Array(Type.String(), { description: "Lista de códigos CAR da propriedade (opcional)" })),
      user_id: Type.String({ description: "User ID from session context" }),
    }),
    async execute(_toolCallId, params) {
      const result = await callTool("benchmark", { action: "request_rain_alert", operator: params.operator, threshold: params.threshold, window_days: params.window_days || 7, car_codes: params.car_codes || [], user_id: params.user_id });
      if (result.error) return errorResult(result);
      return makeResult(result);
    },
  });

  pi.registerTool({
    name: "confirm_rain_alert",
    label: "Confirm Rain Alert",
    description: "Confirma o cadastro do alerta de chuva planejado. Chame APENAS quando o usuário concordar com o plano apresentado por request_rain_alert (ex: 'sim', 'pode sim', 'confirma'). Retorna a confirmação do agendamento e a condição definida.",
    parameters: Type.Object({
      user_id: Type.String({ description: "User ID from session context" }),
    }),
    async execute(_toolCallId, params) {
      const result = await callTool("benchmark", { action: "confirm_rain_alert", user_id: params.user_id });
      if (result.error) return errorResult(result);
      return makeResult(result);
    },
  });

  // ── Vigor alert (NDVI drop-below-threshold) ────────────────────────────

  pi.registerTool({
    name: "request_vigor_alert",
    label: "Request Vigor Alert",
    description: "Planeja um alerta via WhatsApp que dispara quando o vigor vegetativo (NDVI) da pastagem atinge uma condição definida por operador lógico (gt, lt, le, ge, eq, neq) e um valor de referência. Útil para detectar degradação do pasto. Retorna o plano e pede confirmação.",
    parameters: Type.Object({
      operator: Type.String({ description: "Operador lógico: 'gt', 'lt', 'le', 'ge', 'eq', 'neq'. Default 'lt' (queda abaixo)." }),
      threshold: Type.Number({ description: "Valor de referência do NDVI (0 a 1, ex: 0.4)" }),
      car_codes: Type.Optional(Type.Array(Type.String(), { description: "Lista de códigos CAR da propriedade (opcional)" })),
      user_id: Type.String({ description: "User ID from session context" }),
    }),
    async execute(_toolCallId, params) {
      const result = await callTool("benchmark", { action: "request_vigor_alert", operator: params.operator, threshold: params.threshold, car_codes: params.car_codes || [], user_id: params.user_id });
      if (result.error) return errorResult(result);
      return makeResult(result);
    },
  });

  pi.registerTool({
    name: "confirm_vigor_alert",
    label: "Confirm Vigor Alert",
    description: "Confirma o cadastro do alerta de vigor (NDVI) planejado. Chame APENAS quando o usuário concordar com o plano apresentado por request_vigor_alert (ex: 'sim', 'pode sim', 'confirma'). Retorna a confirmação do agendamento e a condição definida.",
    parameters: Type.Object({
      user_id: Type.String({ description: "User ID from session context" }),
    }),
    async execute(_toolCallId, params) {
      const result = await callTool("benchmark", { action: "confirm_vigor_alert", user_id: params.user_id });
      if (result.error) return errorResult(result);
      return makeResult(result);
    },
  });

  // ── Stocking-rate alert (UA/ha exceeds support capacity) ──────────────

  pi.registerTool({
    name: "request_stocking_rate_alert",
    label: "Request Stocking Rate Alert",
    description: "Planeja um alerta via WhatsApp que dispara quando a lotação animal (UA/ha) ultrapassa ou atinge uma condição definida por operador lógico (gt, lt, le, ge, eq, neq) e um valor de referência. Útil para evitar superlotação além da capacidade de suporte. Retorna o plano e pede confirmação.",
    parameters: Type.Object({
      operator: Type.String({ description: "Operador lógico: 'gt', 'lt', 'le', 'ge', 'eq', 'neq'. Default 'gt' (excede)." }),
      threshold: Type.Number({ description: "Valor de referência de lotação em UA/ha (ex: 2.5)" }),
      car_codes: Type.Optional(Type.Array(Type.String(), { description: "Lista de códigos CAR da propriedade (opcional)" })),
      user_id: Type.String({ description: "User ID from session context" }),
    }),
    async execute(_toolCallId, params) {
      const result = await callTool("benchmark", { action: "request_stocking_rate_alert", operator: params.operator, threshold: params.threshold, car_codes: params.car_codes || [], user_id: params.user_id });
      if (result.error) return errorResult(result);
      return makeResult(result);
    },
  });

  pi.registerTool({
    name: "confirm_stocking_rate_alert",
    label: "Confirm Stocking Rate Alert",
    description: "Confirma o cadastro do alerta de lotação (UA/ha) planejado. Chame APENAS quando o usuário concordar com o plano apresentado por request_stocking_rate_alert (ex: 'sim', 'pode sim', 'confirma'). Retorna a confirmação do agendamento e a condição definida.",
    parameters: Type.Object({
      user_id: Type.String({ description: "User ID from session context" }),
    }),
    async execute(_toolCallId, params) {
      const result = await callTool("benchmark", { action: "confirm_stocking_rate_alert", user_id: params.user_id });
      if (result.error) return errorResult(result);
      return makeResult(result);
    },
  });

  // ── List / delete schedulers (benchmark — mocked) ──────────────────────
  //
  // Mocked management tools that operate on a fixed in-memory list of
  // already-registered alert schedulers (MOCKED_SCHEDULERS in benchmark.py).
  // `list_schedulers` shows the list; `delete_scheduler` removes one by
  // name or by its 1-indexed position. Used to exercise the LLM's
  // list/update/delete flow as the tool registry grows (see BENCHMARK.md).

  pi.registerTool({
    name: "list_schedulers",
    label: "List Schedulers",
    description: "Lista os agendamentos de alerta já cadastrados (nome e condição de cada um). Use quando o usuário quiser revisar, listar, atualizar ou modificar seus agendamentos de alerta.",
    parameters: Type.Object({
      user_id: Type.String({ description: "User ID from session context" }),
    }),
    async execute(_toolCallId, params) {
      const result = await callTool("benchmark", { action: "list_schedulers", user_id: params.user_id });
      if (result.error) return errorResult(result);
      return makeResult(result);
    },
  });

  pi.registerTool({
    name: "delete_scheduler",
    label: "Delete Scheduler",
    description: "Remove um agendamento de alerta já cadastrado. Forneça `name` (nome exato do agendamento) OU `number` (número do agendamento na lista retornada por list_schedulers, começando em 1). Use APENAS um dos dois.",
    parameters: Type.Object({
      name: Type.Optional(Type.String({ description: "Nome exato do agendamento a remover (ex: 'Alerta de Biomassa - Fazenda Primavera')" })),
      number: Type.Optional(Type.Integer({ description: "Número do agendamento na lista do list_schedulers (1-indexado)" })),
      user_id: Type.String({ description: "User ID from session context" }),
    }),
    async execute(_toolCallId, params) {
      const payload = { action: "delete_scheduler", user_id: params.user_id };
      if (params.name !== undefined && params.name !== null) payload.name = params.name;
      if (params.number !== undefined && params.number !== null) payload.number = params.number;
      const result = await callTool("benchmark", payload);
      if (result.error) return errorResult(result);
      return makeResult(result);
    },
  });

  // ── Weather (benchmark — mocked) ────────────────────────────────────────
  //
  // weather-benchmark: read-only mocked weather/rain data tools. All return
  // canned JSON tables (max 5 attributes per row) without hitting any
  // backend. Grouped under category "weather" in registry.py so they can be
  // removed in one sweep (see BENCHMARK.md §8). No confirm flow — these are
  // pure data-retrieval mocks that stress Tool-RAG disambiguation between
  // similarly-named weather concepts.

  pi.registerTool({
    name: "get_rain_forecast_15_days",
    label: "Rain Forecast 15 Days",
    description: "Retorna a previsão de chuva para os próximos 15 dias em forma de tabela (data, precipitação mm, máximo, mínimo, probabilidade %). Use quando o usuário quiser saber a previsão de chuva das próximas duas semanas.",
    parameters: Type.Object({
      car_codes: Type.Optional(Type.Array(Type.String(), { description: "Lista de códigos CAR da propriedade (opcional)" })),
      user_id: Type.String({ description: "User ID from session context" }),
    }),
    async execute(_toolCallId, params) {
      const result = await callTool("benchmark", { action: "get_rain_forecast_15_days", car_codes: params.car_codes || [], user_id: params.user_id });
      if (result.error) return errorResult(result);
      return makeResult(result);
    },
  });

  pi.registerTool({
    name: "get_rain_forecast_months",
    label: "Rain Forecast Months",
    description: "Retorna a previsão de chuva mensal para 1 a 3 meses à frente em forma de tabela (mês, precipitação mm, máximo, mínimo, probabilidade %). Use quando o usuário quiser saber a previsão de chuva para os próximos meses (máximo 3).",
    parameters: Type.Object({
      months: Type.Integer({ description: "Número de meses à frente (1 a 3)" }),
      car_codes: Type.Optional(Type.Array(Type.String(), { description: "Lista de códigos CAR da propriedade (opcional)" })),
      user_id: Type.String({ description: "User ID from session context" }),
    }),
    async execute(_toolCallId, params) {
      const result = await callTool("benchmark", { action: "get_rain_forecast_months", months: params.months, car_codes: params.car_codes || [], user_id: params.user_id });
      if (result.error) return errorResult(result);
      return makeResult(result);
    },
  });

  pi.registerTool({
    name: "get_rain_history",
    label: "Rain History",
    description: "Retorna o histórico de chuva diário de um mês passado específico em forma de tabela (data, precipitação mm, máximo, mínimo, probabilidade %). Use quando o usuário quiser saber quanto choveu em um mês anterior.",
    parameters: Type.Object({
      month: Type.Integer({ description: "Mês (1 a 12)" }),
      year: Type.Integer({ description: "Ano (deve ser no passado)" }),
      car_codes: Type.Optional(Type.Array(Type.String(), { description: "Lista de códigos CAR da propriedade (opcional)" })),
      user_id: Type.String({ description: "User ID from session context" }),
    }),
    async execute(_toolCallId, params) {
      const result = await callTool("benchmark", { action: "get_rain_history", month: params.month, year: params.year, car_codes: params.car_codes || [], user_id: params.user_id });
      if (result.error) return errorResult(result);
      return makeResult(result);
    },
  });

  pi.registerTool({
    name: "get_weather_today",
    label: "Weather Today",
    description: "Retorna as condições climáticas atuais (hoje): precipitação, temperatura, umidade e condição (ensolarado, nublado, chuva leve/forte). Use quando o usuário quiser saber como está o tempo agora.",
    parameters: Type.Object({
      car_codes: Type.Optional(Type.Array(Type.String(), { description: "Lista de códigos CAR da propriedade (opcional)" })),
      user_id: Type.String({ description: "User ID from session context" }),
    }),
    async execute(_toolCallId, params) {
      const result = await callTool("benchmark", { action: "get_weather_today", car_codes: params.car_codes || [], user_id: params.user_id });
      if (result.error) return errorResult(result);
      return makeResult(result);
    },
  });

  pi.registerTool({
    name: "get_temperature_forecast_15_days",
    label: "Temperature Forecast 15 Days",
    description: "Retorna a previsão de temperatura para os próximos 15 dias em forma de tabela (data, máxima, mínima, média °C, condição). Use quando o usuário quiser saber a previsão de temperatura das próximas duas semanas, não de chuva.",
    parameters: Type.Object({
      car_codes: Type.Optional(Type.Array(Type.String(), { description: "Lista de códigos CAR da propriedade (opcional)" })),
      user_id: Type.String({ description: "User ID from session context" }),
    }),
    async execute(_toolCallId, params) {
      const result = await callTool("benchmark", { action: "get_temperature_forecast_15_days", car_codes: params.car_codes || [], user_id: params.user_id });
      if (result.error) return errorResult(result);
      return makeResult(result);
    },
  });

  pi.registerTool({
    name: "get_drought_index",
    label: "Drought Index",
    description: "Retorna o índice de seca (SPEI-like) para um mês/ano específico: índice (-3 a +3), categoria (severo/seco/normal/úmido), tendência e região. Use quando o usuário quiser saber o nível de seca de um período, não a chuva direta.",
    parameters: Type.Object({
      month: Type.Integer({ description: "Mês (1 a 12)" }),
      year: Type.Integer({ description: "Ano" }),
      user_id: Type.String({ description: "User ID from session context" }),
    }),
    async execute(_toolCallId, params) {
      const result = await callTool("benchmark", { action: "get_drought_index", month: params.month, year: params.year, user_id: params.user_id });
      if (result.error) return errorResult(result);
      return makeResult(result);
    },
  });

  pi.registerTool({
    name: "get_evapotranspiration",
    label: "Evapotranspiration",
    description: "Retorna a evapotranspiração de referência (ET₀ em mm/dia) para um mês/ano: ET₀ diária, ET₀ total, temperatura média e umidade. Use quando o usuário quiser saber a evapotranspiração ou demanda hídrica do pasto.",
    parameters: Type.Object({
      month: Type.Integer({ description: "Mês (1 a 12)" }),
      year: Type.Integer({ description: "Ano" }),
      user_id: Type.String({ description: "User ID from session context" }),
    }),
    async execute(_toolCallId, params) {
      const result = await callTool("benchmark", { action: "get_evapotranspiration", month: params.month, year: params.year, user_id: params.user_id });
      if (result.error) return errorResult(result);
      return makeResult(result);
    },
  });

  pi.registerTool({
    name: "get_soil_moisture",
    label: "Soil Moisture",
    description: "Retorna a umidade do solo atual (%) da propriedade: umidade, máxima, mínima e profundidade. Use quando o usuário quiser saber a umidade da terra/solo agora, não a chuva ou temperatura.",
    parameters: Type.Object({
      car_codes: Type.Optional(Type.Array(Type.String(), { description: "Lista de códigos CAR da propriedade (opcional)" })),
      user_id: Type.String({ description: "User ID from session context" }),
    }),
    async execute(_toolCallId, params) {
      const result = await callTool("benchmark", { action: "get_soil_moisture", car_codes: params.car_codes || [], user_id: params.user_id });
      if (result.error) return errorResult(result);
      return makeResult(result);
    },
  });

  pi.registerTool({
    name: "get_climate_summary",
    label: "Climate Summary",
    description: "Retorna o resumo climático anual de uma região: chuva total, temperatura média, meses secos e chuvosos. Use quando o usuário quiser um panorama climático do ano, não dados diários ou mensais.",
    parameters: Type.Object({
      year: Type.Integer({ description: "Ano" }),
      user_id: Type.String({ description: "User ID from session context" }),
    }),
    async execute(_toolCallId, params) {
      const result = await callTool("benchmark", { action: "get_climate_summary", year: params.year, user_id: params.user_id });
      if (result.error) return errorResult(result);
      return makeResult(result);
    },
  });

  // ── Forage budget, paddock & herd tools (benchmark — mocked) ───────────
  //
  // pasture-benchmark / paddock-benchmark / herd-benchmark: mocked tools
  // for forage budget estimation, paddock management (CRUD), per-paddock
  // pasture/topographic stats, rotation scheduling, and vaccination
  // calendar. All return canned JSON without hitting any backend. Grouped
  // under categories "pasture", "paddock", and "herd" in registry.py so
  // they can be removed in one sweep per category (see BENCHMARK.md §8).
  // Paddock state is persisted in Valkey session_state (all_paddocks key),
  // mirroring the property registration pattern.

  pi.registerTool({
    name: "get_forage_budget",
    label: "Forage Budget",
    description: "Estima quantos dias de pasto restam para o rebanho, combinando biomassa disponível com tamanho do rebanho (UA). Retorna biomassa total, consumo diário, dias restantes e recomendação de manejo.",
    parameters: Type.Object({
      herd_size_ua: Type.Number({ description: "Tamanho do rebanho em Unidades Animais (UA)" }),
      car_codes: Type.Optional(Type.Array(Type.String(), { description: "Lista de códigos CAR da propriedade (opcional)" })),
      user_id: Type.String({ description: "User ID from session context" }),
    }),
    async execute(_toolCallId, params) {
      const result = await callTool("benchmark", { action: "get_forage_budget", herd_size_ua: params.herd_size_ua, car_codes: params.car_codes || [], user_id: params.user_id });
      if (result.error) return errorResult(result);
      return makeResult(result);
    },
  });

  pi.registerTool({
    name: "auto_generate_paddocks",
    label: "Auto Generate Paddocks",
    description: "Divide automaticamente uma propriedade em N piquetes (2 a 10) com áreas variadas e labels padrão. Os piquetes ficam disponíveis para análise individual e rotação.",
    parameters: Type.Object({
      car_codes: Type.Array(Type.String(), { description: "Lista de códigos CAR da propriedade" }),
      count: Type.Optional(Type.Integer({ description: "Número de piquetes (2 a 10, padrão 4)" })),
      user_id: Type.String({ description: "User ID from session context" }),
    }),
    async execute(_toolCallId, params) {
      const payload = { action: "auto_generate_paddocks", car_codes: params.car_codes, user_id: params.user_id };
      if (params.count !== undefined && params.count !== null) payload.count = params.count;
      const result = await callTool("benchmark", payload);
      if (result.error) return errorResult(result);
      return {
        content: [{ type: "text", text: result.message }],
        details: { imagePaths: result.images || [], sessionState: result.session_state },
      };
    },
  });

  pi.registerTool({
    name: "set_paddock_label",
    label: "Set Paddock Label",
    description: "Define ou atualiza o nome (label) de um piquete pelo seu ID (ex: pdk-001).",
    parameters: Type.Object({
      paddock_id: Type.String({ description: "ID do piquete (ex: pdk-001)" }),
      label: Type.String({ description: "Novo nome do piquete" }),
      user_id: Type.String({ description: "User ID from session context" }),
    }),
    async execute(_toolCallId, params) {
      const result = await callTool("benchmark", { action: "set_paddock_label", paddock_id: params.paddock_id, label: params.label, user_id: params.user_id });
      if (result.error) return errorResult(result);
      return makeResult(result);
    },
  });

  pi.registerTool({
    name: "delete_paddock",
    label: "Delete Paddock",
    description: "Remove um piquete pelo seu ID (ex: pdk-001).",
    parameters: Type.Object({
      paddock_id: Type.String({ description: "ID do piquete (ex: pdk-001)" }),
      user_id: Type.String({ description: "User ID from session context" }),
    }),
    async execute(_toolCallId, params) {
      const result = await callTool("benchmark", { action: "delete_paddock", paddock_id: params.paddock_id, user_id: params.user_id });
      if (result.error) return errorResult(result);
      return makeResult(result);
    },
  });

  pi.registerTool({
    name: "get_paddock_pasture_stats",
    label: "Paddock Pasture Stats",
    description: "Retorna estatísticas de pastagem (biomassa, vigor, idade, uso do solo) de um piquete específico pelo seu ID, no mesmo formato de get_pasture_stats.",
    parameters: Type.Object({
      paddock_id: Type.String({ description: "ID do piquete (ex: pdk-001)" }),
      user_id: Type.String({ description: "User ID from session context" }),
    }),
    async execute(_toolCallId, params) {
      const result = await callTool("benchmark", { action: "get_paddock_pasture_stats", paddock_id: params.paddock_id, user_id: params.user_id });
      if (result.error) return errorResult(result);
      return makeResult({ message: result.stats_text || JSON.stringify(result.stats) });
    },
  });

  pi.registerTool({
    name: "get_paddock_topographic_stats",
    label: "Paddock Topographic Stats",
    description: "Retorna estatísticas de topografia (altimetria e declividade) de um piquete específico pelo seu ID.",
    parameters: Type.Object({
      paddock_id: Type.String({ description: "ID do piquete (ex: pdk-001)" }),
      user_id: Type.String({ description: "User ID from session context" }),
    }),
    async execute(_toolCallId, params) {
      const result = await callTool("benchmark", { action: "get_paddock_topographic_stats", paddock_id: params.paddock_id, user_id: params.user_id });
      if (result.error) return errorResult(result);
      return makeResult({ message: result.stats_text || JSON.stringify(result.stats) });
    },
  });

  pi.registerTool({
    name: "get_rotation_schedule",
    label: "Rotation Schedule",
    description: "Gera um plano de rotação de pastagem baseado nos piquetes cadastrados: ordena por biomassa e dias de repouso, sugere ordem de pastejo e dias de ocupação por piquete.",
    parameters: Type.Object({
      rest_days: Type.Optional(Type.Integer({ description: "Período de repouso desejado em dias (padrão 30)" })),
      herd_size_ua: Type.Optional(Type.Number({ description: "Tamanho do rebanho em UA (padrão 50)" })),
      user_id: Type.String({ description: "User ID from session context" }),
    }),
    async execute(_toolCallId, params) {
      const payload = { action: "get_rotation_schedule", user_id: params.user_id };
      if (params.rest_days !== undefined && params.rest_days !== null) payload.rest_days = params.rest_days;
      if (params.herd_size_ua !== undefined && params.herd_size_ua !== null) payload.herd_size_ua = params.herd_size_ua;
      const result = await callTool("benchmark", payload);
      if (result.error) return errorResult(result);
      return makeResult(result);
    },
  });

  pi.registerTool({
    name: "get_vaccination_calendar",
    label: "Vaccination Calendar",
    description: "Retorna o calendário anual de vacinação do rebanho (aftosa, brucelose, carbúnculo, raiva, clostridioses, botulismo) adaptado à região Centro-Oeste.",
    parameters: Type.Object({
      car_codes: Type.Optional(Type.Array(Type.String(), { description: "Lista de códigos CAR da propriedade (opcional, usado para derivar região)" })),
      year: Type.Optional(Type.Integer({ description: "Ano (padrão: atual)" })),
      user_id: Type.String({ description: "User ID from session context" }),
    }),
    async execute(_toolCallId, params) {
      const payload = { action: "get_vaccination_calendar", user_id: params.user_id };
      if (params.car_codes) payload.car_codes = params.car_codes;
      if (params.year !== undefined && params.year !== null) payload.year = params.year;
      const result = await callTool("benchmark", payload);
      if (result.error) return errorResult(result);
      return makeResult(result);
    },
  });
}
