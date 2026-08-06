# 🌿 Pasto Legal

**AI-powered agricultural extension via WhatsApp** — delivering satellite-based pasture diagnostics, agronomic consultancy, and property management to rural producers in Brazil.

[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/) [![License: GPLv3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE) [![Status: Alpha](https://img.shields.io/badge/status-alpha-orange.svg)]()

---

## About

Pasto Legal is an open-science platform that brings advanced satellite analytics and agronomic expertise directly to farmers' phones through WhatsApp. Behind a simple chat interface, a team of specialized AI agents connects to official databases (SICAR — Brazil's Rural Environmental Registry) and global satellites (Google Earth Engine, MapBiomas) to transform complex geospatial data into fast answers, clear maps, and precise diagnostics for rural properties.

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

Pasto Legal is a WhatsApp-based AI assistant for Brazilian ranchers. It uses the **pi coding agent** via JSON-RPC (`--mode rpc`) as a local subprocess — **zero Node.js code in the project**. Python handles WhatsApp webhooks, domain services (GEE, SICAR, TTS), and tool execution.

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
│  │  WhatsApp Router  │   │  /tool endpoint│   │  /chat endpoint     │ │
│  │  - verify webhook │   │  - calls CLI   │   │  (Streamlit debug)  │ │
│  │  - receive msgs   │   │    scripts     │   │                      │ │
│  │  - send responses │   │                │   │                      │ │
│  └────────┬─────────┘   └───────┬────────┘   └──────────┬──────────┘ │
│           │                     │                        │           │
│  ┌────────┴─────────────────────┴────────────────────────┴─────────┐ │
│  │                        Shared Services                            │ │
│  │  ┌─────────────┐  ┌──────────┐  ┌───────┐  ┌──────────────────┐ │ │
│  │  │ Valkey/Redis │  │ Database │  │  GEE  │  │ SICAR + TTS +    │ │ │
│  │  │ (session    │  │ (SQLite/ │  │       │  │ Pasture Classif. │ │ │
│  │  │  state,     │  │  PG)     │  │       │  │                  │ │ │
│  │  │  debounce,  │  │          │  │       │  │                  │ │ │
│  │  │  history)   │  │          │  │       │  │                  │ │ │
│  │  └─────────────┘  └──────────┘  └───────┘  └──────────────────┘ │ │
│  └──────────────────────────────────────────────────────────────────┘ │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────────┐ │
│  │                    pi RPC subprocess                              │ │
│  │                    (one per user, spawned on demand)              │ │
│  │                                                                   │ │
│  │  pi --mode rpc --no-session --provider google --model ...         │ │
│  │       -e .pi/extensions/pasto-legal-tools.js                      │ │
│  │                                                                   │ │
│  │  ┌────────────┐  ┌──────────────┐  ┌─────────────────────────┐  │ │
│  │  │ AGENTS.md   │  │ 6 Skills     │  │ 19 Custom Tools          │  │ │
│  │  │ (system     │  │ (auto-       │  │ (extension:              │  │ │
│  │  │  prompt)    │  │  discovered  │  │  .pi/extensions/         │  │ │
│  │  │             │  │  from        │  │  pasto-legal-tools.js)   │  │ │
│  │  │             │  │  .pi/skills/) │  │                         │  │ │
│  │  └────────────┘  └──────────────┘  └──────────┬──────────────┘  │ │
│  │                                                │                 │ │
│  │  Tools call back to FastAPI via HTTP            │                 │ │
│  │  POST http://localhost:3000/tool                │                 │ │
│  └────────────────────────────────────────────────┘                 │ │
└──────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                      valkey  (Redis-compatible :6379)                │
│  - Message debouncing (5s window)                                    │
│  - Session state persistence                                         │
│  - pi session mirror (entries saved after each prompt)               │
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
                ├── Load session state (Valkey + DB)
                │   └── Check terms_accepted from DB
                │
                ▼
            Onboarding gate (Python)
            If !terms_accepted and user says "aceito" → accept directly
                │
                ▼
            PiRpcPool.get_client(user_id)
            One pi process per user, restored from Valkey if returning
                │
                ▼
            build_prompt()
            Session state + user message (system prompt via AGENTS.md)
                │
                ▼
            pi_rpc.prompt(full_prompt)
            JSON-RPC over stdin/stdout
                │
                ├── pi processes message with LLM
                ├── LLM may call custom tools
                │   └── Extension calls POST /tool on localhost:3000
                │       └── Python CLI scripts execute
                │           ├── cli/property.py
                │           ├── cli/gee.py
                │           ├── cli/tts.py
                │           ├── cli/onboarding.py
                │           └── cli/version.py
                ├── Returns text + base64 images + audio paths
                │
                ▼
            pi_rpc response
            { content, images[], audio[] }
                │
                ├── Mirror session to Valkey (get_entries)
                ├── Send text to WhatsApp
                ├── Upload images to WhatsApp Media API
                └── Upload audio to WhatsApp Media API
```

---

## Key Design Decisions

### JSON-RPC Subprocess (zero Node.js in project)

The pi coding agent is a Node.js CLI. Instead of embedding its SDK in a custom Express server, we run `pi --mode rpc` as a local subprocess and communicate via JSON-RPC over stdin/stdout. **Zero Node.js code in the Pasto Legal project.**

- pi is installed globally in the Docker image (`npm install -g @earendil-works/pi-coding-agent`)
- Python spawns pi on demand via `asyncio.create_subprocess_exec`
- All communication is JSON-Line protocol (one JSON object per line)
- `PiRpcPool` manages per-user pi processes with TTL-based cleanup (30 min idle)

### Per-User pi Processes (Option 2a)

Each user gets their own pi process with an in-memory session. pi manages conversation context and compaction. After each prompt, the session tree is mirrored to Valkey via `get_entries` for durability.

- **New user**: `--no-session` → fresh in-memory session
- **Returning user**: session entries loaded from Valkey → written to temp JSONL → `--session <file>` → pi restores full tree including compaction state
- **Cleanup**: idle processes saved to Valkey and terminated after 30 min TTL

### System Prompt via AGENTS.md

pi reads `AGENTS.md` from its working directory and includes it in the system prompt context. This gives our Pasto Legal instructions higher priority than user-message injection.

### Onboarding Gate (Terms of Service)

New users must accept terms before any interaction. Enforced at two levels:

1. **Python layer** (`router.py`): when `terms_accepted` is false and the user's message matches acceptance keywords (`sim`, `aceito`, `concordo`, etc.), calls `accept_terms()` directly — bypassing the LLM entirely
2. **LLM fallback**: the `accept_terms_and_conditions` tool is still available for edge cases

### Single Agent + Skills (replacing Multi-Agent)

AGNO used a router agent dispatching to 7 specialized agents. pi uses a **single agent** with **6 skills** auto-discovered from `.pi/skills/`:

| Skill | Purpose |
|-------|---------|
| `pasto-legal-analyst` | Pasture analysis, GEE stats, satellite imagery |
| `pasto-legal-manager` | Property registration, CRUD operations |
| `pasto-legal-faq` | Platform questions, data sources |
| `pasto-legal-onboarding` | Terms of service, first-access gate |
| `pasto-legal-smalltalk` | Greetings, casual conversation |
| `pasto-legal-feedback` | User satisfaction, issue reporting |

### Custom Tools (Extension)

19 custom tools defined in `.pi/extensions/pasto-legal-tools.js`. Each tool calls `POST /tool` on `localhost:3000` (same container). The extension is loaded explicitly via `-e` flag to bypass auto-discovery issues.

### Session State Management

| Concern | Storage | Accessed by |
|---------|---------|-------------|
| Conversation context + compaction | pi in-memory session | pi subprocess |
| Session durability (backup) | Valkey (`pi_session:{user_id}`) | PiRpcPool |
| User properties, registration state | Valkey (`session:{user_id}`) | Python CLI scripts + router |
| Terms acceptance | SQLite/PostgreSQL | Python DB layer |
| Message debouncing | Valkey | WhatsApp router |

---

## Docker Compose

```yaml
services:
  valkey:        # Redis-compatible, session state + debouncing + pi session mirror
  fastapi_app:   # Python + Node.js (pi), WhatsApp webhook + /tool + /chat, :3000
  streamlit_app: # Python, debug UI → calls FastAPI /chat, :8080
```

pi runs as a subprocess inside `fastapi_app` — no separate bridge container. Streamlit is a thin UI that calls FastAPI's `/chat` endpoint via HTTP.

---

## Comparison: AGNO → pi SDK bridge → pi RPC

| Aspect | AGNO | pi SDK bridge | pi RPC (current) |
|--------|------|---------------|-------------------|
| **Node.js code in project** | None | ~300 lines (bridge/) | **Zero** |
| **Agent model** | Router → 7 agents | Single agent + 6 skills | Single agent + 6 skills |
| **Communication** | Python in-process | HTTP (bridge:3001) | JSON-RPC stdin/stdout |
| **System prompt** | AGNO config | SDK override | AGENTS.md + per-prompt injection |
| **Session history** | AGNO sessions | pi SDK in-memory | pi in-memory + Valkey mirror |
| **Tool execution** | Python in-process | HTTP POST /tool | HTTP POST /tool (localhost) |
| **Deployment** | 3 containers | 4 containers | **3 containers** |
| **Onboarding gate** | Workflow step | System prompt + DB check | Python keyword match + LLM fallback |

## Getting Started

### Prerequisites

- **[uv](https://docs.astral.sh/uv/)** — fast Python package manager
- **Google Earth Engine** service account with access to MapBiomas collections
- **Redis / Valkey** (for WhatsApp message debouncing in production)

### Installation

```bash
# Clone the repository
git clone https://github.com/lapig-ufg/pasto-legal.git
cd pasto-legal
```

### Configuration

Copy the environment template and fill in your credentials:

```bash
cp .env.example .env
```

Key environment variables (see [`.env.example`](.env.example) for the full list):

| Variable | Description |
|---|---|
| `APP_ENV` | `development`, `staging`, or `production` |
| `DATABASE_TYPE` | `sqlite` (dev) or `postgres` (prod) |
| `GEE_PROJECT` | Google Earth Engine project ID |
| `GEE_SERVICE_ACCOUNT` | GEE service account email |
| `GEE_KEY_FILE` | Path to GEE service account JSON key |
| `MODEL_PROVIDER` | `google` (Gemini) or `ollama` (local) |
| `MODEL_ID` | Model identifier (default: `gemini-2.5-flash`) |
| `GOOGLE_API_KEY` | Google Gemini API key (mapped to `GEMINI_API_KEY` for pi) |
| `PI_PROVIDER` | pi RPC provider (default: `google`) |
| `PI_MODEL` | pi RPC model (default: `gemini-2.5-flash`) |
| `PI_SESSION_TTL` | Idle pi process TTL in seconds (default: `1800`) |

> **Production also requires:** PostgreSQL connection vars, WhatsApp Business API credentials (`WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_WEBHOOK_URL`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_APP_SECRET`), and Redis/Valkey connection vars.

### Running Locally (Docker)

```bash
docker compose up --build
```

---

## Project Structure

```
app/
├── main.py                          # FastAPI app + /tool + /chat endpoints
├── core/
│   └── pi_rpc.py                   # PiRpcClient + PiRpcPool + build_prompt()
├── configs/
│   ├── config.py                    # Settings
│   └── logging_config.py            # Logging
├── interfaces/
│   ├── whatsapp/
│   │   ├── router.py                # Webhook → pi_rpc.prompt()
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
├── schemas/                         # Pydantic models (unchanged)
├── services/
│   ├── audio/tts.py                 # TTS synthesis
│   └── geospatial/
│       ├── gee.py                   # Google Earth Engine
│       ├── sicar.py                 # SICAR API client
│       ├── pasture_classification.py # Pasture classification
│       ├── image.py                 # Map rendering
│       └── pasture_cache.py         # Cache layer
└── utils/

cli/                                 # Python tool wrappers (called by /tool endpoint)
├── property.py                      # Property registration/removal
├── gee.py                           # GEE analysis + image generation
├── tts.py                           # TTS synthesis
├── onboarding.py                    # Terms acceptance
└── version.py                       # Changelog reader

.pi/                                 # pi auto-discovery (zero Node.js code in project)
├── extensions/
│   └── pasto-legal-tools.js         # 19 custom tool definitions
└── skills/                          # Symlinks → ../../skills/*/

skills/                              # Skill SKILL.md files
├── pasto-legal-analyst/
├── pasto-legal-manager/
├── pasto-legal-faq/
├── pasto-legal-onboarding/
├── pasto-legal-smalltalk/
└── pasto-legal-feedback/

AGENTS.md                            # System prompt for pi (read from cwd)
dead_agno/                           # Original AGNO code (reference only)
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