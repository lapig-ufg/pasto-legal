"""
Unified tool & skill registry for Pasto Legal.

Each entry defines a tool's name, description, category, and skill instructions.
Used by ToolRAG for embedding + search, and by build_prompt() for skill injection.

Also re-exports action handlers from agent.tools.* for the /tool endpoint.
"""

# ── Tool/Skill definitions ────────────────────────────────────────────────

TOOLS = [
    # ═══ Property Registration ═══════════════════════════════════════════
    {
        "name": "register_property_by_car",
        "description": "Registra uma propriedade rural pelo código CAR/SICAR. Use quando o usuário fornecer um código CAR.",
        "category": "property",
        "skill": """
## Cadastro de Propriedade por CAR

Use esta skill quando o usuário quiser cadastrar uma propriedade rural fornecendo o código CAR (Cadastro Ambiental Rural).

### Processo
1. Valide o formato do código CAR (2 letras do estado + 7 números + 32 caracteres).
2. Chame a ferramenta `register_property_by_car` com o código CAR e o user_id.
3. Se a ferramenta retornar múltiplas propriedades, peça ao usuário para escolher uma.
4. Após a seleção, chame `confirm_property_selection` ou `select_property_from_list`.
5. Peça um nome para a propriedade e chame `complete_property_registration`.
""".strip(),
    },
    {
        "name": "register_property_by_coords",
        "description": "Registra uma propriedade rural/fazenda por coordenadas geográficas (latitude, longitude)",
        "category": "property",
    },
    {
        "name": "register_property_by_url",
        "description": "Registra uma propriedade rural/fazenda a partir de um link de compartilhamento do Google Maps",
        "category": "property",
    },
    {
        "name": "confirm_property_selection",
        "description": "Confirma a propriedade rural/fazenda selecionada quando há apenas uma opção",
        "category": "property",
    },
    {
        "name": "select_property_from_list",
        "description": "Seleciona uma propriedade rural/fazenda de uma lista de múltiplos resultados",
        "category": "property",
    },
    {
        "name": "complete_property_registration",
        "description": "Conclui o cadastro da propriedade rural/fazenda com o nome escolhido pelo usuário",
        "category": "property",
    },
    {
        "name": "cancel_property_registration",
        "description": "Cancela o processo de cadastro de propriedade rural/fazenda em andamento",
        "category": "property",
    },
    {
        "name": "remove_property",
        "description": "Remove uma propriedade rural/fazenda registrada do sistema",
        "category": "property",
    },
    {
        "name": "remove_all_properties",
        "description": "Remove todas as propriedades rural/fazendas registradas do sistema",
        "category": "property",
    },
    {
        "name": "set_property_name",
        "description": "Atualiza o nome de uma propriedade rural/fazenda já registrada no sistema",
        "category": "property",
    },
    # ═══ Pasture Analysis ════════════════════════════════════════════════
    {
        "name": "get_pasture_stats",
        "description": "Calcula a área de pastagem, biomassa ou matéria seca do pasto, vigor do pasto, idade do pasto e classes de uso da terra (floresta, agricultura, savana, vegetação natural, água, entre outros)",
        "category": "analysis",
        "skill": """
## Análise de Pastagens

Use esta skill quando o usuário solicitar análise de pastagens, biomassa, ou estatísticas de vegetação.

### Processo
1. Identifique a propriedade do usuário (código CAR).
2. Chame `get_pasture_stats` com o código CAR, ano e mês desejados.
3. Interprete os resultados: biomassa (matéria seca), NDVI, idade do pasto, classificação.
4. Se o usuário pedir imagens, chame `generate_biomass_image` ou `generate_property_image`.
""".strip(),
    },
    {
        "name": "get_topographic_stats",
        "description": "Calcula altitude/altimetria e declividade considerando relevo e topografia",
        "category": "analysis",
    },
    {
        "name": "generate_property_image",
        "description": "Gera mapa com imagem de satélite Sentinel-2 (RGB) com limite da propriedade",
        "category": "analysis",
    },
    {
        "name": "generate_biomass_image",
        "description": "Gera mapa de biomassa (matéria seca) para área de pastagem/pasto",
        "category": "analysis",
    },
    {
        "name": "generate_soil_texture_image",
        "description": "Gera um mapa de solo (textura de sol) com profundidade de 0-30cm",
        "category": "analysis",
    },
    {
        "name": "generate_pasture_classification_image",
        "description": "Gera o mapa das áreas de pastagem/paso para o ano de 2026",
        "category": "analysis",
    },
    # ═══ UA Calculator ═══════════════════════════════════════════════════
    {
        "name": "ua_calculator",
        "description": "Cálculo de Unidade Animal (UA) para estimativa de capacidade de suporte segundo a metodologia do LAPIG/UFG.",
        "category": "analysis",
        "skill": """
## Cálculo de UA (Unidade Animal)

Use esta skill quando precisar calcular a lotação ou capacidade de suporte animal.

### Fórmulas do Lapig
- *UA Total do Rebanho* = Peso Total do Rebanho (kg) / 450
- *Lotação Real (UA/ha)* = UA Total do Rebanho / Área da Pastagem (ha)
- *Capacidade Ideal (UA Ideal Total)* = Forragem Total Disponível (t MS/ano) / 8.2
- *Capacidade Ideal por Hectare* = Capacidade Ideal Total / Área da Pastagem (ha)

### Processo
1. Chame `get_pasture_stats` para obter a biomassa da propriedade.
2. Aplique as fórmulas do Lapig (1 UA = 450 kg, demanda = 8.2 t MS/UA/ano).
3. Explique o resultado de forma didática, mostrando os números na fórmula.
4. O fator 8.2 representa o dobro do consumo (2.5% do peso vivo) — 50% é perdido por pisoteio.
""".strip(),
    },
    # ═══ TTS ════════════════════════════════════════════════════════════
    {
        "name": "generate_speech",
        "description": "Gera áudio falado a partir de um texto. Use APENAS quando o usuário solicitar explicitamente uma resposta em áudio.",
        "category": "utility",
    },
    # ═══ Onboarding ═════════════════════════════════════════════════════
    {
        "name": "accept_terms_and_conditions",
        "description": "Registra a aceitação formal dos Termos de Uso do Pasto Legal pelo usuário. Chame quando o usuário concordar claramente com os termos (ex: 'aceito', 'sim', 'concordo').",
        "category": "onboarding",
        "skill": """
## Aceitação de Termos de Uso

Use esta skill quando o usuário concordar claramente com os Termos de Uso do Pasto Legal.

### Processo
1. Confirme que o usuário aceitou os termos (ex: "aceito", "sim", "concordo", "pode sim").
2. Chame a ferramenta `accept_terms_and_conditions` com o `user_id` da sessão.
3. A ferramenta registra a aceitação no banco de dados e retorna uma mensagem de sucesso.
4. Apresente-se brevemente e pergunte como pode ajudar o usuário.
""".strip(),
    },
    # ═══ Version ════════════════════════════════════════════════════════
    {
        "name": "consult_update_notes",
        "description": "Lê e retorna as notas de atualização (patch notes) do sistema Pasto Legal.",
        "category": "utility",
    },
]

