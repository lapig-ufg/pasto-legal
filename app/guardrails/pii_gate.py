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
    redigir_pii(text)        -- troca dados pessoais por marcadores.
    mascarar_pii(text)       -- substitui PII por [oculto], para logs seguros.
"""

import re
from typing import Callable, Dict, List, Tuple

# =====================================================================
# Camada 0 — Exclusão de escopo conhecido
# =====================================================================
# Antes de procurar PII, tiramos do texto os identificadores que são do
# próprio sistema.
#
# Motivo: o dígito verificador é um sinal fraco — cerca de 1 em cada 100
# sequências aleatórias de 11 ou 14 dígitos passa por acaso (e 1 em 9 no
# Luhn do cartão). Então qualquer identificador longo, como o CAR com seus
# 32 caracteres hexadecimais, mais cedo ou mais tarde contém um trecho que
# parece um documento válido. Medido: 1 a cada ~3.000 códigos CAR era
# bloqueado indevidamente.
#
# Endurecer o regex não resolve essa classe de problema — só reduz a
# frequência. Removendo o trecho antes da varredura, o detector nunca
# chega a vê-lo.

# CAR (Cadastro Ambiental Rural): UF + código do município + identificador.
# Ex.: GO-5212303-27057D4194F64CE3A498B90BFAC2E5F9

_CAR_RE = re.compile(r"\b[A-Z]{2}-\d{7}-[A-F0-9]{32}\b", re.IGNORECASE)
_ESCOPO_CONHECIDO = [
    _CAR_RE,
]

def remover_escopo_conhecido(text: str) -> str:
    """Remove identificadores do próprio sistema antes da varredura de PII.

    Substitui por espaço (e não por string vazia) de propósito: sem isso, o
    que estava dos dois lados gruda e pode formar um número que não existia
    no texto original.
    """
    for rx in _ESCOPO_CONHECIDO:
        text = rx.sub(" ", text)
    return text

_NB_L = r"(?<!\d)(?<!\d[.,])"
_NB_R = r"(?!\d)(?![.,]\d)"

# --- CPF ---
# Três formas aceitas, sempre completas — nunca meio a meio:
#   pontuada  123.456.789-01
#   espaçada  123 456 789 01
#   crua      12345678901
# A forma espaçada existe porque é como muita gente digita, e sem ela o CPF
# só era pego pela camada de intenção (dependia da palavra "cpf" por perto).
_CPF_RE = re.compile(
    _NB_L
    + r"(?:\d{3}\.\d{3}\.\d{3}-\d{2}|\d{3} \d{3} \d{3} \d{2}|\d{11})"
    + _NB_R
)


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
# Mesmas três formas do CPF:
#   pontuada  12.345.678/0001-90
#   espaçada  12 345 678 0001 90
#   crua      12345678000190
_CNPJ_RE = re.compile(
    _NB_L
    + r"(?:\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}|\d{2} \d{3} \d{3} \d{4} \d{2}|\d{14})"
    + _NB_R
)

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
_CARTAO_RE = re.compile(
    _NB_L
    + r"(?:"
    r"\d{4}[ -]\d{4}[ -]\d{4}[ -]\d{1,4}"
    r"|4\d{12}(?:\d{3})?"
    r"|5[1-5]\d{14}"
    r"|3[47]\d{13}"
    r"|6(?:011|5\d{2})\d{12}"
    r")"    
    + _NB_R
)


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

    text = remover_escopo_conhecido(text)

    tipos = [tipo for tipo, detector in _DETECTORES.items() if detector(text)]
    
    # Camada de intenção: citou "cpf/cnpj/rg" e emendou número → bloqueia mesmo inválido.
    for tipo, rx in _INTENCAO_RE.items():
        if tipo not in tipos and rx.search(text):
            tipos.append(tipo)
    return tipos

# --- Redação ---
# Em vez de recusar a mensagem inteira, troca só o dado sensível por um
# marcador e deixa o resto seguir. Assim o produtor não perde os pedidos que
# fez junto, e o dado não chega ao agente nem ao banco.
_MARCADOR = {
    "CPF": "[CPF_OCULTO]",
    "CNPJ": "[CNPJ_OCULTO]",
    "cartão": "[CARTAO_OCULTO]",
    "RG": "[RG_OCULTO]",
    "e-mail": "[EMAIL_OCULTO]",
}


def redigir_pii(text: str) -> Tuple[str, List[str]]:
    """Substitui dados pessoais por marcadores.

    Devolve (texto_redigido, tipos_removidos). Se não achou nada, devolve o
    texto original e lista vazia.
    """
    if not text:
        return text, []

    # Trechos de escopo conhecido (CAR) são intocáveis: um CAR pode conter,
    # por acaso, uma sequência que valida como documento.
    protegidos = [mt.span() for rx in _ESCOPO_CONHECIDO for mt in rx.finditer(text)]

    def _protegido(ini: int, fim: int) -> bool:
        return any(ini < p_fim and fim > p_ini for p_ini, p_fim in protegidos)

    achados = []  # (inicio, fim, tipo)
    for tipo, rx in (
        ("CPF", _CPF_RE),
        ("CNPJ", _CNPJ_RE),
        ("cartão", _CARTAO_RE),
        ("RG", _RG_RE),
        ("e-mail", _EMAIL_RE),
    ):
        for mt in rx.finditer(text):
            ini, fim = mt.span()
            if _protegido(ini, fim):
                continue
            digitos = re.sub(r"\D", "", mt.group())
            # CPF, CNPJ e cartão só contam se o verificador bater.
            # RG e e-mail não têm verificador: o formato já é a evidência.
            if tipo == "CPF" and not _valida_cpf(digitos):
                continue
            if tipo == "CNPJ" and not _valida_cnpj(digitos):
                continue
            if tipo == "cartão" and not (13 <= len(digitos) <= 16 and _luhn(digitos)):
                continue
            achados.append((ini, fim, tipo))

    if not achados:
        return text, []

    # Substitui de trás para frente para os índices não saírem do lugar,
    # descartando sobreposições entre detectores.
    achados.sort(key=lambda a: a[0])
    limpo, tipos, ultimo_inicio = text, [], len(text)
    for ini, fim, tipo in reversed(achados):
        if fim > ultimo_inicio:
            continue
        limpo = limpo[:ini] + _MARCADOR[tipo] + limpo[fim:]
        tipos.append(tipo)
        ultimo_inicio = ini

    return limpo, sorted(set(tipos))


# --- Mascaramento (para logs seguros) ---

_MASCARAR_RES = [_CPF_RE, _CNPJ_RE, _CARTAO_RE, _EMAIL_RE, _RG_RE] + list(_INTENCAO_RE.values())


def mascarar_pii(text: str) -> str:
    """Substitui qualquer trecho que pareça PII por [oculto] — para logs seguros."""
    for rx in _MASCARAR_RES:
        text = rx.sub("[oculto]", text)
    return text