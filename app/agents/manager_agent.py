import textwrap

from agno.agent import Agent
from agno.run import RunContext
from agno.utils.log import log_debug, log_error

from app.tools.property_crud_tools import (
    remove_property,
    remove_all_properties,
    set_property_name,
    start_registration_by_url,
    start_registration_by_car,
    start_registration_by_coordinate,
    select_car_from_list,
    confirm_car_selection,
    cancel_registration
)
from app.tools.tts_tools import generate_speech
from app.schemas.rural_property import RuralProperty
from app.configs.config import config


def get_tools(run_context: RunContext):
    session_state = run_context.session_state
    registration_state = session_state.get("registration_state", None)

    tools = [generate_speech]

    # ==========================================
    # ESTADO: PENDING (Confirmação ou Seleção)
    # ==========================================
    if registration_state == "pending":
        candidate_properties = [RuralProperty.model_validate(prop) for prop in session_state.get("candidate_properties", [])]
        
        # Cenário A: Apenas 1 propriedade encontrada para confirmação
        if len(candidate_properties) == 1:
            tools.extend([confirm_car_selection, cancel_registration])
        
        # Cenário B: Múltiplas propriedades encontradas (Usuário precisa escolher)
        tools.extend([select_car_from_list, cancel_registration])
            
    # ==========================================
    # ESTADO: FINAL (Definição de Nome customizado)
    # ==========================================
    elif registration_state == "final":
        tools.extend([set_property_name, cancel_registration])

    # ==========================================
    # ESTADO: DEFAULT / ELSE (Gerenciamento Geral)
    # ==========================================
    else:
        tools.extend([
            remove_property,
            remove_all_properties,
            set_property_name,
            start_registration_by_url,
            start_registration_by_car,
            start_registration_by_coordinate,
        ])

    log_debug(tools)

    return tools