# Tools always available regardless of RAG results.
# - consult_update_notes: low-cost utility, always hand for "what's new" queries.
# - generate_speech: obligatory every run so the model can synthesize audio
#   whenever the user requests a spoken reply, independent of RAG similarity.
ALWAYS_AVAILABLE = {
    "consult_update_notes",
    "generate_speech",
}

# Tools available ONLY during the first-time onboarding flow (terms acceptance).
# These are the only tools suggested to the LLM until the user accepts the terms.
ONBOARDING_TOOLS = {
    "accept_terms_and_conditions",
    "generate_speech",
}

# ── Action handler mapping (for /tool endpoint) ───────────────────────────

# Maps tool_name -> (module_name, action_name)
# The /tool endpoint uses this to dispatch to the correct handler.
# Modules are loaded lazily from agent.tools.*.
ACTION_MAP = {
    # property
    "register_by_car": ("property", "register_by_car"),
    "register_by_coords": ("property", "register_by_coords"),
    "register_by_url": ("property", "register_by_url"),
    "confirm_selection": ("property", "confirm_selection"),
    "select_from_list": ("property", "select_from_list"),
    "complete_registration": ("property", "complete_registration"),
    "cancel_registration": ("property", "cancel_registration"),
    "remove": ("property", "remove"),
    "remove_all": ("property", "remove_all"),
    "set_name": ("property", "set_name"),
    # gee
    "pasture_stats": ("gee", "pasture_stats"),
    "topographic_stats": ("gee", "topographic_stats"),
    "property_image": ("gee", "property_image"),
    "biomass_image": ("gee", "biomass_image"),
    "soil_texture_image": ("gee", "soil_texture_image"),
    "pasture_classification_image": ("gee", "pasture_classification_image"),
    # tts
    "generate_speech": ("tts", "generate_speech"),
    # onboarding
    "accept_terms": ("onboarding", "accept_terms"),
    # version
    "update_notes": ("version", "update_notes"),
}
