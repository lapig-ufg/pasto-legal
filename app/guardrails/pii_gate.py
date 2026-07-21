"""Detecção de PII (dados pessoais) na camada de ingestão do Pasto Legal.

Reúne detectores determinísticos (regex + validação de dígitos verificadores)
e uma camada de intenção, que barram documentos pessoais antes da mensagem
chegar aos agentes.

Interface externa:
    detecta_cpf(text)        -- True se o texto contém um CPF válido.
    detecta_cnpj(text)       -- True se o texto contém um CNPJ válido.
    detecta_cartao(text)     -- True se o texto contém um número de cartão válido.
    detecta_email(text)      -- True se o texto contém um endereço de e-mail.
    detecta_rg(text)         -- True se o texto contém um RG no formato pontuado.
    check_pii(text)          -- lista dos tipos de PII encontrados (vazia se limpo).
    mensagem_bloqueio(tipos) -- monta o aviso de bloqueio a partir dos tipos.
    mascarar_pii(text)       -- substitui PII por [oculto], para logs seguros.
"""

import re
from typing import Callable, Dict, List



# --- CPF ---
# Aceita CPF formatado ("123.456.789-01") e puro ("12345678901").
# Pontos e traço são opcionais (?), por isso cobre os dois formatos.
_CPF_RE = re.compile(r"\d{3}\.?\d{3}\.?\d{3}-?\d{2}")


def _valida_cpf(digitos: str) -> bool:
    """Valida os dois dígitos verificadores de um CPF (recebe só números)."""
    if len(digitos) != 11 or digitos == digitos[0] * 11:
        return False

    # 1º dígito verificador: pesos 10..2 sobre os 9 primeiros números.
    soma = sum(int(digitos[i]) * (10 - i) for i in range(9))
    resto = (soma * 10) % 11
    if resto == 10:
        resto = 0
    if resto != int(digitos[9]):
        return False

    # 2º dígito verificador: pesos 11..2 sobre os 10 primeiros números.
    soma = sum(int(digitos[i]) * (11 - i) for i in range(10))
    resto = (soma * 10) % 11
    if resto == 10:
        resto = 0
    return resto == int(digitos[10])


def detecta_cpf(text: str) -> bool:
    """Retorna True se o texto contém pelo menos um CPF válido."""
    for trecho in _CPF_RE.findall(text):
        digitos = re.sub(r"\D", "", trecho)
        if _valida_cpf(digitos):
            return True
    return False

# --- CNPJ ---
# Aceita CNPJ formatado ("12.345.678/0001-90") e puro ("12345678000190").
# Pontos, barra e traço são opcionais (?).
_CNPJ_RE = re.compile(r"\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}")

# Pesos oficiais para o cálculo dos dígitos verificadores do CNPJ.
_CNPJ_PESOS_1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
_CNPJ_PESOS_2 = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]


def _valida_cnpj(digitos: str) -> bool:
    """Valida os dois dígitos verificadores de um CNPJ (recebe só números)."""
    if len(digitos) != 14 or digitos == digitos[0] * 14:
        return False

    # 1º dígito verificador: soma ponderada dos 12 primeiros números.
    soma = sum(int(digitos[i]) * _CNPJ_PESOS_1[i] for i in range(12))
    resto = soma % 11
    dv1 = 0 if resto < 2 else 11 - resto
    if dv1 != int(digitos[12]):
        return False

    # 2º dígito verificador: soma ponderada dos 13 primeiros números.
    soma = sum(int(digitos[i]) * _CNPJ_PESOS_2[i] for i in range(13))
    resto = soma % 11
    dv2 = 0 if resto < 2 else 11 - resto
    return dv2 == int(digitos[13])


def detecta_cnpj(text: str) -> bool:
    """Retorna True se o texto contém pelo menos um CNPJ válido."""
    for trecho in _CNPJ_RE.findall(text):
        digitos = re.sub(r"\D", "", trecho)
        if _valida_cnpj(digitos):
            return True
    return False

# --- Cartão de crédito ---
# Sequência de 13 a 16 dígitos, aceitando espaços ou traços entre os grupos
# (ex.: "1234 5678 9012 3456" ou "1234-5678-9012-3456").
_CARTAO_RE = re.compile(r"\d(?:[ -]?\d){12,15}")


