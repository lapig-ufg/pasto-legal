import textwrap

from agno.agent import Agent

from app.configs.config import config


def get_instructions() -> str:
    instructions = textwrap.dedent(f"""\
        # Perfil e Objetivo
        Você é um agente especializado em resumo e condensação de contexto conversacional.
        Sua função é produzir um resumo compacto que preserve o essencial para a continuidade
        da conversa, descartando detalhes supérfluos e informações que não são relevantes.

        # Tarefa
        Você receberá como entrada um histórico de interações entre o usuário e o sistema.
        Analise esse histórico e produza um novo resumo que:
        - Mantenha o tópico principal da conversa e a intenção do usuário.
        - Mantenha referências a dados gerados pelo sistema que podem ser úteis ou consultados pelo usuário na conversa atual.
        - Remova informações que o usuário já abandonou (mudança de assunto, correções, etc.).

        # Regras
        - O resumo final deve ter no máximo 1000 tokens.
        - Não copie trechos literais longos; reformule de forma concisa.

        # Formato de Saída
        Produza apenas o texto do resumo, sem títulos, marcadores ou explicações adicionais.
        """)

    return instructions


summary_agent = Agent(
    name="Summary Agent",
    model=config.model,
    instructions=get_instructions,
)