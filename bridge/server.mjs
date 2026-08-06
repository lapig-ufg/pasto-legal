/**
 * Pasto Legal Bridge — pi SDK wrapper for the WhatsApp ranching assistant.
 *
 * Usage:
 *   GOOGLE_API_KEY=... node bridge/server.mjs
 *
 * Environment:
 *   GOOGLE_API_KEY  – Gemini API key
 *   BRIDGE_PORT      – HTTP listen port (default 3001)
 *   CLI_DIR          – path to Python CLI directory (default ../cli)
 */

import {
  createAgentSession,
  ModelRuntime,
  SessionManager,
  DefaultResourceLoader,
  getAgentDir,
} from "@earendil-works/pi-coding-agent";
import express from "express";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const PORT = parseInt(process.env.BRIDGE_PORT || "3001", 10);

// ── System prompt ────────────────────────────────────────────────────────────
const SYSTEM_PROMPT = `
Você é o **Pasto Legal**, um assistente virtual para pecuaristas brasileiros,
desenvolvido pelo LAPIG/UFG. Você ajuda produtores rurais com:

1. **Análise de pastagens** – biomassa, vigor vegetativo (NDVI/LAPIG),
   classificação de uso do solo, idade do pasto, topografia, textura do solo.
2. **Cadastro de propriedades** – registro via código CAR/SICAR, coordenadas
   geográficas ou link do Google Maps.
3. **Dúvidas sobre a plataforma** – como usar, de onde vêm os dados, FAQs.
4. **Conversa informal** – acolhimento, saudações, pequenas conversas.

## Regra de acesso — NOVOS USUÁRIOS (terms_accepted = false)
Se o <session-state> indicar "terms_accepted": false, o usuário AINDA NÃO
aceitou os Termos de Uso. Neste caso, você DEVE:
- Ignorar QUALQUER outra solicitação do usuário.
- Apresentar-se brevemente como assistente do Pasto Legal (LAPIG/UFG).
- Informar o link dos Termos de Uso: https://pasto.legal/termos-de-uso
- Perguntar educadamente se o usuário concorda com os termos.
- Apenas quando o usuário responder SIM, ACEITO, CONCORDO (ou similar),
  chame a ferramenta \`accept_terms_and_conditions\`.
- NUNCA faça análises, cadastros ou responda outras perguntas antes do aceite.
- Se o usuário tiver dúvidas sobre os termos, responda com base neste resumo:
  Plataforma gratuita do LAPIG/UFG, usa dados de satélite Copernicus/ESA,
  código aberto (MIT), serviço "as is", contato lapig.ufg@gmail.com.

## Regras absolutas (todos os usuários)
- Comunique-se SEMPRE em português brasileiro, linguagem simples e acessível.
- Use formatação do WhatsApp: *negrito* com asteriscos, sem markdown.
- NUNCA diga que você é um robô, IA, chatbot ou modelo de linguagem.
- NUNCA cite termos técnicos de software (prompts, ferramentas, agentes, tokens).
- Seja conciso. Respostas curtas, parágrafos limpos.
- Use emojis com moderação.
- Se o usuário pedir áudio, responda em texto — o sistema converte depois.

## Estado da sessão
O estado do usuário (propriedades cadastradas, persona, humor) é passado
como contexto no início de cada mensagem, dentro de tags <session-state>.
Use essas informações para personalizar suas respostas.

## Ferramentas disponíveis
Use as ferramentas cadastradas para buscar dados de propriedades, gerar
imagens de satélite, calcular estatísticas de pastagem e sintetizar áudio.
`.trim();

// ── Model runtime ───────────────────────────────────────────────────────────
const GOOGLE_API_KEY = process.env.GOOGLE_API_KEY;
if (!GOOGLE_API_KEY) {
  console.error("[pasto-legal-bridge] FATAL: GOOGLE_API_KEY environment variable is not set.");
  process.exit(1);
}

const modelRuntime = await ModelRuntime.create();
modelRuntime.setRuntimeApiKey("google", GOOGLE_API_KEY);

const model = modelRuntime.getModel("google", "gemini-2.5-flash")
  || modelRuntime.getModel("google", "gemini-2.0-flash")
  || modelRuntime.getModel("google", "gemini-1.5-flash");

if (!model) {
  console.error("[pasto-legal-bridge] FATAL: No Google Gemini model found.");
  process.exit(1);
}

console.log(`[pasto-legal-bridge] Using model: ${model.provider}/${model.id}`);

// ── Resource loader ─────────────────────────────────────────────────────────
const loader = new DefaultResourceLoader({
  cwd: __dirname,
  agentDir: getAgentDir(),
  additionalExtensionPaths: [resolve(__dirname, "extensions", "pasto-legal-tools.mjs")],
  systemPromptOverride: () => SYSTEM_PROMPT,
});
await loader.reload();

const skills = loader.getSkills().skills;
console.log(`[pasto-legal-bridge] Loaded ${skills.length} skills:`, skills.map(s => s.name).join(", "));

