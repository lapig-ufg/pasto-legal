"""Testes unitários do guardrail de PII (app/guardrails/pii_gate.py).

Cobrem os detectores determinísticos, o RG por formato, a camada de intenção,
o orquestrador, a mensagem, o mascaramento e as regressões de falso positivo
em coordenadas geográficas e códigos CAR. Tudo determinístico — sem LLM/rede.
"""

import random

import pytest

from app.guardrails.pii_gate import (
    detecta_cpf, detecta_cnpj, detecta_cartao, detecta_email, detecta_rg,
    check_pii, mascarar_pii, redigir_pii, remover_escopo_conhecido,
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


# --- Mascaramento ---
def test_mascarar_oculta_pii():
    mascarado = mascarar_pii("meu cpf é 006.819.915-50")
    assert "006.819.915-50" not in mascarado and "[oculto]" in mascarado

# =====================================================================
# Regressão: identificadores do domínio não são documentos
# =====================================================================
# Contexto (medido, não suposto):
#   - dígito verificador do CPF  → 1 em 103 sequências de 11 dígitos passa
#   - dígito verificador do CNPJ → 1 em 100 sequências de 14 dígitos passa
#   - Luhn do cartão             → 1 em 9 sequências de 16 dígitos passa
#
# Ou seja, o validador é quase um cara-ou-coroa. Qualquer identificador longo
# (coordenada de alta precisão, código CAR) contém, cedo ou tarde, um trecho
# que "valida" por acaso. Antes das guardas de fronteira e da Camada 0:
#   - 21,6% dos pinos de localização eram bloqueados
#   -  0,8% dos códigos CAR eram bloqueados

# Casos reais reportados em campo, na seleção de CAR.
COORD_UMA_PROPRIEDADE = "47,1798509°W 19,5350942°S"
COORD_DUAS_PROPRIEDADES = "42,1343264°W 17,3386047°S"
COORD_TRES_CARS = "-52.50857591629029, -5.935149162520979"

# Códigos CAR que davam falso positivo antes da Camada 0.
CAR_FALSO_POSITIVO = [
    "BA-3287819-4845970474100364E5587A1F37A75AC3",   # casava como cartão
    "RO-1708070-D811A2AC67B370794126616945A35974",   # casava como cartão
    "TO-5367207-8E7A3510FBBC929BBBB32361861437E8",   # casava como CPF
    "MS-3779009-B2F7F7C7F16D4B5BC89965149090355B",   # casava como CNPJ
    "MT-4750161-C69210318617B554911562D859B399AE",   # casava como CPF
    "GO-4237547-A56925079940F78341EA1054FF4F40B5",   # casava como CPF
]

NAO_DEVE_BLOQUEAR = [
    COORD_UMA_PROPRIEDADE,
    COORD_DUAS_PROPRIEDADES,
    COORD_TRES_CARS,
    "Quero registrar minha propriedade nas coordenadas Lat: -5.935149162520979 Long: -52.50857591629029.",
    "minha fazenda fica em -16.3107, -43.8839",
    "GO-5212303-27057D4194F64CE3A498B90BFAC2E5F9",
    "go-5212303-27057d4194f64ce3a498b90bfac2e5f9",
    "quero unificar GO-5205703-5B18B6DF441C4B7FA9444DDC127CF6C0 e GO-5212303-27057D4194F64CE3A498B90BFAC2E5F9",
    "tenho 1.234,56 hectares de pasto",
    "a area total e 1.234.567,89 hectares",
    "produzi 12345678901234 kg de silagem",
    "meu talhao e o 987654321098765",
    "o boleto e 34191790010104351004791020150008291070026000",
    "comprei 250 cabecas a 2.850,00 cada",
    "chuveu 120 130 140 15 mm",
    "meu telefone e 62 99999-8888",
    "quero ver o mapa da minha fazenda",
]

DEVE_BLOQUEAR = [
    ("meu cpf é 710.768.971-18", "CPF"),
    ("71076897118", "CPF"),
    ("meu cpf é 71076897118.", "CPF"),
    ("710 768 971 18", "CPF"),
    ("CNPJ 27.486.358/0001-22", "CNPJ"),
    ("27486358000122", "CNPJ"),
    ("27 486 358 0001 22", "CNPJ"),
    ("meu rg é 12.345.678-9", "RG"),
    ("cartão 4570 7318 2800 8591", "cartão"),
    ("4111111111111111", "cartão"),
    ("me chama no joao.silva@gmail.com", "e-mail"),
    ("meu cpf é 322443", "CPF"),
]


@pytest.mark.parametrize("texto", NAO_DEVE_BLOQUEAR)
def test_nao_deve_bloquear(texto):
    assert check_pii(texto) == [], f"falso positivo em: {texto}"


@pytest.mark.parametrize("texto,tipo", DEVE_BLOQUEAR)
def test_deve_bloquear(texto, tipo):
    assert tipo in check_pii(texto), f"falso negativo em: {texto}"


@pytest.mark.parametrize("car", CAR_FALSO_POSITIVO)
def test_car_nao_bloqueia(car):
    """Cada um destes bloqueava antes da Camada 0."""
    assert check_pii(car) == []


# --- Guarda de fronteira: documento é token inteiro, não fragmento ---
def test_cpf_com_ponto_final_de_frase():
    """O ponto final não pode ser confundido com separador decimal."""
    assert detecta_cpf("meu cpf é 71076897118.")


def test_cpf_dentro_de_numero_maior_nao_conta():
    assert not detecta_cpf("9971076897118")


def test_cnpj_dentro_de_numero_maior_nao_conta():
    assert not detecta_cnpj("123456780001957")
    assert not detecta_cnpj("9927486358000122")


def test_cartao_cru_sem_bandeira_nao_conta():
    """13-16 dígitos + Luhn é ruído: 1 em 9 passa por acaso."""
    assert not detecta_cartao("50857591629029")


def test_cartao_com_bandeira_real_conta():
    assert detecta_cartao("4111111111111111")


# --- Formato espaçado (o CPF só era pego pela camada de intenção) ---
def test_cpf_espacado_pega_sem_palavra_chave():
    assert detecta_cpf("710 768 971 18")
    assert detecta_cpf("meu documento e 710 768 971 18")


def test_cnpj_espacado_pega_sem_palavra_chave():
    assert detecta_cnpj("27 486 358 0001 22")


def test_espacado_invalido_nao_conta():
    """Um dígito errado deixa de ser documento e vira número avulso."""
    assert not detecta_cpf("710 768 971 19")


# --- Camada 0 ---
def test_camada_zero_nao_engole_documento():
    """Remover escopo conhecido não pode apagar PII de verdade."""
    assert check_pii(remover_escopo_conhecido("meu cpf é 710.768.971-18")) == ["CPF"]


def test_camada_zero_preserva_texto_sem_car():
    texto = "quero ver a biomassa da minha fazenda"
    assert remover_escopo_conhecido(texto) == texto


def test_car_e_cpf_na_mesma_mensagem():
    """O CAR sai da varredura, o CPF continua sendo pego."""
    texto = "cadastra GO-5212303-27057D4194F64CE3A498B90BFAC2E5F9 e meu cpf é 710.768.971-18"
    assert "CPF" in check_pii(texto)


# --- Testes estatísticos: o falso positivo era probabilístico ---
def test_falso_positivo_em_coordenadas():
    """Nenhum pino de localização no Brasil pode ser bloqueado."""
    rng = random.Random(7)
    bloqueadas = [
        t for _ in range(5000)
        for t in [f"Lat: {rng.uniform(-33.0, 5.0)} Long: {rng.uniform(-74.0, -34.0)}"]
        if check_pii(t)
    ]
    assert not bloqueadas, f"{len(bloqueadas)} bloqueadas, ex: {bloqueadas[:3]}"


def test_falso_positivo_em_codigos_car():
    """Antes da Camada 0, ~1 a cada 3.000 CARs era bloqueado."""
    rng = random.Random(42)
    ufs = ["GO", "MT", "MS", "MG", "BA", "PA", "TO", "SP", "PR", "RO"]
    bloqueados = []
    for _ in range(5000):
        car = (
            f"{rng.choice(ufs)}-{rng.randint(1000000, 9999999)}-"
            + "".join(rng.choice("0123456789ABCDEF") for _ in range(32))
        )
        if check_pii(car):
            bloqueados.append(car)
    assert not bloqueados, f"{len(bloqueados)} bloqueados, ex: {bloqueados[:3]}"


# --- Mascaramento continua permissivo de propósito ---
def test_mascaramento_continua_agressivo():
    """No log, mascarar demais é barato; mascarar de menos é vazamento."""
    assert "[oculto]" in mascarar_pii("27486358000122")
    assert "[oculto]" in mascarar_pii("meu cpf é 006.819.915-50")
