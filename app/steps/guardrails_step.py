"""Sanitização de PII: remove dados pessoais do texto antes dos agentes.

Substitui o dado por um marcador (`[CPF_OCULTO]`) e deixa a mensagem seguir,
em vez de recusá-la. Assim o produtor não perde os pedidos que fez na mesma
mensagem, e o dado não chega ao agente.

O texto digitado já é redigido na entrada (MessageContent.__post_init__, em
whatsapp/helpers.py). Este passo cobre o que só vira texto dentro do workflow:
a transcrição do áudio e a descrição da imagem, produzidas pelo input_step.

Interface externa:
    _guardrail_pii_executor  -- StepExecutor consumido por pasto_legal_workflow.
"""
from agno.utils.log import log_info
from agno.workflow import Step
from agno.workflow.types import StepInput, StepOutput

from app.guardrails.pii_gate import redigir_pii


def _guardrail_pii_executor(step_input: StepInput) -> StepOutput:
    """Redige dados pessoais do texto consolidado pelo passo anterior.

    Lê `previous_step_content` e não `get_input_as_string()`: esta última
    devolve o input ORIGINAL do workflow (agno/workflow/types.py:257), o que
    deixaria a transcrição do áudio e a descrição da imagem fora da varredura.
    """
    conteudo = step_input.previous_step_content or step_input.get_input_as_string() or ""
    text = conteudo if isinstance(conteudo, str) else str(conteudo)

    limpo, tipos = redigir_pii(text)

    if tipos:
        # Só os tipos, nunca o valor.
        log_info(f"guardrail PII: dados removidos ({', '.join(tipos)})")

    return StepOutput(content=limpo)


guardrails_step = Step(
    name="Guardrail PII",
    executor=_guardrail_pii_executor,
)
