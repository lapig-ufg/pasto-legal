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

Pasto Legal is a WhatsApp-based AI assistant for Brazilian ranchers, providing pasture analysis, property registration, and rural insights. It originally used the **AGNO** framework (Python) for multi-agent orchestration. It now uses the **pi coding agent SDK** (Node.js) as the LLM orchestration layer, with Python retained exclusively for domain services (GEE, SICAR, TTS, database).

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
│  ┌──────────────────┐   ┌──────────────┐   ┌──────────────────────┐  │
│  │  WhatsApp Router  │   │  /tool endpoint│   │  Streamlit (debug)   │  │
│  │  - verify webhook │   │  - calls CLI   │   │  (separate service)  │  │
│  │  - receive msgs   │   │    scripts     │   │                      │  │
│  │  - send responses │   │                │   │                      │  │
│  └────────┬─────────┘   └───────┬────────┘   └──────────┬──────────┘  │
│           │                     │                        │            │
│  ┌────────┴─────────────────────┴────────────────────────┴──────────┐  │
│  │                        Shared Services                            │  │
│  │  ┌─────────────┐  ┌──────────┐  ┌───────┐  ┌──────────────────┐ │  │
│  │  │ Valkey/Redis │  │ Database │  │  GEE  │  │ SICAR + TTS +    │ │  │
│  │  │ (session    │  │ (SQLite/ │  │       │  │ Pasture Classif. │ │  │
│  │  │  state,     │  │  PG)     │  │       │  │                  │ │  │
│  │  │  debounce)  │  │          │  │       │  │                  │ │  │
│  │  └─────────────┘  └──────────┘  └───────┘  └──────────────────┘ │  │
│  └──────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────┬───────────────────────────────────┘
                                   │
                      HTTP POST /prompt
                      HTTP POST /reset
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      bridge  (Node.js :3001)                         │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐    │
│  │                    pi SDK Agent Session                        │    │
│  │                                                                │    │
│  │  ┌────────────┐  ┌──────────────┐  ┌─────────────────────┐   │    │
│  │  │ System      │  │ 6 Skills     │  │ 18 Custom Tools     │   │    │
│  │  │ Prompt      │  │ (auto-       │  │ (extension:          │   │    │
│  │  │ (Portuguese, │  │  discovered │  │  pasto-legal-tools)  │   │    │
│  │  │  onboarding  │  │  from        │  │                     │   │    │
│  │  │  gate,       │  │  .pi/skills/) │  │  Property:          │   │    │
│  │  │  WhatsApp    │  │              │  │  register_by_car    │   │    │
│  │  │  rules)      │  │  analyst     │  │  register_by_coords │   │    │
│  │  │              │  │  manager     │  │  register_by_url    │   │    │
│  │  │              │  │  faq         │  │  confirm_selection  │   │    │
│  │  │              │  │  onboarding  │  │  select_from_list   │   │    │
│  │  │              │  │  smalltalk   │  │  complete_registr.  │   │    │
│  │  │              │  │  feedback    │  │  cancel_registration│   │    │
│  │  │              │  │              │  │  remove / remove_all │   │    │
│  │  │              │  │              │  │  set_name            │   │    │
│  │  │              │  │              │  │                     │   │    │
│  │  │              │  │              │  │  GEE:               │   │    │
│  │  │              │  │              │  │  pasture_stats       │   │    │
│  │  │              │  │              │  │  topographic_stats   │   │    │
│  │  │              │  │              │  │  property_image      │   │    │
│  │  │              │  │              │  │  biomass_image       │   │    │
│  │  │              │  │              │  │  soil_texture_image  │   │    │
│  │  │              │  │              │  │  pasture_classif.    │   │    │
│  │  │              │  │              │  │                     │   │    │
│  │  │              │  │              │  │  Other:             │   │    │
│  │  │              │  │              │  │  generate_speech     │   │    │
│  │  │              │  │              │  │  accept_terms        │   │    │
│  │  │              │  │              │  │  consult_update_notes│   │    │
│  │  └────────────┘  └──────────────┘  └──────────┬──────────┘   │    │
│  │                                                │               │    │
│  │  ┌─────────────────────────────────────────────┘               │    │
│  │  │  Tool execution: HTTP POST to fastapi_app:3000/tool         │    │
│  │  └─────────────────────────────────────────────────────────────┘    │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                                                      │
│  Model: google/gemini-2.5-flash (via ModelRuntime)                  │
│  Sessions: in-memory Map (30min TTL, per user_id)                   │
└──────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                      valkey  (Redis-compatible :6379)                │
│  - Message debouncing (5s window)                                    │
│  - Session state persistence                                         │
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
            bridge /prompt
            { userId, message, sessionState }
                │
                ├── pi SDK session (created or reused per user)
                │   ├── System prompt + session-state context
                │   ├── LLM processes message
                │   ├── Calls tools (via HTTP POST to /tool)
                │   │   └── Python CLI scripts execute
                │   │       ├── cli/property.py
                │   │       ├── cli/gee.py
                │   │       ├── cli/tts.py
                │   │       ├── cli/onboarding.py
                │   │       └── cli/version.py
                │   └── Returns text + images + audio paths
                │
                ▼
            bridge response
            { content, images[], audio[] }
                │
                ├── Send text to WhatsApp
                ├── Upload images to WhatsApp Media API
                ├── Upload audio to WhatsApp Media API
                └── Update session state (Valkey)
