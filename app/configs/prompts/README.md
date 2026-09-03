# Prompts — Customizing the System for Your Country / Language

This folder holds all the texts the AI agents show to users: agent
instructions/personas, tool descriptions and system hook messages. They live
in YAML files so the product can be adapted to a new country or language
**without touching any Python code**.

```
app/configs/prompts/
├── agents.yml        # Agent names, roles and instruction blocks  (localized)
├── tools.yml         # Tool descriptions shown to the LLM         (localized)
├── hooks.yml         # Validation-hook system messages            (localized)
└── defaults/         # ENGLISH reference versions of the three files
    ├── agents.yml
    ├── tools.yml
    └── hooks.yml
```

## How the files are loaded

At startup the loader (`app/configs/prompts.py`) reads each localized file
(`agents.yml`, `tools.yml`, `hooks.yml`) and merges it over the English
default in `defaults/`:

| Situation | Behavior |
|---|---|
| Localized file present and complete | Localized texts are used. No warnings. |
| Localized file missing entirely | English default used. One warning logged. |
| Key missing or blank inside a localized file | That part filled from the default. One warning per gap. |
| Key present in the localized file but unknown to the default | Ignored at runtime. Warning logged (likely a typo). |
| Neither file exists | Startup fails with `MissingPromptError`. |

Every warning is prefixed with `[prompts]` and names the exact key path, e.g.:

```
[prompts] agents.yml: key 'welcoming_agent.role' missing - falling back to English default
```

So a partially translated deployment still runs: anything you have not
translated yet simply falls back to English until you complete it. Watch the
logs after editing to catch typos and forgotten keys.

## Customizing for a new country/language

1. Start from the English files in `defaults/` — they document every text the
   system uses and are written to be understood by other countries.
2. Create your localized `agents.yml`, `tools.yml` and `hooks.yml` in this
   folder (they override the defaults) with **exactly the same structure and
   the same keys**.
3. Translate the values. Keep the keys and the YAML structure unchanged.
4. Restart the service and check the logs for `[prompts]` warnings.

The current repository ships `agents.yml`, `tools.yml` and `hooks.yml` in
Brazilian Portuguese — use them as a real-world example of a localized
deployment.

### What to translate vs. what to keep

Translate the free text (instructions, descriptions, messages). Keep as-is:

- **Placeholders** — `{candidate_text}`, `{options_text}`, `{terms_text}`,
  `{user_persona}`, `{satisfaction_level}`, `{last_message}`,
  `{negative_prompt}`, `{new_message}` are filled by the code at runtime.
  Never translate or rename them.
- **Escaped braces** — `{{level: str, level_message: str}}` in
  `satisfaction_agent.base_instructions` must keep the double braces.
- **Tool and function names** — identifiers like `confirm_car_selection`,
  `get_pasture_stats`, `search_knowledge_base`, `accept_terms_and_conditions`
  must stay in English; they refer to actual code.
- **URLs, e-mails and identifiers** — forms links, support e-mail, etc.
- **Technical terms of your domain** as appropriate (e.g. CAR, SICAR are
  Brazil-specific registries; adapt them to your country's equivalents when
  applicable).

### Agent-specific notes (`agents.yml`)

- `single_agent` has one instruction block per conversation state
  (`instructions_default`, `instructions_pending_single`,
  `instructions_pending_multiple`, `instructions_final`) plus small fallback
  strings. Translate each block as a whole, preserving the headings and the
  `>` blockquote line (dynamic content is injected after it).
- `welcoming_agent.instructions` contains `{terms_text}` — the full Terms of
  Use are injected into it. Keep the reference section header at the end and
  the `{terms_text}` placeholder on its own line.
- `persona_agent.instructions` and the `negative_prompt_*` templates describe
  the JSON-like output contract (e.g. `PersonaUpdate`, "Nível 1/Level 1")
  referenced by code and schemas — keep those tokens intact.
- `remediation_agent` requires the literal `[PAUSE]` tag (exactly twice) —
  it is parsed downstream; never translate it.
- `satisfaction_agent.base_instructions` output format
  (`{{level: str, level_message: str}}`) must match the response schema —
  keep the JSON example as-is.

### Tool notes (`tools.yml`)

- Grouped by tool file (component), then by function name, each with a
  `description` tag. Keys are the Python function names — do not rename them.
- The `params:` / `Args:` sections inside a description help the LLM call the
  tool correctly. Keep parameter names exactly as in the code; translate only
  the explanatory words.

### Hook notes (`hooks.yml`)

- `pre_hooks` messages replace the user's input to force a specific agent
  behavior (authorization, terms acceptance) — keep the imperative tone.
- `tool_hooks.media_integration_error` contains `{function_name}` and
  `{error}` placeholders filled at runtime.

## Quick checklist

- [ ] Same keys and hierarchy as the `defaults/` file you are overriding.
- [ ] All placeholders (`{...}`) untouched; `{{...}}` kept double.
- [ ] Tool names inside instruction texts untouched.
- [ ] `[PAUSE]` tag untouched (remediation flow).
- [ ] Service restarted and logs free of `[prompts]` warnings.

## Testing your changes

```bash
# Loader unit tests (fallback, merge, warnings)
.venv/bin/python -m pytest tests/configs -q

# Quick smoke: load everything with your files
.venv/bin/python -c "from app.configs.prompts import get_agent_config, \
get_tool_description, get_hook_texts; \
get_agent_config('single_agent'); \
get_tool_description('weather_tools', 'get_temperature_forecast'); \
get_hook_texts('pre_hooks'); print('OK')"
```

If a requested key is absent from both your file and the defaults, the loader
raises `MissingPromptError` — the log message tells you which key to add.