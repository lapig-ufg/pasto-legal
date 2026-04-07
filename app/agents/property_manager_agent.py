import textwrap

from agno.run import RunContext
from agno.agent import Agent
from agno.models.google import Gemini

from app.tools.property_manager_tools import (
    remove_property,
    remove_all_properties,
    set_property_name,
    get_all_properties,
    get_selected_property,
    register_feature_by_url,
    register_feature_by_car,
    register_feature_by_coordinate,
    select_car_from_list,
    confirm_car_selection,
    reject_car_selection
    )


def get_instructions(run_context: RunContext):
    session_state = run_context.session_state or {}

    candidate_properties = session_state.get("candidate_properties", None)

    if candidate_properties:
        n_candidates = len(candidate_properties)

        if n_candidates == 1:
            candidate_text = (
                f" > Identificador CAR: {candidate_properties[0]["car_code"]}, "
                f"Tamanho da área: {round(candidate_properties[0]["spatial_features"]["total_area"])} ha, "
                f"Município: {candidate_properties[0]["spatial_features"]["municipality"]}."
            )

            instructions = textwrap.dedent(f"""
                - Você atua como um agente especialista subordinado dentro de um time de agentes.
                - Sua função exclusiva é receber, interpretar e executar com precisão as tarefas delegadas a você pelo agente Orquestrador.
                - Ao concluir sua tarefa, seja o mais claro, objetivo e estruturado possível ao reportar ao agente Orquestrador.
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
            for i, p in enumerate(candidate_properties):
                options_text.append(
                    f"> Opção {i + 1} - Identificador CAR: {p["car_code"]}, "
                    f"Tamanho da área: {round(p["spatial_features"]["total_area"])} ha, "
                    f"Município: {p["spatial_features"]["municipality"]}."
                )
            result_text = "\n".join(options_text)

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
        instructions = textwrap.dedent("""
            - Utilize as ferramentas disponíveis de forma estrita, respeitando rigorosamente os parâmetros e as orientações de uso de cada uma.
            - É proibido invocar as ferramentas `confirm_car_selection`, `select_car_from_list` e `reject_car_selection`. Nunca tente usá-las sob nenhuma hipótese.

            <mandatory-workflow>
            - Se o usuário informar o nome da propriedade:
                - Use a ferramenta set_property_name para definir o nome da propriedade.
            <mandatory-workflow>  
        """).strip()
    
    return instructions


property_manager_agent = Agent(
    name="Gestor de Propriedades Rurais",
    role=(
        "Resposável por administrar os registros de propriedades do usuário no sistema, sendo o responsável por:\n"
        "   - Localizar e cadastrar novas propriedades rurais.\n"
        "   - Editar e atualizar os dados e metadados das propriedades.\n"
        "   - Excluir registros de propriedades quando solicitado."
    ),
    description=(
        "Agente resposável por administrar os registros de propriedades do usuário no sistema, sendo o responsável por:\n"
        "   - Localizar e cadastrar novas propriedades rurais.\n"
        "   - Editar e atualizar os dados e metadados das propriedades.\n"
        "   - Excluir registros de propriedades quando solicitado."
    ),
    tools=[
        remove_property,
        remove_all_properties,
        set_property_name,
        get_all_properties,
        get_selected_property,
        register_feature_by_url,
        register_feature_by_car,
        register_feature_by_coordinate,
        confirm_car_selection,
        select_car_from_list,
        reject_car_selection
        ],
    markdown=True,
    instructions=get_instructions,
    model=Gemini(id="gemini-3-flash-preview", temperature=0)
)