```

---

## Key Design Decisions

### Bridge Pattern (Node.js ↔ Python)

The pi SDK is a Node.js library. The WhatsApp webhook and all domain services (GEE, SICAR, TTS, database) are Python. Rather than rewriting Python services in TypeScript, we use a **bridge**:

- **Node.js bridge** manages LLM sessions, skills, and tool orchestration via the pi SDK
- **Python FastAPI** handles WhatsApp webhook, media, PII guardrails, and tool execution
- The bridge calls Python via `HTTP POST /tool` when the LLM invokes a tool
- CLI scripts (`cli/*.py`) are thin wrappers around the Python services, receiving base64-encoded JSON args and returning JSON on stdout

### Single Agent + Skills (replacing Multi-Agent)

AGNO used a **router agent** that dispatched to specialized agents (analyst, manager, FAQ, small talk, etc.). pi uses a **single agent** with **6 skills** that are auto-loaded when the task matches:

| Skill | Replaces |
|-------|----------|
| `pasto-legal-analyst` | analyst_agent + property_analyst_tools |
| `pasto-legal-manager` | manager_agent + property_crud_tools |
| `pasto-legal-faq` | question_answer_agent |
| `pasto-legal-onboarding` | welcoming_agent + accept_terms |
| `pasto-legal-smalltalk` | small_talk_agents |
| `pasto-legal-feedback` | feedback_agent + feedback_tools |

Skills are discovered from `.pi/skills/` — a standard pi location. In Docker, the Dockerfile copies `bridge/skills/*` → `.pi/skills/`.

### Onboarding Gate (Terms of Service)

New users must accept terms before any interaction. This is enforced at two levels:

1. **Python layer** (`router.py`): `_get_session_state()` queries `user_terms_acceptance` from the database and includes `terms_accepted: true/false` in the session state sent to the bridge
2. **System prompt**: instructs the LLM to refuse all requests and present the terms when `terms_accepted` is false, and only call `accept_terms_and_conditions` after explicit user consent

This replaces the AGNO `_needs_onboarding` workflow step that blocked all other agents until terms were accepted.

### Session State Management

| Concern | Storage | Accessed by |
|---------|---------|-------------|
| Conversation history | pi SDK in-memory session | Bridge |
| User properties, registration state | Valkey (Redis) | Python CLI scripts + router |
| Terms acceptance | SQLite/PostgreSQL | Python DB layer |
| Message debouncing | Valkey | WhatsApp router |

The bridge receives `sessionState` in each `/prompt` call (from `_get_session_state()`). The system prompt instructs the LLM to use this context for personalization. Tool results can also return `sessionState` updates, which the Python layer persists to Valkey.

---

## Docker Compose

```yaml
services:
  valkey:        # Redis-compatible, session state + debouncing
  bridge:        # Node.js, pi SDK, :3001
  fastapi_app:   # Python, WhatsApp webhook + /tool, :3000
  streamlit_app: # Python, debug UI, :8080
```

All services share the `pasto-legal` Docker network. Internal communication uses service names (`bridge:3001`, `fastapi_app:3000`, `valkey:6379`).

---

## Key Differences from AGNO

| Aspect | AGNO (before) | pi SDK (after) |
|--------|---------------|----------------|
| **Language** | Python only | Node.js (LLM) + Python (services) |
| **Agent model** | Router → 7 specialized agents | Single agent + 6 skills |
| **Session mgmt** | AGNO session objects | pi `createAgentSession` + in-memory Map |
| **Tool execution** | Python in-process | HTTP POST to FastAPI `/tool` |
| **Onboarding gate** | Workflow step `_needs_onboarding` | System prompt + DB check |
| **Skills** | Agent prompts hardcoded in Python | SKILL.md files auto-discovered from `.pi/skills/` |
| **Model routing** | AGNO model config | pi `ModelRuntime` with explicit model selection |
| **State** | AGNO workflow state | Valkey (session) + SQLite (terms) |
| **Image/audio** | AGNO media objects | File paths (bridge → FastAPI → WhatsApp upload) |

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
| `MODEL_ID` | Model identifier (default: `gemini-3.1-flash-lite`) |
| `GOOGLE_API_KEY` | Google Gemini API key |

> **Production also requires:** PostgreSQL connection vars, WhatsApp Business API credentials (`WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_WEBHOOK_URL`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_APP_SECRET`), and Redis/Valkey connection vars.

### Running Locally (Docker)

```bash
docker compose up --build
```

---

## Project Structure

```
app/
├── main.py                          # FastAPI app + /tool endpoint
├── configs/
│   ├── config.py                    # Settings (AGNO removed)
│   └── logging_config.py            # Logging (AGNO removed)
├── interfaces/
│   ├── whatsapp/
│   │   ├── router.py                # Webhook → bridge HTTP call
│   │   ├── helpers.py               # WhatsApp message sending (AGNO removed)
│   │   └── security.py              # Webhook signature validation
│   └── streamlit/
│       ├── streamlit_webapp.py      # Debug UI → bridge HTTP call
│       ├── debug_panel.py           # Debug controls
│       └── debug_helpers.py         # Bridge HTTP helpers
├── database/
│   ├── session.py                   # SQLAlchemy session
│   └── models.py                    # UserTermsAcceptance model
├── guardrails/
│   └── pii_gate.py                  # PII detection + hashing
├── schemas/                         # Pydantic models (unchanged)
├── services/
│   ├── audio/tts.py                 # TTS synthesis (AGNO removed)
│   └── geospatial/
│       ├── gee.py                   # Google Earth Engine (AGNO removed)
│       ├── sicar.py                 # SICAR API client (AGNO removed)
│       ├── pasture_classification.py # Pasture classification (AGNO removed)
│       ├── image.py                 # Map rendering
│       └── pasture_cache.py         # Cache layer
└── utils/

cli/                                 # Thin wrappers for bridge tool calls
├── property.py                      # Property registration/removal
├── gee.py                           # GEE analysis + image generation
├── tts.py                           # TTS synthesis
├── onboarding.py                    # Terms acceptance
└── version.py                       # Changelog reader

bridge/                              # Node.js pi SDK bridge
├── server.mjs                       # Express server + pi session management
├── package.json                     # Dependencies (pi-coding-agent, express)
├── extensions/
│   └── pasto-legal-tools.mjs        # 18 custom tool definitions
├── skills/                          # Skill SKILL.md files
│   ├── pasto-legal-analyst/
│   ├── pasto-legal-manager/
│   ├── pasto-legal-faq/
│   ├── pasto-legal-onboarding/
│   ├── pasto-legal-smalltalk/
│   └── pasto-legal-feedback/
└── .pi/skills/                      # Symlinks for local dev (auto-discovery)

docker/
└── Dockerfile.bridge                # Node.js bridge container
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