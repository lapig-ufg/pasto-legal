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
    # ═══ Feedback ═════════════════════════════════════════════════════
    {
        "name": "request_feedback",
        "description": "Ativa o modo de aguardo de feedback do usuário. Chame APENAS após entregar uma resposta reformulada (remediação) por frustração do usuário.",
        "category": "feedback",
        "skill": """
## Coleta de Feedback — Remediação de Frustração

Use esta skill quando o usuário demonstrar **frustração, insatisfação ou decepção** com a resposta anterior.

### Gatilhos comuns de frustração (não exaustivo)
- "Não gostei da resposta", "isso está errado", "não ajudou", "péssimo",
  "que resposta ruim", "não foi isso que eu perguntei", "idiota",
  "inútil", "vou desistir", ou similar.
- Tom agressivo, ironia, ou negação direta da utilidade da resposta.

### Processo de Remediação (uma única chamada)
1. Peça desculpas de forma breve e humanizada (sem soar robótico).
2. Gere uma NOVA resposta melhorada, considerando o que o usuário
   realmente queria. Use o histórico da conversa (já na sua sessão)
   para inferir a intenção original.
3. Ao final da mensagem, pergunte diretamente:
   "Ficou melhor? Responda SIM ou NÃO."
4. Chame a ferramenta `request_feedback` com o `user_id` da sessão
   para ativar o modo de aguardo de feedback.
5. NÃO repita a resposta anterior nem a reformule de forma vaga.
   Seja concreto e tente resolver o que deu errado.

### Regras
- Se o usuário NÃO demonstrar frustração, NÃO chame esta ferramenta.
- Use APENAS uma vez por ciclo de remediação.
- Após `request_feedback`, a próxima mensagem do usuário será
  classificada por você (positiva/negativa) — veja a skill
  `save_feedback` para o próximo passo.
""".strip(),
    },
    {
        "name": "save_feedback",
        "description": "Registra o feedback do usuário (positivo ou negativo) sobre a resposta reformulada e encerra o modo de feedback.",
        "category": "feedback",
        "skill": """
## Coleta de Feedback — Registro da Avaliação

Use esta skill quando o `<feedback-mode>` da sessão estiver
`awaiting_rating`. O usuário está respondendo à sua pergunta
"Ficou melhor? Responda SIM ou NÃO."

### Processo
1. Classifique a resposta do usuário:
   - **POSITIVE** se disser "sim", "melhorou", "ficou melhor",
     "agora sim", "obrigado", "ajudou", "perfeito", "é isso",
     ou similar (afirmação ou gratidão).
   - **NEGATIVE** se disser "não", "piorou", "continua ruim",
     "ainda não", "não ajudou", "péssimo", "continua errado",
     ou similar (negação ou crítica).
2. Se POSITIVE:
   - Agradeça brevemente.
   - Chame `save_feedback` com `verdict="positive"`,
     `user_message` (a mensagem do usuário),
     `assistant_response` (a resposta reformulada que foi avaliada),
     e `reason` (opcional: justificativa curta).
3. Se NEGATIVE:
   - Peça desculpas novamente de forma breve e humanizada.
   - Chame `save_feedback` com `verdict="negative"`,
     `user_message`, `assistant_response`, `reason`.
4. Após chamar `save_feedback`, prossiga normalmente: se o usuário
   fez uma nova pergunta, responda-a como de costume.

### Regras
- Classifique pelo tom e palavras-chave, não pelo conteúdo literal.
- Em caso de ambiguidade, considere o contexto da conversa.
- APENAS uma chamada a `save_feedback` por ciclo. Após isso, o modo
  de feedback é encerrado e o fluxo volta ao normal.
        """.strip(),
    },
    # ═══ Alert Schedulers (benchmark — mocked) ═══════════════════════════
    # Mocked alert-scheduler tools used to grow the tool registry for the
    # single-agent benchmark (see BENCHMARK.md). Each alert type exposes a
    # `request_*` (plans the scheduler, asks for confirmation) and a
    # `confirm_*` (registers the scheduler when the user says yes). The
    # two-step confirm flow mirrors request_feedback / save_feedback and the
    # property registration flow. All actions are handled by the Python
    # `benchmark` tool (agent/tools/benchmark.py), which returns canned JSON
    # without hitting any real backend.
    {
        "name": "request_biomass_alert",
        "description": "Planeja um alerta via WhatsApp que dispara quando a biomassa (matéria seca, kg/ha) atinge uma condição definida por operador lógico (gt, lt, le, ge, eq, neq) e um valor de referência. Retorna o plano e pede confirmação.",
        "category": "alert",
        "skill": """
## Alerta de Biomassa — Planejamento

Use esta skill quando o usuário quiser ser avisado no WhatsApp quando a biomassa
(matéria seca) do pasto atingir um certo nível.

### Processo
1. Identifique o operador lógico desejado a partir da fala do usuário:
   - "maior que" / "acima de" / "no mínimo" → `gt` (ou `ge` se "no mínimo" for inclusivo)
   - "menor que" / "abaixo de" / "no máximo" → `lt` (ou `le` se "no máximo" for inclusivo)
   - "igual a" / "exatamente" → `eq`
   - "diferente de" / "não for" → `neq`
2. Identifique o valor de referência (threshold) em kg/ha.
3. Chame `request_biomass_alert` com `operator`, `threshold` e `user_id`.
4. A ferramenta retorna um plano em linguagem natural pedindo confirmação.
5. NÃO cadastre o alerta ainda — aguarde o usuário confirmar.
6. Quando o usuário disser "sim", "pode sim", "confirma", "isso mesmo",
   chame `confirm_biomass_alert` com o `user_id`.
7. Se o usuário disser "não", "cancela", "espera", NÃO chame a ferramenta
   de confirmação — ajuste o plano ou desista.

### Regras
- Use APENAS uma chamada a `request_biomass_alert` por alerta planejado.
- O `confirm_biomass_alert` deve ser chamado apenas após confirmação explícita.
""".strip(),
    },
    {
        "name": "confirm_biomass_alert",
        "description": "Confirma o cadastro do alerta de biomassa planejado. Chame APENAS quando o usuário concordar com o plano apresentado por request_biomass_alert (ex: 'sim', 'pode sim', 'confirma').",
        "category": "alert",
        "skill": """
## Alerta de Biomassa — Confirmação

Use esta skill quando o usuário já recebeu o plano de alerta de biomassa (via
`request_biomass_alert`) e respondeu afirmativamente.

### Processo
1. Classifique a resposta do usuário:
   - POSITIVA: "sim", "pode sim", "confirma", "isso mesmo", "pode criar",
     "bom", "perfeito", "fez" → chame `confirm_biomass_alert` com `user_id`.
   - NEGATIVA: "não", "cancela", "espera", "deixa pra lá", "ainda não",
     "muda" → NÃO chame a confirmação. Ajuste o plano ou desista.
2. Após `confirm_biomass_alert`, o alerta está cadastrado (mockado) e o
   fluxo volta ao normal.

### Regras
- APENAS uma chamada a `confirm_biomass_alert` por alerta.
- Se não houver alerta de biomassa pendente, a ferramenta avisa e não faz nada.
""".strip(),
    },
    {
        "name": "request_rain_alert",
        "description": "Planeja um alerta via WhatsApp que dispara quando a chuva acumulada (mm) em uma janela de dias atinge uma condição definida por operador lógico (gt, lt, le, ge, eq, neq) e um valor de referência. Retorna o plano e pede confirmação.",
        "category": "alert",
        "skill": """
## Alerta de Chuva — Planejamento

Use esta skill quando o usuário quiser ser avisado no WhatsApp quando a chuva
acumulada atingir um certo nível em uma janela de dias.

### Processo
1. Identifique o operador lógico a partir da fala do usuário (mesmo mapeamento
   do alerta de biomassa: gt, lt, le, ge, eq, neq).
2. Identifique o valor de referência (threshold) em mm e, se mencionada,
   a janela de acumulação em dias (default: 7 dias).
3. Chame `request_rain_alert` com `operator`, `threshold`, `window_days`
   (opcional) e `user_id`.
4. A ferramenta retorna o plano pedindo confirmação.
5. Aguarde confirmação explícita do usuário antes de chamar `confirm_rain_alert`.

### Regras
- Use APENAS uma chamada a `request_rain_alert` por alerta planejado.
""".strip(),
    },
    {
        "name": "confirm_rain_alert",
        "description": "Confirma o cadastro do alerta de chuva planejado. Chame APENAS quando o usuário concordar com o plano apresentado por request_rain_alert (ex: 'sim', 'pode sim', 'confirma').",
        "category": "alert",
        "skill": """
## Alerta de Chuva — Confirmação

Use esta skill quando o usuário já recebeu o plano de alerta de chuva (via
`request_rain_alert`) e respondeu afirmativamente.

### Processo
1. Classifique a resposta do usuário (positiva vs negativa) — mesmo critério
   do `confirm_biomass_alert`.
2. Se positiva, chame `confirm_rain_alert` com `user_id`.
3. Se negativa, NÃO chame a confirmação.

### Regras
- APENAS uma chamada a `confirm_rain_alert` por alerta.
""".strip(),
    },
    {
        "name": "request_vigor_alert",
        "description": "Planeja um alerta via WhatsApp que dispara quando o vigor vegetativo (NDVI) da pastagem atinge uma condição definida por operador lógico (gt, lt, le, ge, eq, neq) e um valor de referência. Útil para detectar degradação do pasto. Retorna o plano e pede confirmação.",
        "category": "alert",
        "skill": """
## Alerta de Vigor (NDVI) — Planejamento

Use esta skill quando o usuário quiser ser avisado no WhatsApp quando o vigor
vegetativo (NDVI) da pastagem atingir um certo nível — geralmente uma queda
abaixo de um limite, indicando degradação ou seca.

### Processo
1. Identifique o operador lógico a partir da fala do usuário. Para "queda",
   "caindo", "abaixando", "degradando", use `lt` (menor que). Outros
   operadores (gt, le, ge, eq, neq) seguem o mesmo mapeamento das demais.
2. Identifique o valor de referência do NDVI (0 a 1, ex: 0.4).
3. Chame `request_vigor_alert` com `operator`, `threshold` e `user_id`.
4. A ferramenta retorna o plano pedindo confirmação.
5. Aguarde confirmação explícita do usuário antes de chamar `confirm_vigor_alert`.

### Regras
- Use APENAS uma chamada a `request_vigor_alert` por alerta planejado.
""".strip(),
    },
    {
        "name": "confirm_vigor_alert",
        "description": "Confirma o cadastro do alerta de vigor (NDVI) planejado. Chame APENAS quando o usuário concordar com o plano apresentado por request_vigor_alert (ex: 'sim', 'pode sim', 'confirma').",
        "category": "alert",
        "skill": """
## Alerta de Vigor (NDVI) — Confirmação

Use esta skill quando o usuário já recebeu o plano de alerta de vigor (via
`request_vigor_alert`) e respondeu afirmativamente.

### Processo
1. Classifique a resposta do usuário (positiva vs negativa) — mesmo critério
   do `confirm_biomass_alert`.
2. Se positiva, chame `confirm_vigor_alert` com `user_id`.
3. Se negativa, NÃO chame a confirmação.

### Regras
- APENAS uma chamada a `confirm_vigor_alert` por alerta.
""".strip(),
    },
    {
        "name": "request_stocking_rate_alert",
        "description": "Planeja um alerta via WhatsApp que dispara quando a lotação animal (UA/ha) ultrapassa ou atinge uma condição definida por operador lógico (gt, lt, le, ge, eq, neq) e um valor de referência. Útil para evitar superlotação além da capacidade de suporte. Retorna o plano e pede confirmação.",
        "category": "alert",
        "skill": """
## Alerta de Lotação (UA/ha) — Planejamento

Use esta skill quando o usuário quiser ser avisado no WhatsApp quando a lotação
animal (UA/ha) ultrapassar a capacidade de suporte ou atingir um certo nível.

### Processo
1. Identifique o operador lógico a partir da fala do usuário. Para "ultrapassa",
   "passa de", "acima de", "excede", use `gt` (ou `ge` se inclusivo). Outros
   operadores (lt, le, eq, neq) seguem o mesmo mapeamento das demais.
2. Identifique o valor de referência em UA/ha (ex: 2.5).
3. Chame `request_stocking_rate_alert` com `operator`, `threshold` e `user_id`.
4. A ferramenta retorna o plano pedindo confirmação.
5. Aguarde confirmação explícita do usuário antes de chamar
   `confirm_stocking_rate_alert`.

### Regras
- Use APENAS uma chamada a `request_stocking_rate_alert` por alerta planejado.
""".strip(),
    },
    {
        "name": "confirm_stocking_rate_alert",
        "description": "Confirma o cadastro do alerta de lotação (UA/ha) planejado. Chame APENAS quando o usuário concordar com o plano apresentado por request_stocking_rate_alert (ex: 'sim', 'pode sim', 'confirma').",
        "category": "alert",
        "skill": """
## Alerta de Lotação (UA/ha) — Confirmação

Use esta skill quando o usuário já recebeu o plano de alerta de lotação (via
`request_stocking_rate_alert`) e respondeu afirmativamente.

### Processo
1. Classifique a resposta do usuário (positiva vs negativa) — mesmo critério
   do `confirm_biomass_alert`.
2. Se positiva, chame `confirm_stocking_rate_alert` com `user_id`.
3. Se negativa, NÃO chame a confirmação.

### Regras
- APENAS uma chamada a `confirm_stocking_rate_alert` por alerta.
""".strip(),
    },
    # ═══ Scheduler management (benchmark — mocked) ═══════════════════════
    # Mocked list/delete tools that operate on a fixed in-memory list of
    # already-registered alert schedulers (MOCKED_SCHEDULERS in benchmark.py).
    # `list_schedulers` carries the "update a scheduler" skill — the full
    # list + delete + request permission + create + confirm flow.
    {
        "name": "list_schedulers",
        "description": "Lista os agendamentos de alerta já cadastrados (nome e condição de cada um). Use quando o usuário quiser revisar, listar, atualizar ou modificar seus agendamentos de alerta.",
        "category": "alert",
        "skill": """
## Agendamentos de Alerta — Listar e Atualizar

Use esta skill quando o usuário quiser **listar, revisar, atualizar ou
modificar** seus agendamentos de alerta existentes.

### Listar
1. Chame `list_schedulers` com o `user_id` da sessão.
2. A ferramenta retorna a lista numerada de agendamentos ativos
   (nome + condição de cada um).
3. Apresente a lista ao usuário em linguagem natural, numerada.

### Atualizar um agendamento
Quando o usuário quiser **atualizar/modificar** um agendamento existente,
siga exatamente esta sequência:

1. Chame `list_schedulers` e mostre a lista numerada (se ainda não listou).
2. Pergunte qual agendamento ele quer atualizar (por nome ou pelo número
   da lista).
3. Chame `delete_scheduler` para remover o agendamento antigo:
   - Passe `name` (nome exato) OU `number` (número da lista, 1-indexado).
   - Use APENAS um dos dois — nunca os dois juntos.
4. Peça ao usuário a **nova condição** que deseja (tipo de alerta, operador,
   valor de referência, janela de dias para chuva, propriedade).
5. **Peça permissão explícita** antes de criar o novo agendamento.
   Apresente o plano em linguagem natural e pergunte algo como:
   "Posso criar esse novo alerta? Responda SIM para confirmar."
   - NÃO chame nenhuma ferramenta de `request_*` antes da permissão.
   - Se o usuário disser "não", "cancela", "espera", NÃO crie o novo
     agendamento — o antigo já foi removido; ofereça recriar o antigo
     ou ajustar o plano.
6. Após permissão, chame a ferramenta `request_*` correspondente ao tipo
   de alerta desejado com os novos parâmetros:
   - biomassa        → `request_biomass_alert`    (operator, threshold, car_codes, user_id)
   - chuva acumulada → `request_rain_alert`       (operator, threshold, window_days, car_codes, user_id)
   - vigor (NDVI)    → `request_vigor_alert`     (operator, threshold, car_codes, user_id)
   - lotação (UA/ha) → `request_stocking_rate_alert` (operator, threshold, car_codes, user_id)
7. O `request_*` retorna o plano e pede confirmação. Aguarde o usuário
   responder ("sim", "pode sim", "confirma", "isso mesmo").
8. Quando o usuário confirmar explicitamente, chame a ferramenta
   `confirm_*` correspondente ao **mesmo tipo** do `request_*` que você
   acabou de chamar (ex: se chamou `request_biomass_alert`, chame
   `confirm_biomass_alert`).
9. Após o `confirm_*`, o novo agendamento está cadastrado (mockado) e o
   fluxo volta ao normal.

### Regras
- Sempre chame `list_schedulers` antes de remover/atualizar, para mostrar
  ao usuário o que existe.
- Use APENAS uma chamada a `delete_scheduler` por atualização.
- Nunca chame `request_*` sem permissão explícita do usuário.
- O `confirm_*` deve corresponder ao tipo do `request_*` chamado.
- Se o usuário quiser apenas listar (sem atualizar), não chame `delete_scheduler`.
- Se o usuário cancelar a atualização após o `delete_scheduler`, ofereça
  recriar o agendamento antigo — não deixe o usuário sem o alerta que tinha.
""".strip(),
    },
    {
        "name": "delete_scheduler",
        "description": "Remove um agendamento de alerta já cadastrado. Forneça `name` (nome exato do agendamento) OU `number` (número do agendamento na lista retornada por list_schedulers, começando em 1). Use APENAS um dos dois.",
        "category": "alert",
    },
    # ═══ Weather (benchmark — mocked) ═════════════════════════════════════
    # weather-benchmark: read-only mocked weather/rain data tools. All return
    # canned JSON tables (max 5 attributes per row) without hitting any
    # backend. Grouped under category "weather" so they can be removed in one
    # sweep (see BENCHMARK.md §8). Skill-less (read-only data retrieval, no
    # confirm flow) — they exercise Tool-RAG disambiguation between similarly
    # named weather concepts.
    {
        "name": "get_rain_forecast_15_days",
        "description": "Retorna a previsão de chuva para os próximos 15 dias em forma de tabela (data, precipitação mm, máximo, mínimo, probabilidade %). Use quando o usuário quiser saber a previsão de chuva das próximas duas semanas.",
        "category": "weather",
    },
    {
        "name": "get_rain_forecast_months",
        "description": "Retorna a previsão de chuva mensal para 1 a 3 meses à frente em forma de tabela (mês, precipitação mm, máximo, mínimo, probabilidade %). Use quando o usuário quiser saber a previsão de chuva para os próximos meses (máximo 3).",
        "category": "weather",
    },
    {
        "name": "get_rain_history",
        "description": "Retorna o histórico de chuva diário de um mês passado específico em forma de tabela (data, precipitação mm, máximo, mínimo, probabilidade %). Use quando o usuário quiser saber quanto choveu em um mês anterior (ex: 'quanto choveu em março do ano passado?').",
        "category": "weather",
    },
    {
        "name": "get_weather_today",
        "description": "Retorna as condições climáticas atuais (hoje): precipitação, temperatura, umidade e condição (ensolarado, nublado, chuva leve/forte). Use quando o usuário quiser saber como está o tempo agora.",
        "category": "weather",
    },
    {
        "name": "get_temperature_forecast_15_days",
        "description": "Retorna a previsão de temperatura para os próximos 15 dias em forma de tabela (data, máxima, mínima, média °C, condição). Use quando o usuário quiser saber a previsão de temperatura das próximas duas semanas, não de chuva.",
        "category": "weather",
    },
    {
        "name": "get_drought_index",
        "description": "Retorna o índice de seca (SPEI-like) para um mês/ano específico: índice (-3 a +3), categoria (severo/seco/normal/úmido), tendência e região. Use quando o usuário quiser saber o nível de seca de um período, não a chuva direta.",
        "category": "weather",
    },
    {
        "name": "get_evapotranspiration",
        "description": "Retorna a evapotranspiração de referência (ET₀ em mm/dia) para um mês/ano: ET₀ diária, ET₀ total, temperatura média e umidade. Use quando o usuário quiser saber a evapotranspiração ou demanda hídrica do pasto.",
        "category": "weather",
    },
    {
        "name": "get_soil_moisture",
        "description": "Retorna a umidade do solo atual (%) da propriedade: umidade, máxima, mínima e profundidade. Use quando o usuário quiser saber a umidade da terra/sojo agora, não a chuva ou temperatura.",
        "category": "weather",
    },
    {
        "name": "get_climate_summary",
        "description": "Retorna o resumo climático anual de uma região: chuva total, temperatura média, meses secos e chuvosos. Use quando o usuário quiser um panorama climático do ano, não dados diários ou mensais.",
        "category": "weather",
    },
    # ═══ Forage budget (benchmark — mocked) ════════════════════════════════
    # pasture-benchmark: mocked forage budget estimation. Skill-guided —
    # the LLM should fetch pasture stats first, ask herd size, then call
    # this tool. Category "pasture" groups it with future pasture-management
    # mocks. See BENCHMARK.md §8.
    {
        "name": "get_forage_budget",
        "description": "Estima quantos dias de pasto restam para o rebanho, combinando biomassa disponível com tamanho do rebanho (UA). Retorna biomassa total, consumo diário, dias restantes e recomendação de manejo. Use quando o usuário quiser saber se o pasto vai durar para o rebanho.",
        "category": "pasture",
        "skill": """
## Orçamento Forrageiro

Use esta skill quando o usuário quiser saber se a forragem/pasto é
suficiente para o rebanho, quantos dias de pasto restam, ou se precisa
reduzir o rebanho (destocking).

### Processo
1. Se o usuário não informou o tamanho do rebanho, pergunte quantas
   Unidades Animais (UA) ele tem antes de chamar a ferramenta.
2. Chame `get_forage_budget` com `herd_size_ua` e `user_id`.
   - Opcional: passe `car_codes` se a propriedade já for conhecida.
3. A ferramenta retorna `days_remaining` (dias de pasto restantes) e
   uma `recommendation` automática.
4. Interprete o resultado para o usuário em linguagem simples:
   - < 15 dias: situação crítica, destocking imediato ou suplementação.
   - 15–30 dias: atenção, planejar redução ou suplementação.
   - 30–60 dias: moderado, monitorar.
   - > 60 dias: confortável.

### Regras
- NUNCA invente o `herd_size_ua` — sempre pergunte se não foi informado.
- Use APENAS uma chamada a `get_forage_budget` por análise.
""".strip(),
    },
    # ═══ Paddock management (benchmark — mocked) ══════════════════════════
    # paddock-benchmark: mocked paddock CRUD + per-paddock stats + rotation
    # schedule. Paddock state is persisted in Valkey session_state under
    # `all_paddocks`, mirroring the property registration pattern. Category
    # "paddock" groups all paddock-related mocks. See BENCHMARK.md §8.
    {
        "name": "auto_generate_paddocks",
        "description": "Divide automaticamente uma propriedade em N piquetes (2 a 10) com áreas variadas e labels padrão (Pasto 1, Pasto 2, ...). Os piquetes ficam disponíveis para análise individual e rotação. Use quando o usuário quiser criar/gerar piquetes para a propriedade.",
        "category": "paddock",
        "skill": """
## Geração automática de piquetes

Use esta skill quando o usuário quiser dividir a propriedade em piquetes
ou quando precisar de contexto de piquetes para rotação de pastagem.

### Processo
1. Se o usuário informou o número de piquetes, use esse valor (2 a 10).
   Caso contrário, use o padrão (4) sem perguntar.
2. Chame `auto_generate_paddocks` com `car_codes`, `count` (opcional) e
   `user_id`.
3. A ferramenta cria os piquetes com ids `pdk-001`, `pdk-002`, etc. e
   labels padrão ("Pasto 1", "Pasto 2", ...).
4. Informe ao usuário que ele pode renomear os piquetes com
   `set_paddock_label`.

### Regras
- Use APENAS uma chamada por geração. Se já existem piquetes, a chamada
  substitui os anteriores.
""".strip(),
    },
    {
        "name": "set_paddock_label",
        "description": "Define ou atualiza o nome (label) de um piquete pelo seu ID (ex: pdk-001). Use quando o usuário quiser renomear ou nomear um piquete.",
        "category": "paddock",
        "skill": """
## Nomear/Renomear piquete

Use esta skill quando o usuário quiser dar um nome a um piquete ou
renomear um piquete existente.

### Processo
1. Identifique o `paddock_id` do piquete (ex: pdk-001). Se o usuário
   referir-se pelo nome atual, identifique o ID correspondente.
2. Identifique o novo `label` (nome) desejado.
3. Chame `set_paddock_label` com `paddock_id`, `label` e `user_id`.

### Regras
- Use APENAS um dos dois: `paddock_id` (nunca `label` para identificar).
""".strip(),
    },
    {
        "name": "delete_paddock",
        "description": "Remove um piquete pelo seu ID (ex: pdk-001). Use quando o usuário quiser excluir um piquete da propriedade.",
        "category": "paddock",
    },
    {
        "name": "get_paddock_pasture_stats",
        "description": "Retorna estatísticas de pastagem (biomassa, vigor, idade, uso do solo) de um piquete específico pelo seu ID, no mesmo formato de get_pasture_stats. Use quando o usuário quiser análise de pastagem de um piquete individual, não da propriedade inteira.",
        "category": "paddock",
    },
    {
        "name": "get_paddock_topographic_stats",
        "description": "Retorna estatísticas de topografia (altimetria e declividade) de um piquete específico pelo seu ID. Use quando o usuário quiser topografia de um piquete individual.",
        "category": "paddock",
    },
    {
        "name": "get_rotation_schedule",
        "description": "Gera um plano de rotação de pastagem baseado nos piquetes cadastrados: ordena por biomassa e dias de repouso, sugere ordem de pastejo e dias de ocupação por piquete. Use quando o usuário quiser um plano de rotação/rodízio de pasto.",
        "category": "paddock",
        "skill": """
## Plano de rotação de pastagem

Use esta skill quando o usuário quiser um plano de rotação/rodízio de
piquetes, saber qual piquete pastar primeiro, ou quantos dias deixar
o gado em cada piquete.

### Processo
1. Se não houver piquetes cadastrados (verifique o contexto da sessão),
   chame `auto_generate_paddocks` primeiro.
2. Se o usuário informou o período de repouso desejado, use esse valor
   (`rest_days`). Caso contrário, use o padrão (30 dias) sem perguntar.
3. Se o usuário informou o tamanho do rebanho, passe `herd_size_ua`.
   Caso contrário, use o padrão (50 UA) sem perguntar.
4. Chame `get_rotation_schedule` com `rest_days` (opcional),
   `herd_size_ua` (opcional) e `user_id`.
5. A ferramenta retorna um plano ordenado por prontidão (piquetes
   prontos primeiro), com dias de ocupação estimados.
6. Apresente o plano em linguagem natural, destacando qual piquete
   pastar primeiro.

### Regras
- Use APENAS uma chamada a `get_rotation_schedule` por plano.
""".strip(),
    },
    # ═══ Vaccination calendar (benchmark — mocked) ═════════════════════════
    # herd-benchmark: mocked annual vaccination calendar for Centro-Oeste.
    # Category "herd" groups herd-health mocks. See BENCHMARK.md §8.
    {
        "name": "get_vaccination_calendar",
        "description": "Retorna o calendário anual de vacinação do rebanho (aftosa, brucelose, carbúnculo, raiva, clostridioses, botulismo) adaptado à região Centro-Oeste. Use quando o usuário quiser saber quando vacinar o gado ou o calendário sanitário.",
        "category": "herd",
        "skill": """
## Calendário de vacinação

Use esta skill quando o usuário quiser saber o calendário de vacinação
do rebanho, quando aplicar cada vacina, ou o cronograma sanitário anual.

### Processo
1. Chame `get_vaccination_calendar` com `car_codes` (opcional) e
   `user_id`. O ano padrão é o atual.
2. A ferramenta retorna uma tabela com mês, vacina, rebanho-alvo e
   observações.
3. Apresente o calendário em linguagem natural, agrupado por mês.
4. Sempre mencione que é um calendário de referência e que o produtor
   deve consultar um médico veterinário.

### Regras
- Use APENAS uma chamada por calendário.
""".strip(),
    },
]