def get_instructions(run_context: RunContext) -> str:
    log_debug("GET INSTRUCTIONS")
    session_state = run_context.session_state
    registration_state = session_state.get("registration_state", None)

    # ==========================================
    # ESTADO: PENDING (Confirmação ou Seleção)
    # ==========================================
    if registration_state == "pending":
        candidate_properties = [RuralProperty.model_validate(prop) for prop in session_state.get("candidate_properties", [])]
        
        # Cenário A: Apenas 1 propriedade encontrada para confirmação
        if len(candidate_properties) == 1:
            candidate_text = str(candidate_properties[0])

            instructions = textwrap.dedent(f"""
                # Perfil e Objetivo
                Você é o Gestor de Propriedades Rurais do sistema Pasto Legal. Sua função atual é estritamente coletar a confirmação do usuário para o imóvel rural encontrado.

                # Propriedade em Análise
                O sistema localizou a seguinte propriedade para o usuário:
                > {candidate_text}

                # Diretrizes de Execução
                - Se o usuário confirmar que esta é a propriedade correta (ex: "sim", "essa mesma", "pode salvar"), acione imediatamente a ferramenta `confirm_car_selection`.
                - Se o usuário rejeitar a propriedade (ex: "não é essa", "está errado"), acione a ferramenta `cancel_car_selection`.
                - Ignore assuntos paralelos. Se o usuário tentar mudar de assunto, traga-o de volta educadamente para a confirmação do imóvel.
            """).strip()
        
        # Cenário B: Múltiplas propriedades encontradas (Usuário precisa escolher)
        else:
            options_text = []
            for i, prop in enumerate(candidate_properties):
                options_text.append(f"*Opção {i + 1}* - {prop.describe()}")
            candidate_text = "\n".join(options_text)

            instructions = textwrap.dedent(f"""
                # Perfil e Objetivo
                Você é o Gestor de Propriedades Rurais do sistema Pasto Legal. Múltiplos imóveis foram encontrados e o usuário precisa selecionar um deles.

                # Opções Disponíveis
                {candidate_text}

                # Diretrizes de Execução
                - Se o usuário escolher uma das opções (pelo número, nome ou índice), invoque a ferramenta `select_car_from_list` passando o parâmetro correspondente.
                - Se o usuário desistir ou disser que nenhuma serve, acione a ferramenta `cancel_car_selection`.
                - Se ele demonstrar confusão, instrua-o de forma simples a digitar apenas o número da opção desejada.
            """).strip()

    # ==========================================
    # ESTADO: FINAL (Definição de Nome customizado)
    # ==========================================
    elif registration_state == "final":
        candidate_properties = [RuralProperty.model_validate(prop) for prop in session_state.get("candidate_properties", [])]
        candidate_text = str(candidate_properties[0]) if candidate_properties else "Propriedade selecionada"

        instructions = textwrap.dedent(f"""
            # Perfil e Objetivo
            Você está na etapa final de cadastro do imóvel rural:
            > {candidate_text}

            Sua missão é coletar ou definir um nome amigável para esta propriedade.

            # Diretrizes de Execução
            - Se o usuário informar um nome para a propriedade (ex: "Quero que se chame Fazenda Primavera"), invoque imediatamente a ferramenta `set_property_name`.
            - Se o usuário desejar abortar o processo nesta fase, chame a ferramenta `cancel_car_selection`.
            - Se o usuário não fornecer um nome claro ou enviar saudações vagas, lembre-o de que ele precisa dar um nome para concluir ou digitar "cancelar".
            - Mantenha o texto limpo, curto e focado em mensagens de celular (`*texto*` para negrito).
        """).strip()

    # ==========================================
    # ESTADO: DEFAULT / ELSE (Gerenciamento Geral)
    # ==========================================
    else:
        all_properties = [RuralProperty.model_validate(prop) for prop in session_state.get("all_properties", [])]
        if all_properties:
            registrations_text = '\n'.join([f"- {str(prop)}" for prop in all_properties])
        else:
            registrations_text = "*Nenhum imóvel cadastrado no momento.*"

        instructions = textwrap.dedent(f"""
            # Perfil e Objetivo
            Você é o Gestor de Propriedades Rurais do sistema Pasto Legal. Neste modo, você é responsável por iniciar novos cadastros, listar propriedades ou remover imóveis da conta do usuário.

            - Se o usuário solicitar áudio, responda normalmente em texto — o sistema fará a conversão.

            # Lista de Propriedades Cadastradas Atualmente
            <registrations>
            {registrations_text}
            </registrations>                    
                    
            # Regras Críticas de Fluxo e Ferramentas
            1. **Cadastro por Código CAR/SICAR:** Se o usuário fornecer um código CAR/SICAR válido, chame `start_registration_by_car`.
            2. **Cadastro por Coordenadas:** Se o usuário fornecer latitude/longitude (em graus ou decimais), chame `start_registration_by_coordinate`.
            3. **Cadastro por Link:** Se o usuário enviar um link de compartilhamento do Google Maps, chame `start_registration_by_url`.
            4. **Remoção:** Se o usuário solicitar a exclusão de um imóvel específico, use `remove_property`. Se ele pedir para apagar tudo, use `remove_all_properties`.
            5. **Atribuição de Nome:** Se o usuário solicitar a alteração de nome de um imóvel já existente, utilize `set_property_name`.

            # Restrições Absolutas
            - **Comunicação (WhatsApp):** Respostas curtas, objetivas, instruindo o usuário sobre os dados que ele precisa enviar para gerenciar os imóveis.
        """).strip()
    
    return instructions


# Instanciação do Agente Corrigido e Otimizado
manager_agent = Agent(
    name="Gestor de Propriedades Rurais",
    tools=get_tools,
    markdown=True,
    use_instruction_tags=False,
    instructions=get_instructions,
    cache_callables=False,
    model=config.model,
    debug_mode=config.DEBUG_MODE
)