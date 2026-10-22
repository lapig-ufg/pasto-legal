"""Brazil-specific PII guards — domain material of Pasto Legal.

Semente is a domain-neutral framework: CPF/CNPJ/RG shape recognition and the
Portuguese intent layer are Brazil/LGPD specifics, not framework material.
They live here, one blocking guard per document type, on the
:class:`semente.guardrails.RegexGuardrail` base.

Policy — these guards *block* the turn (the agent never runs) instead of
redacting, because these are the user's personal documents; a refusal with a
clear reply is safer than silently editing the message::

    from domain.guardrails import CpfGuardrail, CnpjGuardrail, RgGuardrail

    domain_spec = DomainSpec(
        name="Pasto Legal",
        tools=[...],
        guardrails=[CpfGuardrail(), CnpjGuardrail(), RgGuardrail()],
    )

Detection is **shape-only** — no check-digit validation: any well-formed
number is treated as the document (users mistype digits; the intent to share
a document is what matters, not the check digit).

Trade-offs accepted by this policy (measured on the old validated detector):

- A bare 11- or 14-digit integer is treated as CPF/CNPJ — implausible as
  legitimate data in this domain, so no keyword is required. The one
  plausible exception — an unformatted **phone** number (DDD + 9 digits,
  11 digits, e.g. "62999998888") — is excused when a phone/WhatsApp hint
  ("telefone", "celular", "whatsapp", "fone", "contato", "phone") appears
  right before the number. The dotted form cannot look like a phone and
  needs no keyword.
- The **spaced** form ("123 456 789 01") is keyword-only: without the check
  digit it also matches innocent sequences ("it rained 120 130 140 15 mm").
  With a keyword nearby ("cpf", "cnpj", "rg") the intent layer still blocks
  it — that is also how partial/invalid numbers get caught.
- Known-scope spans (the CAR codes this system itself emits) are untouchable
  — their hex strings can by chance contain an 11-digit run ("Layer 0").
"""

from __future__ import annotations

import re

from semente.guardrails import (
    GuardrailContext,
    GuardrailResult,
    RegexGuardrail,
)

# =====================================================================
# Layer 0 — exclusion of known scope
# =====================================================================
#
# The check digit is a weak signal, and now there is none at all: any long
# identifier (the CAR, with its 32 hexadecimal characters) sooner or later
# contains a stretch of digits that looks like a document. Measured on the
# validated detector: 1 in ~3,000 CAR codes was being blocked wrongly;
# without validation the rate is orders of magnitude higher.
#
# So spans that belong to the system itself are excused from every detector.

# CAR (Rural Environmental Registry): state (UF) code + municipality code + identifier.
# E.g.: GO-5212303-27057D4194F64CE3A498B90BFAC2E5F9
_CAR_RE = re.compile(r"\b[A-Z]{2}-\d{7}-[A-F0-9]{32}\b", re.IGNORECASE)
_KNOWN_SCOPE = (
    _CAR_RE,
)


def remove_known_scope(text: str) -> str:
    """Removes the system's own identifiers from the text (Layer 0, for tests/tools).

    Replaces with a space (and not with an empty string) on purpose: without
    that, whatever was on both sides glues together and can form a number
    that did not exist in the original text.
    """
    for rx in _KNOWN_SCOPE:
        text = rx.sub(" ", text)
    return text


_NB_L = r"(?<!\d)(?<!\d[.,])"
_NB_R = r"(?!\d)(?![.,]\d)"

# Unformatted phone numbers share the raw 11-digit shape with the CPF
# (DDD + 9-digit mobile, e.g. "62999998888"). When a phone/WhatsApp hint
# appears right before an otherwise plain number, the number is a contact,
# not a document — excused from the raw-shape form.
_PHONE_HINT_RE = re.compile(
    r"(?:telefon|celular|whatsapp|whats|phone|fone|contato)[^\n]{0,24}$",
    re.IGNORECASE,
)

# --- Document intent (catches a partial/fake number too) ---
# If the user mentions the document and appends a number (e.g.: "my cpf is 322443"),
# we block even if the number is short — the intent is already to send the data.
# This is also the only way the spaced form fires (see the trade-offs above).


def _intent_re(word: str) -> re.Pattern:
    return re.compile(
        rf"\b{word}\b.{{0,12}}?\d{{3,}}|\d{{3,}}.{{0,12}}?\b{word}\b",
        re.IGNORECASE,
    )


# =====================================================================
# The blocking guardrail base — one concrete guard per document type
# =====================================================================


