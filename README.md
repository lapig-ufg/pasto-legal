# 🌿 Pasto Legal

**AI-powered agricultural extension via WhatsApp** — delivering satellite-based pasture diagnostics, agronomic consultancy, and property management to rural producers in Brazil.

[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/) [![License: GPLv3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE) [![Status: Alpha](https://img.shields.io/badge/status-alpha-orange.svg)]()

---

## About

Pasto Legal is an open-science platform that brings advanced satellite analytics and agronomic expertise directly to farmers' phones through WhatsApp. Behind a simple chat interface, an AI assistant connects to official databases (SICAR — Brazil's Rural Environmental Registry) and global satellites (Google Earth Engine, MapBiomas) to transform complex geospatial data into fast answers, clear maps, and precise diagnostics for rural properties.

The system is designed to be as natural as talking to a trusted agronomist — no menus, no complex navigation. Farmers can send text, audio (while standing in the field), or photos of their pasture and get actionable insights in return.

**Core capabilities:**

- 🛰️ **Pasture health monitoring** — biomass, vegetation vigor, pasture age, and land-use/cover maps derived from satellite imagery
- 🐄 **Carrying capacity calculations** — real stocking rates and ideal carrying capacity (UA/ha) using the LAPIG methodology
- 📋 **Property registration** — lookup and register properties by CAR/SICAR code, GPS coordinates, or Google Maps link
- 🌾 **Agronomic consultancy** — EMBRAPA-validated guidance on forage management, stocking rates, and pasture recovery
- 🗺️ **Thematic map generation** — biomass, soil texture, land-use, and topographic maps clipped to property boundaries
- 🔊 **Voice responses** — audio reports narrated back to the producer via WhatsApp

---

## Sponsors & Partners

Pasto Legal was born from the **Desafio IA Natureza & Clima** (AI Nature & Climate Challenge), an initiative by **iCS (Instituto Clima e Sociedade)** to promote AI solutions that generate positive socio-environmental impact in Brazil.

| Partner | Role |
|---|---|
| **LAPIG** — Laboratório de Processamento de Imagens e Geoprocessamento | Proponent and scientific nucleus — geospatial data, pasture analysis, environmental monitoring |
| **UFG** — Universidade Federal de Goiás | Academic home of LAPIG — scientific and institutional rigor |
| **Solved** | Technology partner — bridging research into accessible, user-focused software |
| **iCS** — Instituto Clima e Sociedade | Funder — creator of the Desafio IA Natureza & Clima |
| **Google.org** | Philanthropic supporter — funding AI solutions for socio-environmental challenges |
| **ITS** — Instituto de Tecnologia e Sociedade | Technical guidance — best practices, governance, and ethical AI use |

---

## Goals

Pasto Legal aligns with the directives of the Desafio IA Natureza & Clima:

- 🌱 **Regenerative agriculture** — supporting sustainable pasture management and recovery
- 💰 **Bioeconomy strengthening** — enabling data-driven decisions for rural producers
- 🦜 **Biodiversity loss reversal** — monitoring and preserving native vegetation in Brazil
- 🌍 **GHG emission mitigation** — promoting resilient ecosystems that sequester carbon
- 🔓 **Open science** — free access to geospatial data, reports, and the source code itself

---

## Overview

Pasto Legal uses a **Host-Side [Tool-RAG](https://next.redhat.com/2025/11/26/tool-rag-the-next-breakthrough-in-scalable-ai-agents/#:~:text=Imagine%20this%3A%20you're%20building%20an%20AI%20assistant,only%20handle%20so%20much%20context%20at%20once.) Router** combined with **pi RPC** (JSON-RPC subprocess). Python owns everything: the WhatsApp webhook, tool selection via FAISS vector search, and all domain services (GEE, SICAR, TTS). pi runs as a local subprocess — zero Node.js code in the project.

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                          WhatsApp Cloud API                         │
└──────────────────────────────┬──────────────────────────────────────┘
                               │ webhook
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     fastapi_app  (Python :3000)                      │
│                                                                      │
│  ┌──────────────────┐   ┌──────────────┐   ┌──────────────────────┐ │
│  │  WhatsApp Router │   │  /tool endpoint│   │  /chat endpoint     │ │
│  │  - verify webhook│   │  - dispatches  │   │  (Streamlit debug)  │ │
│  │  - receive msgs  │   │   to agent/    │   │                     │ │
│  │  - send responses│   │   tools/*.py   │   │                     │ │
│  └────────┬─────────┘   └───────┬────────┘   └──────────┬──────────┘  │
│           │                     │                        │            │
│  ┌────────┴─────────────────────┴────────────────────────┴─────────┐  │
│  │                    Tool-RAG Router                               │ │
│  │                    (agent/tool_rag.py)                           │ │
│  │  Embeds tool schemas → FAISS index                               │ │
│  │  Cosine similarity search on user message + last 3 queries       │ │
│  │  Returns top-5 relevant tools → injected into pi prompt          │ │
│  └──────────────────────────────────────────────────────────────────┘ │
│                                                                       │
│  ┌──────────────────────────────────────────────────────────────────┐ │
│  │                    pi RPC subprocess                             │ │
│  │                    (one per user, spawned on demand)             │ │
│  │                                                                  │ │
│  │  pi --mode rpc --session /tmp/pi-sessions/{user}/session.jsonl   │ │
│  │       -e agent/extensions/pasto-legal-tools.js                   │ │
│  │                                                                  │ │
│  │  Session file on disk — pi manages context + compaction natively │ │
│  │  Only RAG-selected tools described in prompt (zero prompt bloat) │ │
│  └──────────────────────────────────────────────────────────────────┘ │
│                                                                       │
│  ┌──────────────────────────────────────────────────────────────────┐ │
│  │                        Shared Services                           │ │
│  │  ┌─────────────┐  ┌──────────┐  ┌───────┐  ┌──────────────────┐  │ │
│  │  │ Valkey/Redis│  │ Database │  │  GEE  │  │ SICAR + TTS +    │  │ │
│  │  │ (session    │  │ (SQLite/ │  │       │  │ Pasture Classif. │  │ │
│  │  │  state,     │  │  PG)     │  │       │  │                  │  │ │
│  │  │  debounce,  │  │          │  │       │  │                  │  │ │
│  │  │  recent     │  │          │  │       │  │                  │  │ │
│  │  │  queries)   │  │          │  │       │  │                  │  │ │
│  │  └─────────────┘  └──────────┘  └───────┘  └──────────────────┘  │ │
│  └──────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                      valkey  (Redis-compatible :6379)                │
│  - Message debouncing (5s window)                                    │
│  - Session state (properties, persona, terms_accepted)               │
│  - Recent queries for RAG context (last 3 per user)                  │
│  - PII hashing cache                                                 │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Message Flow

```
WhatsApp ──► fastapi_app/whatsapp/webhook
                │
                ├── PII guardrail check
                ├── Media download (images, audio, docs)
                ├── Message debouncing (Valkey, 5s)
                ├── Onboarding gate (Python — no LLM)
                │   !terms_accepted → pre-canned terms message
                │   user says "aceito" → accept_terms() → DB
                │
                ▼
            Tool-RAG Router (agent/tool_rag.py)
            Embeds [last 3 queries + current message] → FAISS cosine similarity
            Returns top-5 relevant tools from agent/registry.py
                │
                ▼
            build_prompt()
            RAG-selected tool descriptions + skill instructions + session state
                │
                ▼
            PiRpcPool.get_client(user_id)
            One pi process per user — session loaded from /tmp/pi-sessions/{user}/session.jsonl
                │
                ▼
            pi_rpc.prompt(full_prompt)  — JSON-RPC over stdin/stdout
                │
                ├── LLM processes message (only sees relevant tools)
                ├── LLM calls a tool → extension POST /tool → agent/tools/*.py
                ├── pi writes conversation to session file (native persistence)
                ├── Returns text + base64 images + audio paths
                │
                ▼
            Send to WhatsApp (text + images + audio)
```

---

## How It Works

### Host-Side Tool-RAG Router

Instead of loading all 19 tool descriptions into every LLM prompt, the Tool-RAG Router embeds all tool schemas into an in-memory FAISS index at startup. For each user message:

1. The current message **plus the last 3 user queries** (stored in Valkey) are concatenated for context
2. A cosine similarity search finds the top-5 most relevant tools
3. Only those 5 tool descriptions and their skill instructions are injected into the prompt
4. Tools like `accept_terms_and_conditions` and `consult_update_notes` are always available regardless of similarity score

This means the LLM sees a lean, focused prompt every time — not a wall of 19 tool descriptions.

### Tool/Skill Registry

All 19 tools are defined in a single file: `agent/registry.py`. Each entry has:

- **name** — the tool identifier (e.g., `register_property_by_car`)
- **description** — what the tool does (used for FAISS embedding)
- **category** — grouping (property, analysis, utility, onboarding)
- **skill** — optional skill instructions injected into the prompt when the tool is RAG-selected

The tool implementations live in `agent/tools/` (property.py, gee.py, tts.py, onboarding.py, version.py). The `/tool` endpoint dispatches to these files based on the action name.

### Isolated Sessions (one pi process per user)

Every user gets their own pi subprocess with its own session file at `/tmp/pi-sessions/{user_id}/session.jsonl`. pi manages the session natively:

- **Conversation history** — stored in the JSONL file, loaded when the process starts
- **Compaction** — pi summarizes old context when the window fills, preserving the compacted state in the file
- **Persistence** — the file survives process restarts and container restarts (Docker volume `pi-sessions`)
- **Isolation** — User A's conversation never touches User B's context

A `PiRpcPool` manages the lifecycle: spawn on first message, reuse for subsequent messages, stop after 30 minutes idle. A per-user `asyncio.Lock` prevents race conditions when two messages arrive simultaneously for the same user.

### Onboarding Gate

New users must accept the Terms of Use before using the system. This is handled entirely in Python — no LLM involved:

1. First message → `_get_session_state()` checks the database → `terms_accepted: false`
2. Python sends a pre-canned terms message directly to WhatsApp
3. User responds "aceito" → Python calls `accept_terms()` → writes to database
4. All subsequent messages → `terms_accepted: true` → normal LLM flow

---

## Main Advantages

- **Zero prompt bloat** — only 5 relevant tool descriptions per prompt, not 19
- **Deterministic tool selection** — same message + context → same FAISS results → same tools, every time
- **Fail-safe** — always-available tools included regardless of similarity; if RAG returns nothing, a fallback message is sent
- **Context-aware RAG** — last 3 user queries are included in the embedding, so the router doesn't lose the thread in medium-sized conversations
- **Native session management** — pi handles compaction, branching, and persistence. No custom mirror/restore code
- **Full isolation** — each user has a separate pi process and session file. No cross-user context leakage
- **Zero Node.js code** — pi is installed globally as a CLI tool. The project is 100% Python
- **Unified registry** — all tool names, descriptions, and skill instructions in one file (`agent/registry.py`)

---

## Possible Disadvantages

- **Memory per user** — each pi subprocess consumes ~50–100 MB of RAM. 100 concurrent users = ~5–10 GB. The 30-minute TTL helps, but bursts can be expensive
- **Cold start latency** — first message for a user spawns a new pi process (~2–5 seconds). Subsequent messages reuse the running process
- **FAISS index is in-memory** — rebuilt on every container restart. For 19 tools this is instant, but wouldn't scale to thousands of tools without a persistent index
- **No streaming to WhatsApp** — the full response is collected before sending. Users wait for the complete message instead of seeing it stream in
- **pi system prompt is not overridable in RPC mode** — pi's default coding-agent prompt is always present. Our instructions are injected via `AGENTS.md` and per-prompt context, but the LLM still sees both
- **Single container for everything** — if FastAPI restarts, all pi subprocesses die. Session files survive on the Docker volume, but users experience a cold start on their next message

---

## Docker Compose

```yaml
services:
  valkey:        # Redis-compatible, session state + debouncing + recent queries
  fastapi_app:   # Python + pi subprocesses, WhatsApp webhook + /tool + /chat, :3000
  streamlit_app: # Python, debug UI → calls FastAPI /chat, :8080

volumes:
  pi-sessions:   # /tmp/pi-sessions — survives container restarts
  valkey-data:   # /data — Valkey persistence (RDB + AOF)
```

---

## Getting Started

### Prerequisites

- **[uv](https://docs.astral.sh/uv/)** — fast Python package manager
- **Google Earth Engine** service account with access to MapBiomas collections
- **Redis / Valkey** (for WhatsApp message debouncing in production)

### Installation

```bash
git clone https://github.com/lapig-ufg/pasto-legal.git
cd pasto-legal
cp .env.example .env  # Fill in your credentials
docker compose up --build
```

### Key Environment Variables

| Variable | Description |
|---|---|
| `GOOGLE_API_KEY` | Google Gemini API key (mapped to `GEMINI_API_KEY` for pi) |
| `GEE_PROJECT` | Google Earth Engine project ID |
| `GEE_SERVICE_ACCOUNT` | GEE service account email |
| `GEE_KEY_FILE` | Path to GEE service account JSON key |
| `PI_PROVIDER` | pi RPC provider (default: `google`) |
| `PI_MODEL` | pi RPC model (default: `gemini-3.5-flash-lite`) |
| `PI_SESSION_TTL` | Idle pi process TTL in seconds (default: `1800`) |

> **Production also requires:** PostgreSQL connection vars, WhatsApp Business API credentials, and Redis/Valkey connection vars. See [`.env.example`](.env.example) for the full list.

---

## Project Structure

```
agent/                              # pi-related code (zero Node.js in project)
├── registry.py                     # All 19 tool/skill definitions (name, description, category, skill instructions)
├── tool_rag.py                     # FAISS index + fastembed + cosine similarity search
├── pi_rpc.py                       # PiRpcClient + PiRpcPool + build_prompt()
├── AGENTS.md                       # System prompt for pi (read from cwd)
├── extensions/
│   └── pasto-legal-tools.js        # JS extension — 19 custom tools, calls POST /tool
└── tools/                          # Tool implementations (called by /tool endpoint)
    ├── property.py                 # Property registration/removal
    ├── gee.py                      # GEE analysis + image generation
    ├── tts.py                      # TTS synthesis
    ├── onboarding.py               # Terms acceptance
    └── version.py                  # Changelog reader

api/                                # FastAPI application
├── main.py                         # FastAPI app + /tool + /chat endpoints + lifespan
├── configs/
│   ├── config.py                   # Settings
│   └── logging_config.py           # Logging
├── interfaces/
│   ├── whatsapp/
│   │   ├── router.py               # Webhook → onboarding gate → RAG → pi_rpc.prompt()
│   │   ├── helpers.py               # WhatsApp message sending
│   │   └── security.py              # Webhook signature validation
│   └── streamlit/
│       ├── streamlit_webapp.py      # Debug UI → FastAPI /chat HTTP call
│       ├── debug_panel.py           # Debug controls
│       └── debug_helpers.py         # Response parsing
├── database/
│   ├── session.py                   # SQLAlchemy session
│   └── models.py                    # UserTermsAcceptance model
├── guardrails/
│   └── pii_gate.py                  # PII detection + hashing
├── schemas/                         # Pydantic models
└── services/
    ├── audio/tts.py                 # TTS synthesis
    └── geospatial/
        ├── gee.py                   # Google Earth Engine
        ├── sicar.py                 # SICAR API client
        ├── pasture_classification.py
        ├── image.py                 # Map rendering
        └── pasture_cache.py         # Cache layer

DELETE_ME/                          # Unused files (old AGNO code, etc.)
```

---


## Documentation

- **[Technical architecture & workflow](docs/README.md)** — detailed agent roles, tools, and data flow
- **[Workflow diagrams](docs/workflow-diagrams.md)** — Mermaid diagrams of the orchestration
- **[Knowledge base](docs/knowledge/)** — reference material used by the Q&A agent (Portuguese)
- **[Release notes](docs/release_notes/)** — version history

---

## License

This project is licensed under the **GNU General Public License v3.0** — see the [LICENSE](LICENSE) file for details.

We encourage others to build upon this project and create their own solutions. If you do, you **must**:

1. **Keep it open** — any derivative work must be released under an open-source and/or open-science license (copyleft).
2. **Give credit** — clearly reference and attribute **Pasto Legal**, **LAPIG**, and **UFG** in your project, documentation, and any published outputs.

> **Note:** The "Pasto Legal" brand name, logo, and visual identity are owned by **UFG/LAPIG** and may not be reproduced without prior authorization. Geospatial data used in the platform comes from public sources (Copernicus/ESA) and is subject to their respective licenses.

---

## Contact

For questions, feature requests, or to exercise data protection rights, contact: **contact@pasto.legal**