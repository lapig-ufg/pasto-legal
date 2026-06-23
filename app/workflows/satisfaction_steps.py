import textwrap

from typing import Any, Dict
from datetime import datetime

from agno.agent import Agent
from agno.run import RunContext
from agno.workflow import Step, Steps, Router, Condition, Parallel
from agno.workflow.types import StepInput, StepOutput, HumanReview
from agno.utils.log import log_error, log_debug

from app.agents.feedback_agent import satisfaction_evaluation_agent, merge_negative_agent
from app.agents.persona_agent import persona_manager_agent
from app.configs.config import config
from app.database.session import engine, SessionLocal
from app.database.models import NegativeFeedback, PositiveFeedback
from app.tools.feedback_tools import _mask_pii


DEFAULT_SATISFACTION_LEVEL = 3


def save_negative_feedback(
    step_input: StepInput,
    session_state: Dict[str, Any],
    run_context: RunContext = None,
) -> StepOutput:
    """Persist a frustrated interaction to the NegativeFeedback table."""
    #user_msg = step_input.get_input_as_string() or ""
    #normal_response = _get_normal_response(step_input)
    #handler_msg = session_state.get("handler_message", "")
    #
    #NegativeFeedback.metadata.create_all(bind=engine)
    #session = SessionLocal()
    #try:
    #    novo_feedback = NegativeFeedback(
    #        timestamp=datetime.now().isoformat(),
    #        original_question="Original Question", # TODO: Deveria ser a mensagem que gerou a frustração (a mensagem anterior à run atual)
    #        reason_frustration=user_msg, 
    #        desired_answer=_mask_pii(normal_response),
    #        context=_mask_pii(handler_msg),
    #    )
    #    session.add(novo_feedback)
    #    session.commit()
    #    log_debug("negative feedback saved by workflow.")
    #except Exception as e:
    #    session.rollback()
    #    log_error(f"Erro ao registrar negative feedback: {e}")
    #finally:
    #    session.close()

    return StepOutput(content="Negative Feedback Saved")


def save_positive_feedback(
    step_input: StepInput,
    session_state: Dict[str, Any],
    run_context: RunContext = None,
) -> StepOutput:
    """Persist an positive interaction to the PositiveFeedback table for future fine-tuning."""
    #grade = session_state.get("satisfaction_grade", 3)
    #user_msg = step_input.get_input_as_string() or ""
    #normal_response = _get_normal_response(step_input)
    #handler_msg = session_state.get("handler_message", "")
    #
    #PositiveFeedback.metadata.create_all(bind=engine)
    #session = SessionLocal()
    #try:
    #    novo_feedback = PositiveFeedback(
    #        timestamp=datetime.now().isoformat(),
    #        user_message=_mask_pii(user_msg),
    #        assistant_response=_mask_pii(normal_response),
    #        handler_message=_mask_pii(handler_msg),
    #        grade=grade,
    #        context=_mask_pii(normal_response),
    #    )
    #    session.add(novo_feedback)
    #    session.commit()
    #    log_debug("Positive feedback saved by workflow.")
    #except Exception as e:
    #    session.rollback()
    #    log_error(f"Erro ao registrar positive feedback: {e}")
    #finally:
    #    session.close()

    return StepOutput(content="Positive Feedback Saved")

# ---------------------------------------------------------------------------
# Step executors
# ---------------------------------------------------------------------------
def satisfaction_evaluation(step_input: StepInput, session_state: Dict[str, Any]) -> StepOutput:
    """Grade the user's message on a 1-5 scale and store it in session_state."""
    user_msg = step_input.get_input_as_string() or ""

    try:
        response = satisfaction_evaluation_agent.run(user_msg)
        if response and response.content:
            satisfaction_level = int(getattr(response.content, "level", DEFAULT_SATISFACTION_LEVEL))
    except Exception as e:
        log_error(f"Satisfaction Evaluation Agent agent failed: {e}")

    satisfaction_level = max(1, min(5, satisfaction_level))
    session_state["satisfaction_level"] = satisfaction_level

    log_debug(f"Satisfaction grade: {satisfaction_level}")
    return StepOutput(content=satisfaction_level)


# ---------------------------------------------------------------------------
# Branching — Agno's Condition is two-way only, so a 3-way branch is built
# with nested Conditions on the grade stored in session_state.
# ---------------------------------------------------------------------------
def satisfaction_selector(step_input: StepInput, session_state: Dict[str, Any]):
    satisfaction_level = session_state.get("satisfaction_level", 3)

    if satisfaction_level == 5:
        return ["Positive Steps"]
    elif satisfaction_level == 1:
        return ["Ngative Steps"]
    else:
        return ["Default"]


def negative_satisfaction_evaluator(step_input: StepInput, session_state: Dict[str, Any]):
    return session_state.get("satisfaction_level", DEFAULT_SATISFACTION_LEVEL) == 1

# ---------------------------------------------------------------------------
# 
# ---------------------------------------------------------------------------
feedback_agent = Agent(
    name="Negative Feedback Handler",  # Corrigido o typo :)
    model=config.model,
    instructions=textwrap.dedent("""
        # Perfil e Objetivo
        Você é um assistente de suporte altamente empático, profissional e focado em resolução de problemas. 
        O usuário ficou frustrado com a resposta anterior do sistema. Sua missão é reatar a confiança dele, apresentando uma nova solução de forma polida e clara.

        # Instruções de Formatação (Output esperado)
        Sua resposta final deve seguir estritamente esta estrutura de três partes:

        1. **Introdução (Pedido de Desculpas Embaçado):** Escreva uma mensagem breve e sincera reconhecendo que a resposta anterior não atendeu às expectativas. Evite ser excessivamente robótico ou dramático; seja profissional e direto.

        2. **O Novo Conteúdo:** Insira integralmente e sem alterações a nova resposta gerada pelo sistema (que você receberá como input).

        3. **Footer (Mensagem de Validação):** Termine com uma pergunta cordial, verificando se esta nova resposta está mais próxima do que ele esperava ou se ele precisa de mais algum ajuste.

        # Regras Importantes
        - Mantenha o tom de voz acolhedor, prestativo e neutro.
        - Não invente informações além da nova resposta fornecida pelo sistema.
        - Separe visualmente a introdução, o conteúdo e o footer usando a seguinte tag: [PAUSA].
    """),
    use_instruction_tags=False,
    debug_mode=config.DEBUG_MODE,
)

# ---------------------------------------------------------------------------
# Evaluation branch — grade the message, then branch on the grade.
# ---------------------------------------------------------------------------
satisfaction_evaluation_steps = Steps(
    name="Satisfaction Evaluation Steps",
    steps=[
        Step(name="Satisfaction Evaluation", executor=satisfaction_evaluation),
        Parallel(
            Router(
                name="Satisfaction Evaluation Router",
                selector=satisfaction_selector,
                choices=[
                    Step(name="Positive Steps", executor=save_positive_feedback),
                    Step(name="Negative Steps", executor=save_negative_feedback),
                    Step(name="Default", executor=lambda x: None)
                ]
            ),
            Step(name="Managing Persona", agent=persona_manager_agent),
            name="Evaluation Parallel"
        )
    ]
)

negative_satisfaction_merge_step = Condition(
    evaluator=negative_satisfaction_evaluator,
    steps=[Step(name="Meging Negative Feedback", agent=merge_negative_agent)],
)