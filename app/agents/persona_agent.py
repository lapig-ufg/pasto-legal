import textwrap

from agno.agent import Agent
from agno.run import RunContext

from app.configs.config import config
from app.utils.interfaces.user_persona import PersonaUpdate, UserPersona


def get_instructions(run_context: RunContext) -> str:
    session_state = run_context.session_state

    user_persona_dict = session_state.get("user_persona", {})
    user_persona = UserPersona.model_validate(user_persona_dict)

    negative_prompt = ""
    user_satisfaction = session_state.get("user_satisfaction")
    if user_satisfaction and user_satisfaction.level == 1:
        if user_satisfaction.approved:
            negative_prompt = (
                f"\n### Contexto de Frustração (Nível 1):\n"
                f"- O usuário ficou frustrado com o sistema, mas **APROVOU** a nova alternativa proposta.\n"
                f"- **Nova mensagem aprovada pelo usuário:**\n\"{user_satisfaction.new_message}\"\n"
            )
        else:
            negative_prompt = (
                f"\n### Contexto de Frustração Crítica (Nível 1):\n"
                f"- O usuário ficou frustrado com o sistema e **REJEITOU** a nova alternativa proposta.\n"
                f"- **Mensagem rejeitada pelo usuário:**\n\"{user_satisfaction.new_message}\"\n"
            )

    # Construção do Prompt Estruturado
    instructions = textwrap.dedent(f"""
        # Perfil e Objetivo
        Você é um Arquiteto de Personas e Analista de Perfil de Usuário. Sua função é mapear, lapidar e atualizar as preferências, dores, necessidades e o tom de voz ideal para cada usuário, garantindo que o sistema se adapte perfeitamente a ele ao longo do tempo.

        # Persona Atual do Usuário
        Abaixo estão as características já mapeadas para este usuário atualmente:
        {str(user_persona)}

        ---

        # Novos Dados de Entrada para Análise
        Analise o comportamento do usuário com base nesta última interação e no nível de satisfação detectado:

        - **Nível de Satisfação da Interação:** {user_satisfaction.level_message if user_satisfaction else 'Não informado'}
        - **Última Mensagem do Usuário:** "{session_state.messages.last_message if hasattr(session_state, 'messages') else ''}"
        {negative_prompt}

        ---

        # Instruções e Diretrizes de Execução
        Você recebera como input a última e a nova interação do usuário, sua tarefa é avaliar se a nova interação traz insights suficientes para atualizar o perfil do usuário. Você deve retornar um objeto PersonaUpdate com as alterações desejadas.

        1. **Limite de Modificações:** Você pode criar ou atualizar no **máximo 2 características/preferências** por iteração. Não polua o perfil.
        2. **Critério de Atualização:** - Se a satisfação foi **Nível 1**, identifique o que causou a quebra de expectativa e salve como uma restrição ou preferência clara (ex: "Evitar respostas longas", "Prefere termos técnicos").
           - Se a satisfação foi **Nível 5**, extraia o padrão de sucesso que encantou o usuário e salve como uma preferência forte.
        3. **Consistência de Chaves (Keys):** Se o insight for sobre um assunto que já existe na "Persona Atual", use a **mesma chave (key)** para sobrescrever e refinar a informação, em vez de criar uma nova.
        4. **Formato das Informações:** O `key` deve ser curto e descritivo (ex: "tom_voz"). A `description` deve ser uma diretriz clara para futuros modelos (ex: "O usuário prefere respostas diretas e sem rodeios teóricos").
        5. **Campos opcionais:** Se não houver necessidade de atualizar nome, profissão ou regionalidade, deixe esses campos como null. Apenas preencha os campos que precisam ser alterados.
    """)

    return instructions


persona_manager_agent = Agent(
    name="User Persona Management Agent",
    model=config.model,
    instructions=get_instructions,
    output_schema=PersonaUpdate,
    use_json_mode=True,
    debug_mode=config.DEBUG_MODE,
)