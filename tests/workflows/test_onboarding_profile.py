"""Testes do portão de onboarding de perfil (issue #148).

Cobrem `_needs_onboarding`, que decide se o usuário vai para o welcoming
agent ou segue para o fluxo normal. O portão precisa exigir três coisas —
aceite dos termos, nome e função — e, quando todas existem no banco,
carregar o perfil no session_state para o agente personalizar a resposta.

Roda com:  PYTHONPATH=. .venv/bin/pytest tests/test_onboarding_profile.py -v
"""

import datetime
from dataclasses import dataclass
from typing import Any, Optional

import pytest

from app.database.models import UserProfile, UserTermsAcceptance
from app.database.session import SessionLocal, engine
from app.workflows.onboarding_gate import _needs_onboarding


UID = "test:onboarding:5562900000000"


# ---------------------------------------------------------------------
# Dublês: o portão só lê `step_input.workflow_session.user_id`, então não
# é preciso montar um StepInput de verdade do agno.
# ---------------------------------------------------------------------
@dataclass
class _FakeWorkflowSession:
    user_id: Optional[str]


@dataclass
class _FakeStepInput:
    workflow_session: Optional[_FakeWorkflowSession] = None


def _entrada(user_id: Optional[str] = UID) -> _FakeStepInput:
    return _FakeStepInput(workflow_session=_FakeWorkflowSession(user_id=user_id))


# ---------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------
@pytest.fixture
def db():
    """Sessão de banco limpa antes e depois de cada teste."""
    UserProfile.metadata.create_all(bind=engine)
    sessao = SessionLocal()
    _limpar(sessao)
    yield sessao
    _limpar(sessao)
    sessao.close()


def _limpar(sessao) -> None:
    sessao.query(UserProfile).filter(UserProfile.user_id == UID).delete()
    sessao.query(UserTermsAcceptance).filter(UserTermsAcceptance.user_id == UID).delete()
    sessao.commit()


def _aceitar_termos(sessao) -> None:
    sessao.add(UserTermsAcceptance(
        user_id=UID, accepted=True, accepted_at=datetime.datetime.utcnow(),
    ))
    sessao.commit()


def _gravar_perfil(sessao, name=None, role=None) -> None:
    sessao.add(UserProfile(user_id=UID, name=name, role=role))
    sessao.commit()


# ---------------------------------------------------------------------
# Cenários
# ---------------------------------------------------------------------
def test_sem_user_id_pede_onboarding(db):
    """Sem identificador não há como consultar o banco: erra pelo seguro."""
    estado: dict[str, Any] = {}
    assert _needs_onboarding(_entrada(user_id=None), estado) is True


def test_usuario_novo_pede_onboarding(db):
    """Nada no banco, nada na sessão."""
    estado: dict[str, Any] = {}
    assert _needs_onboarding(_entrada(), estado) is True


def test_termos_aceitos_sem_perfil_pede_onboarding(db):
    """O bug clássico: aceitou os termos e passaria direto sem se identificar."""
    _aceitar_termos(db)
    estado: dict[str, Any] = {}
    assert _needs_onboarding(_entrada(), estado) is True
    assert estado["terms_accepted"] is True  # o aceite foi reconhecido


def test_perfil_incompleto_pede_onboarding(db):
    """Deu o nome e sumiu antes da função."""
    _aceitar_termos(db)
    _gravar_perfil(db, name="João")
    estado: dict[str, Any] = {}
    assert _needs_onboarding(_entrada(), estado) is True


def test_perfil_completo_libera_e_carrega_na_sessao(db):
    """O caso que a issue #148 existe para resolver.

    Usuário que já passou pelo onboarding volta numa sessão nova e vazia.
    O portão tem que reconhecê-lo pelo banco E entregar o perfil ao agente.
    """
    _aceitar_termos(db)
    _gravar_perfil(db, name="João", role="Produtor")
    estado: dict[str, Any] = {}

    assert _needs_onboarding(_entrada(), estado) is False

    assert estado["user_persona"]["name"] == "João"
    assert estado["user_persona"]["role"] == "Produtor"


def test_sessao_completa_nao_consulta_o_banco(db):
    """Atalho de desempenho: com tudo na sessão, não vai ao banco.

    Nada foi gravado no banco neste teste. Se o portão fosse consultá-lo,
    não acharia perfil e devolveria True.
    """
    estado: dict[str, Any] = {
        "terms_accepted": True,
        "user_persona": {"name": "João", "role": "Produtor"},
    }
    assert _needs_onboarding(_entrada(), estado) is False


def test_sessao_nao_sobrescreve_nome_recem_gravado(db):
    """A tool acabou de mudar o nome na sessão; o banco ainda tem o antigo."""
    _aceitar_termos(db)
    _gravar_perfil(db, name="João", role="Produtor")
    estado: dict[str, Any] = {"user_persona": {"name": "Zé do Pasto"}}

    assert _needs_onboarding(_entrada(), estado) is False
    assert estado["user_persona"]["name"] == "Zé do Pasto"
    assert estado["user_persona"]["role"] == "Produtor"


def test_persona_sentinela_no_banco_incompleto_pede_onboarding(db):
    """Persona com o valor-sentinela do schema não conta como preenchida.

    O `UserPersona` usa "Ainda não conhecido" como default, então uma persona
    montada a partir do schema parece preenchida mas não é. Sem banco, segue
    pedindo onboarding.
    """
    _aceitar_termos(db)
    estado: dict[str, Any] = {
        "user_persona": {"name": "Ainda não conhecido", "role": "Ainda não conhecido"},
    }
    assert _needs_onboarding(_entrada(), estado) is True


def test_sentinela_na_sessao_e_preenchida_pelo_banco(db):
    """Sentinela na sessão + perfil completo no banco: libera e cura a sessão.

    O portão precisa reconhecer que o sentinela não é um nome real, buscar o
    perfil no banco e sobrescrever os campos sentinela — não apenas preencher
    chaves ausentes.
    """
    _aceitar_termos(db)
    _gravar_perfil(db, name="João", role="Produtor")
    estado: dict[str, Any] = {
        "user_persona": {"name": "Ainda não conhecido", "role": "Ainda não conhecido"},
    }

    assert _needs_onboarding(_entrada(), estado) is False
    assert estado["user_persona"]["name"] == "João"
    assert estado["user_persona"]["role"] == "Produtor"


def test_perfil_parcial_sentinela_e_preenchido_sem_apagar_sessao(db):
    """Nome real na sessão + função sentinela: o banco preenche só a função."""
    _aceitar_termos(db)
    _gravar_perfil(db, name="João", role="Técnico")
    estado: dict[str, Any] = {
        "user_persona": {"name": "Zé do Pasto", "role": "Ainda não conhecido"},
    }

    assert _needs_onboarding(_entrada(), estado) is False
    assert estado["user_persona"]["name"] == "Zé do Pasto"
    assert estado["user_persona"]["role"] == "Técnico"