// ── Session cache ───────────────────────────────────────────────────────────
const sessions = new Map();
const SESSION_TTL = 30 * 60 * 1000;

function getOrCreateSession(userId) {
  const now = Date.now();
  for (const [id, entry] of sessions) {
    if (now - entry.lastUsed > SESSION_TTL) {
      entry.session.dispose().catch(() => {});
      sessions.delete(id);
    }
  }
  const existing = sessions.get(userId);
  if (existing) {
    existing.lastUsed = now;
    return existing.session;
  }
  return null;
}

async function createSession(userId) {
  const { session } = await createAgentSession({
    modelRuntime,
    model,
    resourceLoader: loader,
    sessionManager: SessionManager.inMemory(),
  });
  sessions.set(userId, { session, lastUsed: Date.now() });
  return session;
}

// ── Prompt builder ───────────────────────────────────────────────────────────
function buildPrompt(message, sessionState) {
  const parts = [];
  if (sessionState) {
    parts.push("<session-state>");
    if (sessionState.user_persona) {
      parts.push(`<user-persona>${JSON.stringify(sessionState.user_persona)}</user-persona>`);
    }
    if (sessionState.all_properties?.length) {
      parts.push("<registered-properties>");
      for (const p of sessionState.all_properties) {
        parts.push(`- CAR: ${p.car_code}, Nome: ${p.nickname || "sem nome"}`);
      }
      parts.push("</registered-properties>");
    }
    if (sessionState.registration_state) {
      parts.push(`<registration-state>${sessionState.registration_state}</registration-state>`);
    }
    if (sessionState.candidate_properties?.length) {
      parts.push("<candidate-properties>");
      for (const p of sessionState.candidate_properties) {
        parts.push(`- CAR: ${p.car_code}, Área: ${p.spatial_features?.total_area} ha, Município: ${p.spatial_features?.municipality}`);
      }
      parts.push("</candidate-properties>");
    }
    parts.push("</session-state>");
  }
  parts.push(`<user-message>${message}</user-message>`);
  return parts.join("\n");
}

// ── Express server ───────────────────────────────────────────────────────────
const app = express();
app.use(express.json({ limit: "10mb" }));

app.get("/health", (_req, res) => res.json({ status: "ok", sessions: sessions.size }));

app.post("/prompt", async (req, res) => {
  const { userId, message, sessionState } = req.body;
  if (!userId || !message) {
    return res.status(400).json({ error: "userId and message are required" });
  }

  console.log(`[bridge] → prompt  user=${userId.slice(0,16)}  msg=${message.slice(0,100)}`);

  try {
    let session = getOrCreateSession(userId);
    if (!session) {
      console.log(`[bridge] creating new session for ${userId.slice(0,16)}`);
      session = await createSession(userId);
    }

    const fullPrompt = buildPrompt(message, sessionState);

    let responseText = "";
    const responseImages = [];
    const responseAudio = [];

    const unsubscribe = session.subscribe((event) => {
      if (event.type === "message_update") {
        if (event.assistantMessageEvent?.type === "text_delta") {
          responseText += event.assistantMessageEvent.delta;
        }
      }
      if (event.type === "tool_execution_start") {
        console.log(`[bridge] 🔧 tool start: ${event.toolName}  args=${JSON.stringify(event.args).slice(0,150)}`);
      }
      if (event.type === "tool_execution_end") {
        const result = event.result;
        const preview = JSON.stringify(result?.content || result?.details || "").slice(0, 200);
        console.log(`[bridge] 🔧 tool end: ${event.toolName}  isError=${event.isError}  result=${preview}`);
        if (result?.details?.imagePaths) {
          responseImages.push(...result.details.imagePaths);
        }
        if (result?.details?.audioPath) {
          responseAudio.push(result.details.audioPath);
        }
      }
      if (event.type === "agent_end") {
        console.log(`[bridge] agent_end  messages=${event.messages?.length}`);
      }
    });

    await session.prompt(fullPrompt);
    unsubscribe();

    console.log(`[bridge] ← prompt  user=${userId.slice(0,16)}  response=${responseText.slice(0,100)}`);

    res.json({
      content: responseText.trim() || "Desculpa, houve um erro ao processar sua mensagem.",
      images: responseImages,
      audio: responseAudio,
    });
  } catch (err) {
    console.error(`[bridge] prompt error for ${userId}:`, err);
    res.status(500).json({ error: "Internal error", detail: err.message });
  }
});

app.post("/reset", async (req, res) => {
  const { userId } = req.body;
  if (!userId) return res.status(400).json({ error: "userId required" });
  const entry = sessions.get(userId);
  if (entry) {
    try { await entry.session.dispose(); } catch {}
    sessions.delete(userId);
  }
  res.json({ status: "reset" });
});

app.listen(PORT, () => {
  console.log(`[pasto-legal-bridge] listening on :${PORT}`);
});
