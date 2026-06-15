import textwrap

from typing import Optional, Callable, Dict, Any
from pydantic import BaseModel, Field

from agno.run import RunContext
from agno.run.agent import RunInput
from agno.agent import Agent
from agno.models.google import Gemini
from agno.utils.log import log_error, log_debug

from app.configs.config import config


def validate_phone_authorization(user_id: Optional[str], run_input: RunInput):
    """
    Hook de validação para garantir que o número telefônico possui autorização.
    """
    user_phone_number = user_id.replace("wa:", "")

    try:
        with open(f'phone_numbers.in', 'r', encoding='utf-8') as file:
            
            for line in file:
                if line.strip() == user_phone_number.strip():
                    return
    
    except FileNotFoundError:
        log_error("FileNotFoundError: phone_numbers.in.")
    except Exception as e:
        log_error(f"Exception: {e}.")
    
    if config.APP_ENV == "production":
        run_input.input_content = (
            "O usuário não está autorizado a usar o sistema. "
            "Não responda nada do que ele perguntou antes. "
            "Sua ÚNICA tarefa agora é infomar o usuário que:"
            "- Esta é uma versão de Alpha com acesso restrito. "
            "- Para ter solicitar acesso é necessário preencher o formulário em: forms.gle/sKqngW7UvjmSJFKk8. "
        )
        
    elif config.APP_ENV == "stagging":
        run_input.input_content = (
            "INSTRUÇÃO DE SISTEMA IMPERATIVA: O usuário não está autorizado a testar esse sistema. "
            "Não responda nada do que ele perguntou antes. "
            "Sua ÚNICA tarefa agora é infomar o usuário que:"
            "- Esta é uma versão de desenvolvimento com acesso restrito. "
            "- Apenas pessoas autorizadas do projeto possuem acesso. "
        )
    else:
        run_input.input_content = (
            "INSTRUÇÃO DE SISTEMA IMPERATIVA: O usuário é um desenvolvedor testando o pre-hook de autorização. "
            "Não responda nada do que ele perguntou antes. "
            "Sua ÚNICA tarefa agora é infomar o usuário que:"
            "- O pre-hook esta funcionado. "
        )


def validate_terms_acceptance(run_context: RunContext, run_input: RunInput):
    """
    Hook de validação. Se não aceitou, altera o input para o Agente pedir o aceite.
    """
    session_state = run_context.session_state
    
    terms_accepted = session_state.get("terms_acceptance", None)

    # CENÁRIO 1: Primeira vez (chave não existe)
    if terms_accepted is None:
        session_state["terms_acceptance"] = False

        run_input.input_content = (
            "INSTRUÇÃO DE SISTEMA IMPERATIVA: O usuário NOVO acabou de chegar. "
            "Não responda nada do que ele perguntou antes. "
            "Sua ÚNICA tarefa agora é se apresentar brevemente e perguntar: "
            "'Você concorda com os nossos termos e condições?'"
        )

        return True

    # CENÁRIO 2: Usuário respondeu algo
    if terms_accepted is False:
        class TermConsent(BaseModel):
            acceptance: bool = Field(False, description="True se concordou, False caso contrário.")

        validator = Agent(
            instructions="Analise se o usuário concordou com os termos. Responda apenas com o JSON.",
            output_schema=TermConsent,
            model=Gemini(id="gemini-2.5-flash"), 
            markdown=False
        )
        
        check = validator.run(run_input.input_content)
        
        if check.content.acceptance:
            session_state["terms_acceptance"] = True
            
            run_input.input_content = "Olá! Aceitei os termos. Se apresente, por favor."
        else:
            # FALHA: O usuário respondeu algo que não foi um "sim"
            run_input.input_content = (
                "INSTRUÇÃO DE SISTEMA IMPERATIVA: O usuário respondeu algo, mas NÃO aceitou os termos claramente."
                "Explique educadamente que para continuar a análise é OBRIGATÓRIO concordar com os termos. "
                "Pergunte novamente."
            )

    return True


def validate_car_selection(run_context: RunContext, function_call: Callable, arguments: Dict[str, Any]) -> Any:
    """
    Hook de validação para garantir que o CAR (Cadastro Ambiental Rural) esteja presente.
    """
    session_state = run_context.session_state

    if session_state and not hasattr(session_state, "registered_properties"):
        return textwrap.dedent("""
            [SISTEMA] Bloqueio de Execução: Nenhum CAR registrado no sistema.
            
            Ação obrigatória para o Agente:
            1. Informe que o sistema ainda não possui uma propriedade selecionada.
            2. Solicite que o usuário envie a **localização** por meio do pino de localização do WhatsApp para que o sistema identifique o CAR automaticamente.
        """).strip()

def debug_session_state(run_context: RunContext):
    log_debug(f"\033[32mRUN CONTEXT\033[0m")
    log_debug("", center=True)
    log_debug(run_context.session_state)