# Tools always available regardless of RAG results.
# - consult_update_notes: low-cost utility, always hand for "what's new" queries.
# - generate_speech: obligatory every run so the model can synthesize audio
#   whenever the user requests a spoken reply, independent of RAG similarity.
# - request_feedback / save_feedback: the frustration-remediation loop must
#   be reachable on any turn (frustration can arise mid-analysis, registration,
#   etc.), so they bypass RAG selection.
ALWAYS_AVAILABLE = {
    "consult_update_notes",
    "generate_speech",
    "request_feedback",
    "save_feedback",
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
    # feedback
    "request_feedback": ("feedback", "request_feedback"),
    "save_feedback": ("feedback", "save_feedback"),
    # benchmark (mocked alert schedulers)
    "request_biomass_alert": ("benchmark", "request_biomass_alert"),
    "confirm_biomass_alert": ("benchmark", "confirm_biomass_alert"),
    "request_rain_alert": ("benchmark", "request_rain_alert"),
    "confirm_rain_alert": ("benchmark", "confirm_rain_alert"),
    "request_vigor_alert": ("benchmark", "request_vigor_alert"),
    "confirm_vigor_alert": ("benchmark", "confirm_vigor_alert"),
    "request_stocking_rate_alert": ("benchmark", "request_stocking_rate_alert"),
    "confirm_stocking_rate_alert": ("benchmark", "confirm_stocking_rate_alert"),
    "list_schedulers": ("benchmark", "list_schedulers"),
    "delete_scheduler": ("benchmark", "delete_scheduler"),
    # benchmark (mocked weather data tools)
    "get_rain_forecast_15_days": ("benchmark", "get_rain_forecast_15_days"),
    "get_rain_forecast_months": ("benchmark", "get_rain_forecast_months"),
    "get_rain_history": ("benchmark", "get_rain_history"),
    "get_weather_today": ("benchmark", "get_weather_today"),
    "get_temperature_forecast_15_days": ("benchmark", "get_temperature_forecast_15_days"),
    "get_drought_index": ("benchmark", "get_drought_index"),
    "get_evapotranspiration": ("benchmark", "get_evapotranspiration"),
    "get_soil_moisture": ("benchmark", "get_soil_moisture"),
    "get_climate_summary": ("benchmark", "get_climate_summary"),
    # benchmark (mocked forage budget / paddock / vaccination)
    "get_forage_budget": ("benchmark", "get_forage_budget"),
    "auto_generate_paddocks": ("benchmark", "auto_generate_paddocks"),
    "set_paddock_label": ("benchmark", "set_paddock_label"),
    "delete_paddock": ("benchmark", "delete_paddock"),
    "get_paddock_pasture_stats": ("benchmark", "get_paddock_pasture_stats"),
    "get_paddock_topographic_stats": ("benchmark", "get_paddock_topographic_stats"),
    "get_rotation_schedule": ("benchmark", "get_rotation_schedule"),
    "get_vaccination_calendar": ("benchmark", "get_vaccination_calendar"),
}
