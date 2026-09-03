from typing import Optional, Callable, Dict, Any
from pydantic import BaseModel, Field

from agno.run import RunContext
from agno.run.agent import RunInput
from agno.agent import Agent
from agno.models.google import Gemini
from agno.utils.log import log_error, log_debug

from app.configs.config import config
from app.configs.prompts import get_hook_texts


_pre_hook_texts = get_hook_texts("pre_hooks")
_tool_hook_texts = get_hook_texts("tool_hooks")


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
        run_input.input_content = _pre_hook_texts["unauthorized_production"].strip()
        
    elif config.APP_ENV == "stagging":
        run_input.input_content = _pre_hook_texts["unauthorized_stagging"].strip()
    else:
        run_input.input_content = _pre_hook_texts["unauthorized_development"].strip()


def validate_terms_acceptance(run_context: RunContext, run_input: RunInput):
    """
    Hook de validação. Se não aceitou, altera o input para o Agente pedir o aceite.
    """
    session_state = run_context.session_state
    
    terms_accepted = session_state.get("terms_acceptance", None)

    # CENÁRIO 1: Primeira vez (chave não existe)
    if terms_accepted is None:
        session_state["terms_acceptance"] = False

        run_input.input_content = _pre_hook_texts["terms_first_contact"].strip()

        return True

    # CENÁRIO 2: Usuário respondeu algo
    if terms_accepted is False:
        class TermConsent(BaseModel):
            acceptance: bool = Field(False, description="True se concordou, False caso contrário.")

        validator = Agent(
            instructions=_pre_hook_texts["terms_validator_instructions"].strip(),
            output_schema=TermConsent,
            model=Gemini(id="gemini-2.5-flash"), 
            markdown=False
        )
        
        check = validator.run(run_input.input_content)
        
        if check.content.acceptance:
            session_state["terms_acceptance"] = True
            
            run_input.input_content = _pre_hook_texts["terms_accepted"].strip()
        else:
            # FALHA: O usuário respondeu algo que não foi um "sim"
            run_input.input_content = _pre_hook_texts["terms_not_accepted"].strip()

    return True


def validate_car_selection(run_context: RunContext, function_call: Callable, arguments: Dict[str, Any]) -> Any:
    """
    Hook de validação para garantir que o CAR (Cadastro Ambiental Rural) esteja presente.
    """
    session_state = run_context.session_state

    if session_state and not hasattr(session_state, "all_properties"):
        return _tool_hook_texts["no_car_registered"].strip()