def _luhn(digitos: str) -> bool:
    """Valida um número de cartão pelo algoritmo de Luhn (recebe só números)."""
    soma = 0
    for i, ch in enumerate(reversed(digitos)):
        n = int(ch)
        if i % 2 == 1:          # dobra dígitos alternados, da direita p/ esquerda
            n *= 2
            if n > 9:
                n -= 9
        soma += n
    return soma % 10 == 0


def detecta_cartao(text: str) -> bool:
    """Retorna True se o texto contém um número de cartão válido (Luhn)."""
    for trecho in _CARTAO_RE.findall(text):
        digitos = re.sub(r"\D", "", trecho)
        if 13 <= len(digitos) <= 16 and _luhn(digitos):
            return True
    return False

# --- E-mail ---
# Formato padrão: usuario@dominio.extensao
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")


def detecta_email(text: str) -> bool:
    """Retorna True se o texto contém um endereço de e-mail."""
    return bool(_EMAIL_RE.search(text))


# --- RG (formato pontuado) ---
# RG não tem padrão nacional, então cobrimos só o formato claramente escrito
# (12.345.678-9). Número cru NÃO entra, pra não bloquear valores/quantidades à toa.
_RG_RE = re.compile(r"\b\d{2}\.\d{3}\.\d{3}-[\dxX]\b")


def detecta_rg(text: str) -> bool:
    """Retorna True se o texto contém um RG no formato pontuado (ex.: 12.345.678-9)."""
    return bool(_RG_RE.search(text))


# --- Intenção de documento (bloqueia mesmo número falso/inválido) ---
# Se o usuário cita o documento e emenda um número (ex.: "meu cpf é 322443"),
# bloqueamos mesmo que o número não seja válido — a intenção já é enviar o dado.
_INTENCAO_RE = {
    "CPF":    re.compile(r"\bcpf\b.{0,12}?\d{3,}|\d{3,}.{0,12}?\bcpf\b", re.IGNORECASE),
    "CNPJ":   re.compile(r"\bcnpj\b.{0,12}?\d{3,}|\d{3,}.{0,12}?\bcnpj\b", re.IGNORECASE),
    "RG":     re.compile(r"\brg\b.{0,12}?\d{3,}|\d{3,}.{0,12}?\brg\b", re.IGNORECASE),
    "cartão": re.compile(r"\bcart[ãa]o\b.{0,12}?\d{3,}|\d{3,}.{0,12}?\bcart[ãa]o\b", re.IGNORECASE),
}
# --- Orquestrador ---

_DETECTORES: Dict[str, Callable[[str], bool]] = {
    "CPF": detecta_cpf,
    "CNPJ": detecta_cnpj,
    "cartão": detecta_cartao,
    "e-mail": detecta_email,
     "RG": detecta_rg,
}


def check_pii(text: str) -> List[str]:
    """Tipos de PII no texto: documentos válidos + intenção clara de enviar documento."""
    tipos = [tipo for tipo, detector in _DETECTORES.items() if detector(text)]
    # Camada de intenção: citou "cpf/cnpj/rg" e emendou número → bloqueia mesmo inválido.
    for tipo, rx in _INTENCAO_RE.items():
        if tipo not in tipos and rx.search(text):
            tipos.append(tipo)
    return tipos

# --- Mensagem de bloqueio ---
_AVISO_BASE = (
    "🔒 Para sua segurança e proteção de dados, não envie documentos pessoais "
    "no chat (detectei: {tipos}). Por favor, reescreva sua mensagem sem esses dados."
)


def mensagem_bloqueio(tipos: List[str]) -> str:
    """Monta o aviso de bloqueio citando os tipos de PII encontrados."""
    return _AVISO_BASE.format(tipos=", ".join(tipos))


# --- Mascaramento (para logs seguros) ---

_MASCARAR_RES = [_CPF_RE, _CNPJ_RE, _CARTAO_RE, _EMAIL_RE, _RG_RE] + list(_INTENCAO_RE.values())


def mascarar_pii(text: str) -> str:
    """Substitui qualquer trecho que pareça PII por [oculto] — para logs seguros."""
    for rx in _MASCARAR_RES:
        text = rx.sub("[oculto]", text)
    return text