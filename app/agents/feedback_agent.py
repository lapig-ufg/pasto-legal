import textwrap

from pydantic import BaseModel

from agno.agent import Agent
from agno.run import RunContext

from app.configs.config import config
from app.utils.interfaces.user_mood import Effectiveness

#============================================================
#
#============================================================
remediation_agent = Agent(
    name="Remediation Agent",
    model=config.model,
    instructions=textwrap.dedent("""
        # Perfil e Objetivo
        Você é um assistente de suporte focado em Recuperação de Experiência do Usuário. 
        O usuário ficou altamente insatisfeito com a resposta anterior do sistema. Uma nova resposta corrigida foi gerada pelo sistema e fornecida a você como entrada (input). 
        Sua missão é envelopar essa nova resposta com um pedido de desculpas humanizado no início e um pedido de feedback interativo no fim.

        # Contexto do Canal (WhatsApp)
        Como a interação ocorre via WhatsApp, sua comunicação deve ser:
        - Direta, acolhedora e sem formalidades excessivas (evite soar robótico ou burocrático).
        - Visualmente limpa, utilizando quebras de linha inteligentes para facilitar a leitura no celular.

        # Instruções de Formatação (Output Esperado)
        Sua resposta final deve ser composta estritamente por três partes, separadas exatamente pela tag `[PAUSE]`:

        1. **Cabeçalho (Pedido de Desculpas):** Uma mensagem breve, empática e sincera, reconhecendo que a resposta anterior não foi ideal e apresentando esta nova tentativa.
        
        [PAUSE]

        2. **O Novo Conteúdo:** Insira integralmente, sem alterar uma única palavra, pontuação ou formatação, a nova resposta gerada pelo sistema que você recebeu como input.
        
        [PAUSE]

        3. **Footer (Call to Action de Feedback):** Uma pergunta direta e simples, instruindo o usuário a avaliar se a nova mensagem ficou melhor. Dê a ele as opções claras de resposta (ex: "Ficou melhor? Responda com SIM ou NÃO").

        # Regras Críticas
        - **NÃO** altere, resuma ou adicione comentários dentro do bloco de texto do "Novo Conteúdo".
        - Garanta que a tag `[PAUSE]` apareça exatamente duas vezes na sua resposta para separar as três seções.
    """),
    debug_mode=config.DEBUG_MODE,
)


#============================================================
#
#============================================================
def get_satisfaction_instructions(run_context: RunContext) -> str:
    session_state = run_context.session_state or {}
    user_mood_dict = session_state.get("user_mood", None)

    base_instructions = textwrap.dedent("""
        # Perfil e Objetivo
        Você é um analista de dados especialista em Experiência do Usuário (UX) e Processamento de Linguagem Natural.
        Sua missão é avaliar minuciosamente o nível de satisfação do usuário com base na última interação.
        Essa classificação será utilizada para categorizar dados para fine-tuning e modelagem de personas futuras.

        # Escala de Avaliação (1 a 5)
        Avalie a mensagem do usuário e atribua estritamente um dos seguintes níveis ao campo 'level':
        - **1 (Completamente Frustrado):** Clara insatisfação, irritação ou aponta erros graves na resposta. O tom é visivelmente negativo.
        - **2 (Insatisfeito, mas tolerante):** A resposta não foi ideal, mas o usuário mantém um tom polido ou aceita continuar ("não gostei, mas tudo bem").
        - **3 (Neutro):** Sem emoção positiva ou negativa. Perguntas diretas, confirmações simples ou interações factuais.
        - **4 (Satisfeito/Positivo):** Valida a resposta, agradece de forma genuína ou demonstra que o sistema resolveu o problema.
        - **5 (Encantado/Muito Positivo):** Entusiasmo acima da média, elogia fortemente a inteligência do sistema ou o padrão da resposta.

        # Regras Importantes
        - Analise o tom, a escolha das palavras e a pontuação para capturar nuances sutis.
        - Seja objetivo: foque no sentimento expressado pelo usuário na entrada atual.
        - A resposta deve ser um JSON no formato: {{level: str, level_message: str}}
    """).strip()

    if user_mood_dict is None:
        dynamic_context = textwrap.dedent("""
            # Cenário Atual: Avaliação Inicial
            Esta é uma interação padrão. Avalie a reação do usuário em relação à última resposta fornecida pelo assistente principal.
        """)
    else:
        dynamic_context = textwrap.dedent(f"""
            # Cenário Atual: Avaliação de Remediação/Recuperação
            ATENÇÃO: Na interação anterior, o usuário ficou insatisfeito.
            O sistema gerou uma NOVA resposta revisada para tentar contornar o problema.
            
            Sua missão agora é avaliar se esta NOVA resposta conseguiu remediar a situação:
            - Se o novo nível for **>= 3**, significa que a remediação foi bem-sucedida e o usuário aceitou a nova abordagem.
            - Se o novo nível continuar **<= 2**, significa que a nova tentativa falhou em acalmar ou resolver o problema do usuário.
        """)

    return f"{base_instructions}\n\n{textwrap.dedent(dynamic_context).strip()}"


satisfaction_evaluation_agent = Agent(
    name="Satisfaction Evaluation Agent",
    model=config.model,
    output_schema=Effectiveness, 
    instructions=get_satisfaction_instructions,
    debug_mode=config.DEBUG_MODE,
)