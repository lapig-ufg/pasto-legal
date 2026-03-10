import textwrap

from agno.run import RunContext
from agno.agent import Agent
from agno.models.google import Gemini

from app.tools.sicar_tools import (
    query_feature_by_url,
    query_feature_by_car,
    query_feature_by_coordinate,
    select_car_from_list,
    confirm_car_selection,
    reject_car_selection
    )


def get_instructions(run_context: RunContext):
    session_state = run_context.session_state or {}

    is_selecting_car = session_state.get("is_selecting_car", False)

    if is_selecting_car:
        car_selection_type = session_state.get("car_selection_type")

        if car_selection_type == "SINGLE":
            candidate = run_context.session_state['car_candidate']

            candidate_text = (
                f"*CAR* {candidate["code"]}\n"
                f"*Tamanho da área*: {round(candidate["area_info"]["total_area"])} ha\n"
                f"*Município*: {candidate["area_info"]["municipality"]}"
            )

            instructions = textwrap.dedent(f"""
                Foi pedido ao usuário para confirmar ou rejeitar a seguinte propriedade:
                                           
                {candidate_text}

                Atue exclusivamente na etapa de confirmação desta propriedade.
                Acione a ferramenta confirm_car_selection ou reject_car_selection com base na resposta.
                Ignore assuntos paralelos. Se o usuário fugir do tema, redirecione-o educadamente para a seleção do imóvel rural.
                Se o usuário estiver confuso, instrua-o a confirmar ou rejeitar CAR ou a cancelar a operação.
            """).strip()
        elif car_selection_type == "MULTIPLE":
            car_all = run_context.session_state['car_all']

            options_text = []
            for i, prop in enumerate(car_all):
                options_text.append(
                    f"- Opção {i + 1}: CAR {prop['code']}, "
                    f"Tamanho da área {round(prop['area_info']['total_area'])} ha, "
                    f"município de {prop['area_info']['municipality']}."
                )
            result_text = "\n".join(options_text)

            instructions = textwrap.dedent(f"""
                Foi pedido ao usuário para escolher entre as seguintes propriedades:
                                           
                {result_text}
                                           
                Atue exclusivamente na etapa de seleção da propriedade.
                Acione a ferramenta select_car_from_list ou reject_car_selection com base na resposta.
                Ignore assuntos paralelos. Se o usuário fugir do tema, redirecione-o educadamente para a seleção do imóvel rural.
                Se o usuário estiver confuso, instrua-o a digitar o número da opção desejada ou a cancelar a operação.
            """).strip()
    else:
        instructions = instructions = textwrap.dedent("""
            Seja SEMPRE educado e SEMPRE SIGA as instruções dadas pelas ferramentas.
            NUNCA chame as ferramentas confirm_car_selection, select_car_from_list, reject_car_selection. Estas são ferramentas proibidas.
                                                    
            # Recebimento de Localização ou Coordenadas
            SE o usuário enviar uma localização (coordenadas):
            - **AÇÕES:**
                1. Se o usuário fornecer coordenadas no formato de Graus, Minutos e Segundos (GMS), converta-as para Graus Decimais (DD) antes de prosseguir. 
                1. Chame a ferramenta 'query_feature_by_coordinates'.
                2. Depois, SIGA as intruções da ferramenta.
                            
            # Recebimento de Cadastro Ambiental Rural (CAR)
            SE o usuário enviar um CAR no modelo UF-XXXXXXX-XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX ou UF-XXXXXXX-CCCC.CCCC.CCCC.CCCC.CCCC.CCCC.CCCC.CCCC:
            - **AÇÕES:**
                1. Chame a ferramenta 'query_feature_by_car'.
                2. Depois, SIGA as intruções da ferramenta.
                                                      
            # Recebimento de URL do Google Maps
            SE o usuário enviar uma URL do Google Maps
            - **Ações:**
                1. Chame a ferramenta 'query_feature_by_url'
                2. Depois, SIGA as intruções da ferramenta.
        """).strip()
    
    return instructions


sicar_agent = Agent(
    name="sicar-agent",
    role="Processador de Entradas Geográficas e Registros CAR",
    description="Analista técnico responsável por localizar, validar e confirmar propriedades rurais via código CAR ou coordenadas geográficas.",
    tools=[
        query_feature_by_url,
        query_feature_by_car,
        query_feature_by_coordinate,
        confirm_car_selection,
        select_car_from_list,
        reject_car_selection
        ],
    instructions=get_instructions,
    model=Gemini(id="gemini-3-flash-preview")
)