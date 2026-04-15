import textwrap

from agno.run import RunContext
from agno.agent import Agent
from agno.models.google import Gemini

from app.tools.property_crud_tools import (
    remove_property,
    remove_registered_properties,
    set_property_name,
    get_registered_properties,
    get_selected_property,
    register_feature_by_url,
    register_feature_by_car,
    register_feature_by_coordinate,
    select_car_from_list,
    confirm_car_selection,
    reject_car_selection
    )
from app.utils.interfaces.property_record import RuralProperty


def get_instructions(run_context: RunContext):
    session_state = run_context.session_state

    print(session_state, flush=True)

    candidate_properties = [RuralProperty.model_validate(prop) for prop in session_state.get("candidate_properties", [])]

    if candidate_properties:
        if len(candidate_properties) == 1:
            candidate_text = str(candidate_properties[0])

            instructions = textwrap.dedent(f"""
                - Você atua como um agente especialista subordinado dentro de um time de agentes.
                - Sua função exclusiva é receber, interpretar e executar com precisão as tarefas delegadas a você pelo agente Orquestrador.
                - Ao concluir sua tarefa, seja o mais claro, objetivo e estruturado possível ao reportar ao agente Orquestrador.
                - Foi pedido ao usuário para confirmar ou rejeitar a seguinte propriedade:
                                           
                > {candidate_text}

                - Atue exclusivamente na etapa de confirmação desta propriedade.
                - Acione a ferramenta confirm_car_selection ou reject_car_selection com base na resposta.
                - Ignore assuntos paralelos. Se o usuário fugir do tema, redirecione-o educadamente para a seleção do imóvel rural.
                - Se o usuário estiver confuso, instrua-o a confirmar ou rejeitar CAR ou a cancelar a operação.
                - Use markdown no formato do WhatsApp.
            """).strip()
        else:
            options_text = []
            for i, prop in enumerate(candidate_properties):
                options_text.append(f"> Opção {i + 1} - {prop.describe()}")
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
        registered_properties = [RuralProperty.model_validate(prop) for prop in session_state.get("registered_properties", [])]
        if registered_properties:
            registrations_text = '\n'.join([str(prop) for prop in registered_properties])
        else:
            registrations_text = "Vazio"

        instructions = textwrap.dedent(f"""
            <registrations>
            {registrations_text}
            <registrations>                    
                    
            <instructions>
            - Utilize as ferramentas disponíveis de forma estrita, respeitando rigorosamente os parâmetros e as orientações de uso de cada uma.
            - É proibido invocar as ferramentas `confirm_car_selection`, `select_car_from_list` e `reject_car_selection`. Nunca tente usá-las sob nenhuma hipótese.
            <instructions>
                                       
            <workflow>
            - Se o usuário informar o nome da propriedade:
                - Use a ferramenta set_property_name para definir o nome da propriedade.
            <workflow>  
        """).strip()
    
    return instructions


property_manager_agent = Agent(
    name="Gestor de Propriedades Rurais",
    role=(
        "Resposável pelo CRUD (Create, Read, Update e Delete) de propriedades do usuário no sistema:\n"
        "   - Localizar e cadastrar propriedades rurais.\n"
        "   - Editar e atualizar os metadados das propriedades.\n"
        "   - Excluir registros de propriedades quando solicitado."
    ),
    description=(
        "Agente resposável pelo CRUD (Create, Read, Update e Delete) de propriedades do usuário no sistema:\n"
        "   - Localizar e cadastrar propriedades rurais.\n"
        "   - Editar e atualizar os metadados das propriedades.\n"
        "   - Excluir registros de propriedades quando solicitado."
    ),
    tools=[
        remove_property,
        remove_registered_properties,
        set_property_name,
        get_registered_properties,
        get_selected_property,
        register_feature_by_url,
        register_feature_by_car,
        register_feature_by_coordinate,
        confirm_car_selection,
        select_car_from_list,
        reject_car_selection
        ],
    markdown=True,
    use_instruction_tags=False,
    instructions=get_instructions,
    model=Gemini(id="gemini-3-flash-preview", temperature=0)
)