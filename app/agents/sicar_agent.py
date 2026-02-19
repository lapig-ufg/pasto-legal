import textwrap

from agno.run import RunContext
from agno.agent import Agent
from agno.models.google import Gemini

from app.tools.sicar_tools import query_feature_by_car, query_feature_by_coordinate, select_car_from_list, confirm_car_selection, reject_car_selection

# TODO: Possivelmente o agente vai perder o contexto do que ele esta escolhendo. É importante passar isso junto as instruções. é viável e possivel. Fazer caso perceba esse comportamento.
def get_instructions(run_context: RunContext):
    session_state = run_context.session_state or {}

    is_selecting_car = session_state.get("is_selecting_car", False)

    if is_selecting_car:
        car_selection_type = session_state.get("car_selection_type")

        if car_selection_type == "SINGLE":
            instructions = textwrap.dedent("""
                Atue exclusivamente na etapa de confirmação de Cadastro Ambiental Rural (CAR).
                Regras:
                    1. Acione a ferramenta confirm_car_selection ou reject_car_selection com base na resposta.
                    2. Ignore assuntos paralelos. Se o usuário fugir do tema, redirecione-o educadamente para a seleção do imóvel rural.
                    3. Se o usuário estiver confuso, instrua-o a confirmar ou rejeitar CAR ou a cancelar a operação.
                    4. Recuse educadamente toda solicitação até que o usuário selecione, recuse ou cancele a operação.
                    5. NUNCA acione membros e agentes.
            """).strip()
        elif car_selection_type == "MULTIPLE":
            instructions = textwrap.dedent("""
                Atue exclusivamente na etapa de seleção de Cadastro Ambiental Rural (CAR).
                Regras:
                    1. Acione a ferramenta select_car_from_list ou reject_car_selection com base na resposta.
                    2. Ignore assuntos paralelos. Se o usuário fugir do tema, redirecione-o educadamente para a seleção do imóvel rural.
                    3. Se o usuário estiver confuso, instrua-o a digitar o número correspondente ao CAR desejado ou a cancelar a operação.
                    4. Recuse educadamente toda solicitação até que o usuário confirme, recuse ou cancele a operação.
                    5. NUNCA acione membros e agentes.
            """).strip()
        else:
            instructions = "Ignore a menssagem do usuário. Informe educadamente que houve um erro e peça ao usuário que tente novamente mais tarde."
    else:
        instructions = instructions = textwrap.dedent("""
            NUNCA chame as ferramentas confirm_car_selection, select_car_from_list, reject_car_selection. Estas são ferramentas proibidas.
                                                    
            # Recebimento de Localização ou Coordenadas
            SE o usuário enviar uma localização (coordenadas):
            - **AÇÕES:**
                1. Chame a ferramenta 'query_feature_by_coordinates' ajudar o usuário.
                2. Depois, IMEDIATAMENTE responda ao usuário assim como a ferramenta instruir.
                            
            # Recebimento de Cadastro Ambiental Rural (CAR)
            SE usuário enviar um CAR no modelo UF-XXXXXXX-XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX:
            - **AÇÕES:**
                1. Chame a ferramenta 'query_feature_by_car' ajudar o usuário.
                2. Depois, IMEDIATAMENTE responda ao usuário assim como a ferramenta instruir.
        """).strip()
    
    return instructions

sicar_agent = Agent(
    name="sicar-agent",
    role="Processador de Entradas Geográficas e Registros CAR",
    description="Analista técnico responsável por localizar, validar e confirmar propriedades rurais via código CAR ou coordenadas geográficas.",
    tools=[
        query_feature_by_car,
        query_feature_by_coordinate,
        confirm_car_selection,
        select_car_from_list,
        reject_car_selection
        ],
    instructions=get_instructions,
    model=Gemini(id="gemini-2.5-flash")
)