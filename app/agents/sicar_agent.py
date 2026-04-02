import textwrap

from typing import List

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

from app.utils.interfaces.rural_property_interface import RuralProperty


def get_instructions(run_context: RunContext):
    session_state = run_context.session_state or {}

    candidate_properties: List[RuralProperty] = session_state.get("candidate_properties", None)

    if candidate_properties is not None and candidate_properties:
        n_candidates = len(candidate_properties)

        if n_candidates == 1:
            candidate_text = (
                f" > Identificador CAR: {candidate_properties[0].identifier}, "
                f"Tamanho da área: {round(candidate_properties[0].area_info.total_area)} ha, "
                f"Município: {candidate_properties[0].area_info.municipality}."
            )

            instructions = textwrap.dedent(f"""
                - Foi pedido ao usuário para confirmar ou rejeitar a seguinte propriedade:
                                           
                {candidate_text}

                - Atue exclusivamente na etapa de confirmação desta propriedade.
                - Acione a ferramenta confirm_car_selection ou reject_car_selection com base na resposta.
                - Ignore assuntos paralelos. Se o usuário fugir do tema, redirecione-o educadamente para a seleção do imóvel rural.
                - Se o usuário estiver confuso, instrua-o a confirmar ou rejeitar CAR ou a cancelar a operação.
                - Use markdown no formato do WhatsApp.
            """).strip()
        else:
            options_text = []
            for i, prop in enumerate(candidate_properties):
                options_text.append(
                    f"> Opção {i + 1} - Identificador CAR: {prop.identifier}, "
                    f"Tamanho da área: {round(prop.area_info.total_area)} ha, "
                    f"Município: {prop.area_info.municipality}."
                )
            result_text = "\n\n".join(options_text)

            instructions = textwrap.dedent(f"""
                - Foi pedido ao usuário para escolher entre as seguintes propriedades:
                                           
                {result_text}
                                           
                - Atue exclusivamente na etapa de seleção da propriedade.
                - Acione a ferramenta select_car_from_list ou reject_car_selection com base na resposta.
                - Ignore assuntos paralelos. Se o usuário fugir do tema, redirecione-o educadamente para a seleção do imóvel rural.
                - Se o usuário estiver confuso, instrua-o a digitar o número da opção desejada ou a cancelar a operação.
                - Use markdown no formato do WhatsApp.
            """).strip()
    else:
        instructions = instructions = textwrap.dedent("""
            - Seja sempre muito educado.
            - Siga as instruções dadas pelas ferramentas.
            - Nunca chame as ferramentas confirm_car_selection, select_car_from_list, reject_car_selection. Estas são ferramentas proibidas.
            - Use markdown no formato do WhatsApp.
        """).strip()
    
    return instructions


sicar_agent = Agent(
    name="Gestor de Propriedades Rurais",
    role=(
        "Resposável por administrar o inventário de propriedades do usuário no sistema, sendo o responsável por:\n"
        "   - Localizar e cadastrar novas propriedades rurais.\n"
        "   - Editar e atualizar os dados das propriedades selecionadas.\n"
        "   - Excluir registros de propriedades quando solicitado.\n"
    ),
    description=(
        "Agente resposável por administrar o inventário de propriedades do usuário no sistema, sendo o responsável por:\n"
        "   - Localizar e cadastrar novas propriedades rurais.\n"
        "   - Editar e atualizar os dados das propriedades selecionadas.\n"
        "   - Excluir registros de propriedades quando solicitado.\n"
    ),
    tools=[
        query_feature_by_url,
        query_feature_by_car,
        query_feature_by_coordinate,
        confirm_car_selection,
        select_car_from_list,
        reject_car_selection
        ],
    markdown=True,
    instructions=get_instructions,
    model=Gemini(id="gemini-3-flash-preview", temperature=0)
)