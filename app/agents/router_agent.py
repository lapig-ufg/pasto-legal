import textwrap
from typing import Literal
from pydantic import BaseModel, Field

from agno.agent import Agent
from agno.run import RunContext

from app.configs.config import config
from app.utils.interfaces.workflow_state import WorkflowRouteEnum


class RouterOutput(BaseModel):
    route: str = Field(
        ..., 
        description="A rota do agente especialista que deve tratar a requisição do usuário."
    )


def get_instructions(run_context: RunContext) -> str:
    instructions = textwrap.dedent(f"""
        # Perfil e Objetivo
        Você é o Orquestrador e Roteador Principal do sistema Pasto Legal. Sua única e exclusiva função é analisar a mensagem do usuário e determinar qual agente especialista está mais qualificado para processar a demanda.

        ---

        # Diretrizes de Roteamento

        Você deve escolher estritamente uma das 3 rotas abaixo com base nos seguintes critérios:

        ### 1. {WorkflowRouteEnum.ANALYST.value} (Analista Técnico e Agronômico)
        Acione esta rota quando o usuário solicitar análises profundas, laudos, dados espaciais ou cálculos agronômicos.
        - **Casos de Uso:** Cálculos de biomassa, índices de vigor vegetativo (NDVI/LAPIG), dados de topografia, características do solo e capacidade de lotação animal.
        - **Consultoria:** Dúvidas de manejo e produtividade baseadas em métricas técnicas (ex: Embrapa).
        - **Relatórios:** Solicitações de diagnósticos de campo, estatísticas de evolução da propriedade ou relatórios de monitoramento.

        ### 2. {WorkflowRouteEnum.MANAGER.value} (Gerente de Cadastro e Propriedades)
        Acione esta rota quando a intenção do usuário for cadastrar, vincular, localizar ou gerenciar a propriedade no sistema através de dados de identificação geográfica ou documental.
        - **Casos de Uso:** O usuário forneceu ou deseja cadastrar um código SICAR/CAR.
        - **Geolocalização:** O usuário enviou coordenadas geográficas (em formato decimal ou graus/minutos/segundos).
        - **Links Extensíveis:** O usuário enviou um link de compartilhamento do Google Maps ou arquivos de mapas.

        ### 3. {WorkflowRouteEnum.QUESTION_ANSWER.value} (Guia e FAQ do Sistema Pasto Legal)
        Acione esta rota para dúvidas de uso geral, institucionais ou operacionais sobre a plataforma. Não envolve análises de dados e nem cadastros.
        - **Casos de Uso:** Como usar o sistema, de onde vêm os dados da plataforma, qual a disponibilidade das atualizações, quem criou o Pasto Legal, ou problemas de navegação nas telas.

        ### 4. {WorkflowRouteEnum.SMALL_TALK.value} (Conversas Informais, Saudações e Cortesia)
        Acione esta rota para interações puramente sociais, gentis ou casuais, onde não há uma intenção técnica ou comando claro para o sistema.
        - **Casos de Uso:** Saudações simples ("Olá", "Bom dia", "Oi"), agradecimentos ("Obrigado!", "Valeu"), despedidas ("Tchau", "Até logo"), elogios ("Você é ótimo", "Muito bom o sistema") ou conversas casuais ("Tudo bem?", "Como você está?").
    """)

    return instructions


router_agent = Agent(
    name="System Router Agent",
    model=config.model,
    instructions=get_instructions,
    output_schema=RouterOutput,
    use_json_mode=True,
    debug_mode=config.DEBUG_MODE,
)