"""Testes unitários do guardrail de PII (app/guardrails/pii_gate.py).

Cobrem os detectores determinísticos, o RG por formato, a camada de intenção,
o orquestrador, a mensagem e o mascaramento. Tudo determinístico — sem LLM/rede.
"""

from semente.guardrails.pii_gate import (
    detecta_cpf, detecta_cnpj, detecta_cartao, detecta_email, detecta_rg,
    check_pii, mensagem_bloqueio, mascarar_pii,
)


# --- CPF ---
def test_cpf_valido_formatado():
    assert detecta_cpf("meu cpf é 006.819.915-50")

def test_cpf_valido_puro():
    assert detecta_cpf("00681991550")

def test_cpf_digito_invalido():
    assert not detecta_cpf("111.444.777-00")

def test_cpf_nao_confunde_telefone():
    assert not detecta_cpf("meu telefone é 62999998888")

def test_cpf_repetido():
    assert not detecta_cpf("111.111.111-11")


# --- CNPJ ---
def test_cnpj_valido():
    assert detecta_cnpj("CNPJ 27.486.358/0001-22")

def test_cnpj_valido_puro():
    assert detecta_cnpj("27486358000122")

def test_cnpj_invalido():
    assert not detecta_cnpj("11.222.333/0001-00")


# --- Cartão ---
def test_cartao_valido_luhn():
    assert detecta_cartao("cartão 4570 7318 2800 8591")

def test_cartao_luhn_invalido():
    assert not detecta_cartao("4570 7318 2800 8592")

def test_cartao_curto():
    assert not detecta_cartao("o ano é 2024")


# --- E-mail ---
def test_email_valido():
    assert detecta_email("me chama no joao.silva@gmail.com")

def test_email_sem_arroba():
    assert not detecta_email("arroba solto sem email")


# --- RG (formato pontuado) ---
def test_rg_formatado():
    assert detecta_rg("meu rg é 12.345.678-9")

def test_rg_cru_nao_pega():
    assert not detecta_rg("tenho 123456789 cabeças")


# --- Intenção (bloqueia número falso quando cita o documento) ---
def test_intencao_cpf_falso():
    assert "CPF" in check_pii("meu cpf é 322443")

def test_intencao_numero_antes():
    assert "CPF" in check_pii("321312 e meu cpf")

def test_intencao_cartao():
    assert "cartão" in check_pii("meu cartao e 1234")

def test_intencao_numero_distante_nao_pega():
    assert check_pii("meu cpf tá no cadastro, tenho 500 cabeças") == []


# --- Orquestrador ---
def test_check_pii_multiplos():
    tipos = check_pii("cpf 006.819.915-50 e email joao@gmail.com")
    assert "CPF" in tipos and "e-mail" in tipos

def test_check_pii_limpo():
    assert check_pii("quero ver o mapa da minha fazenda") == []


# --- Mensagem e mascaramento ---
def test_mensagem_cita_tipos():
    msg = mensagem_bloqueio(["CPF", "e-mail"])
    assert "CPF" in msg and "e-mail" in msg

def test_mascarar_oculta_pii():
    mascarado = mascarar_pii("meu cpf é 006.819.915-50")
    assert "006.819.915-50" not in mascarado and "[oculto]" in mascarado