class _BlockedDocumentGuardrail(RegexGuardrail):
    """Blocks the turn when the document appears in the input.

    Subclasses set: ``name``, ``marker``, ``patterns`` (shape + intent
    regexes), and ``response``. When a span matches, the guard redacts the
    span with its marker (safety for downstream logs/persistence) and
    refuses the turn with its ``response`` — the agent never runs.

    The base ``mask`` (safe log masking) is inherited; it uses the same
    findings, so it never masks a CAR span.
    """

    protected: tuple[re.Pattern, ...] = _KNOWN_SCOPE
    phone_exempt: tuple[re.Pattern, ...] = ()
    response: str = ""

    def _findings(self, text: str) -> list[tuple[int, int]]:
        """Match spans, minus phone contexts and the system's own identifiers.

        Mirrors the base merge (no validators on the Brazil guards), adding:
        phone-exempt patterns are dropped when a phone/WhatsApp hint sits
        right before the match, and spans overlapping a known-scope
        identifier (the CAR) are excused.
        """
        spans: list[tuple[int, int]] = []
        for rx in self.patterns:
            phone_exempt = rx in self.phone_exempt
            for match in rx.finditer(text):
                start, end = match.span()
                if phone_exempt and _PHONE_HINT_RE.search(text[max(0, start - 24) : start]):
                    continue
                spans.append((start, end))
        if not spans:
            return []
        spans.sort()
        merged = [spans[0]]
        for start, end in spans[1:]:
            last_start, last_end = merged[-1]
            if start < last_end:
                merged[-1] = (last_start, max(last_end, end))
            else:
                merged.append((start, end))
        if not self.protected:
            return merged
        protected_spans = [
            mt.span() for rx in self.protected for mt in rx.finditer(text)
        ]
        return [
            (start, end)
            for start, end in merged
            if not any(
                start < p_end and end > p_start
                for p_start, p_end in protected_spans
            )
        ]

    def redact(self, context: GuardrailContext) -> GuardrailResult:
        text = context.text or ""
        spans = self._findings(text)
        if not spans:
            return GuardrailResult(text=text)
        clean = text
        for start, end in reversed(spans):
            clean = clean[:start] + self.marker + clean[end:]
        return GuardrailResult(
            text=clean,
            removed=[self.name],
            blocked=True,
            response=self.response,
        )


# --- CPF ---
# Dotted (123.456.789-01), raw (12345678901): shape alone.
# Spaced (123 456 789 01): keyword only, via the intent layer.
_CPF_DOC_RE = re.compile(_NB_L + r"\d{3}\.\d{3}\.\d{3}-\d{2}" + _NB_R)
_CPF_RAW_RE = re.compile(_NB_L + r"\d{11}" + _NB_R)

_CPF_RESPONSE = (
    "Detectei um número de CPF na sua mensagem. Por segurança dos seus dados "
    "(LGPD), não posso processar documentos pessoais. Por favor, remova o "
    "número e envie a mensagem novamente."
)


class CpfGuardrail(_BlockedDocumentGuardrail):
    """Blocks the turn when a CPF (or a 'cpf … <number>' mention) appears.

    The raw form (plain 11 digits) is phone-exempt: with a phone/WhatsApp
    hint right before it, it is treated as a contact number.
    """

    name = "cpf"
    marker = "[CPF_HIDDEN]"
    response = _CPF_RESPONSE
    patterns = (
        _CPF_DOC_RE,
        _CPF_RAW_RE,
        _intent_re("cpf"),
    )
    phone_exempt = (_CPF_RAW_RE,)


# --- CNPJ ---
# Dotted (12.345.678/0001-90), raw (12345678000190): shape alone.
# Spaced: keyword only.
_CNPJ_DOC_RE = re.compile(_NB_L + r"\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}" + _NB_R)
_CNPJ_RAW_RE = re.compile(_NB_L + r"\d{14}" + _NB_R)

_CNPJ_RESPONSE = (
    "Detectei um número de CNPJ na sua mensagem. Por segurança dos seus dados "
    "(LGPD), não posso processar documentos pessoais. Por favor, remova o "
    "número e envie a mensagem novamente."
)


class CnpjGuardrail(_BlockedDocumentGuardrail):
    """Blocks the turn when a CNPJ (or a 'cnpj … <number>' mention) appears."""

    name = "cnpj"
    marker = "[CNPJ_HIDDEN]"
    response = _CNPJ_RESPONSE
    patterns = (
        _CNPJ_DOC_RE,
        _CNPJ_RAW_RE,
        _intent_re("cnpj"),
    )


# --- RG ---
# No national pattern, so only the clearly written format (12.345.678-9) —
# the format itself is the evidence (no check digit to validate).
_RG_DOC_RE = re.compile(r"\b\d{2}\.\d{3}\.\d{3}-[\dxX]\b")

_RG_RESPONSE = (
    "Detectei um número de RG na sua mensagem. Por segurança dos seus dados "
    "(LGPD), não posso processar documentos pessoais. Por favor, remova o "
    "número e envie a mensagem novamente."
)


class RgGuardrail(_BlockedDocumentGuardrail):
    """Blocks the turn when an RG in the punctuated format appears."""

    name = "rg"
    marker = "[RG_HIDDEN]"
    response = _RG_RESPONSE
    patterns = (_RG_DOC_RE, _intent_re("rg"))


__all__ = [
    "CpfGuardrail",
    "CnpjGuardrail",
    "RgGuardrail",
]