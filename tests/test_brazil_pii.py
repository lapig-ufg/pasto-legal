"""Unit tests for the Brazil-specific PII guardrails (blocking, per type).

They cover the shape-only detection (no check-digit validation), the pt-BR
intent layer, the CAR known-scope protection, log masking, blocking
semantics (``GuardrailResult.blocked`` + ``response``), and the
false-positive regressions on geographic coordinates and CAR codes.
Fully deterministic — no LLM/network.

The guardrail module is loaded by file path on purpose: importing it through
the ``domain`` package would execute ``domain/__init__.py`` (knowledge base,
tools, prompts) — heavyweight side effects a unit test must not require.
"""

import importlib.util
import pathlib
import random

import pytest

_MODULE_PATH = (
    pathlib.Path(__file__).resolve().parents[1]
    / "domain/guardrails/brazil_pii.py"
)
_spec = importlib.util.spec_from_file_location("brazil_pii", _MODULE_PATH)
brazil_pii = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(brazil_pii)

from semente.guardrails import CardGuardrail, EmailGuardrail, GuardrailChain, GuardrailContext

CpfGuardrail = brazil_pii.CpfGuardrail
CnpjGuardrail = brazil_pii.CnpjGuardrail
RgGuardrail = brazil_pii.RgGuardrail
remove_known_scope = brazil_pii.remove_known_scope


def _chain() -> GuardrailChain:
    """The Brazil guards, as the domain declares them (email/card excluded)."""
    return GuardrailChain([CpfGuardrail(), CnpjGuardrail(), RgGuardrail()])


def _decide(guard, text: str):
    return guard.redact(GuardrailContext(text=text))


def _decide_chain(text: str):
    return _chain().redact(GuardrailContext(text=text))


# =====================================================================
# CPF
# =====================================================================
def test_cpf_dotted_blocked():
    assert _decide(CpfGuardrail(), "my cpf is 710.768.971-18").blocked

def test_cpf_raw_blocked():
    assert _decide(CpfGuardrail(), "71076897118").blocked

def test_cpf_invalid_check_digit_also_blocked():
    """No check-digit validation: a well-formed number is the intent."""
    assert _decide(CpfGuardrail(), "111.444.777-00").blocked
    assert _decide(CpfGuardrail(), "111.111.111-11").blocked

def test_cpf_not_confused_with_phone():
    assert not _decide(CpfGuardrail(), "my phone is 62999998888").blocked
    assert not _decide(CpfGuardrail(), "call me on whatsapp 62999998888").blocked

def test_cpf_inside_larger_number_not_caught():
    assert not _decide(CpfGuardrail(), "9971076897118").blocked

def test_cpf_with_sentence_final_period():
    """The trailing sentence period must not be mistaken for a decimal separator."""
    assert _decide(CpfGuardrail(), "my cpf is 71076897118.").blocked

def test_cpf_spaced_with_keyword_blocked():
    assert _decide(CpfGuardrail(), "my cpf is 710 768 971 18").blocked

def test_cpf_spaced_without_keyword_not_caught():
    """Keyword-only spaced form: without 'cpf/cnpj/rg' nearby it is not evidence.

    Without the check digit, the spaced form also matches innocent sequences
    ("it rained 120 130 140 15 mm") — keyword context is what keeps it safe.
    """
    assert not _decide(CpfGuardrail(), "710 768 971 18").blocked
    assert not _decide(CpfGuardrail(), "my document is 710 768 971 18").blocked


# =====================================================================
# CNPJ
# =====================================================================
def test_cnpj_dotted_blocked():
    assert _decide(CnpjGuardrail(), "CNPJ 27.486.358/0001-22").blocked

def test_cnpj_raw_blocked():
    assert _decide(CnpjGuardrail(), "27486358000122").blocked

def test_cnpj_invalid_check_digit_also_blocked():
    assert _decide(CnpjGuardrail(), "11.222.333/0001-00").blocked

def test_cnpj_inside_larger_number_not_caught():
    assert not _decide(CnpjGuardrail(), "123456780001957").blocked
    assert not _decide(CnpjGuardrail(), "9927486358000122").blocked

def test_cnpj_spaced_with_keyword_blocked():
    assert _decide(CnpjGuardrail(), "cnpj 27 486 358 0001 22").blocked


# =====================================================================
# RG
# =====================================================================
def test_rg_dotted_blocked():
    assert _decide(RgGuardrail(), "my rg is 12.345.678-9").blocked

def test_rg_raw_not_caught():
    assert not _decide(RgGuardrail(), "I have 123456789 head of cattle").blocked


# =====================================================================
# Intent layer (catches a partial/fake number when the doc is mentioned)
# =====================================================================
def test_intent_fake_cpf_blocked():
    assert _decide(CpfGuardrail(), "my cpf is 322443").blocked

def test_intent_number_first_blocked():
    assert _decide(CpfGuardrail(), "321312 and my cpf").blocked

def test_intent_distant_number_not_caught():
    assert not _decide(CpfGuardrail(), "my cpf is on file, I have 500 head").blocked


# =====================================================================
# Blocking semantics (the interface the harness uses to skip the agent)
# =====================================================================
def test_blocking_result_shape():
    result = _decide(CpfGuardrail(), "my cpf is 710.768.971-18, what is the system version?")
    assert result.blocked
    assert result.response  # a user-facing refusal exists
    assert "710.768.971-18" not in result.text
    assert result.removed == ["cpf"]


def test_clean_input_passes_through_untouched():
    text = "I want to see the map of my farm"
    result = _decide_chain(text)
    assert not result.blocked
    assert result.text == text
    assert result.removed == []


def test_chain_blocks_and_reports_one_removed_per_guard():
    result = _decide_chain(
        "cpf 006.819.915-50 and document 27486358000122"
    )
    assert result.blocked
    assert result.response
    assert result.removed == ["cpf", "cnpj"]


def test_chain_blocks_with_the_first_blocked_response():
    result = _decide_chain("cpf 006.819.915-50 cnpj 27486358000122")
    assert result.blocked
    assert result.response == CpfGuardrail().response


def test_rg_blocked_by_chain():
    result = _decide_chain("my rg is 12.345.678-9")
    assert result.blocked
    assert "[RG_HIDDEN]" in result.text
    assert result.removed == ["rg"]


def test_blocked_turn_still_sanitized_for_logs():
    """Even blocked, the text carries only markers — never the document."""
    result = _decide_chain("my cpf is 710.768.971-18 and my rg is 12.345.678-9")
    assert result.blocked
    assert "710" not in result.text
    assert "[CPF_HIDDEN]" in result.text
    assert "[RG_HIDDEN]" in result.text


def test_sanitize_json_through_chain():
    chain = _chain()
    data = chain.sanitize_json({"note": "my rg is 12.345.678-9", "n": 5})
    # The intent span ("rg is 12.345.678-9") is replaced whole — persistence
    # sanitization over-masks on purpose.
    assert data["note"] == "my [RG_HIDDEN]"
    assert data["n"] == 5


def test_composed_with_framework_builtins():
    """Brazil blocks; email/card keep the framework's redact behavior."""
    chain = GuardrailChain(
        [CpfGuardrail(), CnpjGuardrail(), RgGuardrail(), EmailGuardrail()]
    )
    result = chain.redact(
        GuardrailContext(text="cpf 006.819.915-50 and email joao@gmail.com")
    )
    assert result.blocked
    assert "[CPF_HIDDEN]" in result.text
    assert "[EMAIL_HIDDEN]" in result.text
    assert result.removed == ["cpf", "email"]


def test_masking_stays_aggressive():
    """In logs, over-masking is cheap; under-masking is a leak."""
    chain = _chain()
    assert "[hidden]" in chain.mask("27486358000122")
    assert "[hidden]" in chain.mask("my cpf is 006.819.915-50")
    assert "[hidden]" in chain.mask("12.345.678-9")


# =====================================================================
# Layer 0: the system's own identifiers are not documents
# =====================================================================
# Context (measured, not assumed): any long identifier (high-precision
# coordinate, CAR code) contains, sooner or later, a stretch of digits that
# looks like a document. Before Layer 0: 21.6% of location pins and 0.8% of
# CAR codes were being blocked (1 in ~3,000 CARs on the validated detector).

# Real cases reported in the field, on CAR selection.
COORD_ONE_PROPERTY = "47,1798509°W 19,5350942°S"
COORD_TWO_PROPERTIES = "42,1343264°W 17,3386047°S"
COORD_THREE_CARS = "-52.50857591629029, -5.935149162520979"

# CAR codes that used to be false positives before Layer 0.
CAR_FALSE_POSITIVE = [
    "BA-3287819-4845970474100364E5587A1F37A75AC3",
    "RO-1708070-D811A2AC67B370794126616945A35974",
    "TO-5367207-8E7A3510FBBC929BBBB32361861437E8",
    "MS-3779009-B2F7F7C7F16D4B5BC89965149090355B",
    "MT-4750161-C69210318617B554911562D859B399AE",
    "GO-4237547-A56925079940F78341EA1054FF4F40B5",
]

SHOULD_NOT_BLOCK = [
    COORD_ONE_PROPERTY,
    COORD_TWO_PROPERTIES,
    COORD_THREE_CARS,
    "I want to register my property at coordinates Lat: -5.935149162520979 Long: -52.50857591629029.",
    "my farm is at -16.3107, -43.8839",
    "GO-5212303-27057D4194F64CE3A498B90BFAC2E5F9",
    "go-5212303-27057d4194f64ce3a498b90bfac2e5f9",
    "I want to merge GO-5205703-5B18B6DF441C4B7FA9444DDC127CF6C0 and GO-5212303-27057D4194F64CE3A498B90BFAC2E5F9",
    "I have 1.234,56 hectares of pasture",
    "the total area is 1.234.567,89 hectares",
    "my plot is the 987654321098765",
    "the bank slip is 34191790010104351004791020150008291070026000",
    "I bought 250 head at 2.850,00 each",
    "it rained 120 130 140 15 mm",
    "my phone is 62 99999-8888",
    "I want to see the map of my farm",
]


@pytest.mark.parametrize("text", SHOULD_NOT_BLOCK)
def test_should_not_block(text):
    result = _decide_chain(text)
    assert not result.blocked, f"false positive in: {text} — blocked with: {result.text}"


@pytest.mark.parametrize("car", CAR_FALSE_POSITIVE)
def test_car_not_blocked(car):
    """Each of these was blocked before Layer 0."""
    assert not _decide_chain(car).blocked, f"false positive in: {car}"


def test_car_and_cpf_in_same_message():
    """The CAR is protected from the scan, the CPF is still caught."""
    text = "register GO-5212303-27057D4194F64CE3A498B90BFAC2E5F9 and my cpf is 710.768.971-18"
    result = _decide_chain(text)
    assert result.blocked
    assert "GO-5212303-27057D4194F64CE3A498B90BFAC2E5F9" in result.text
    assert "[CPF_HIDDEN]" in result.text


def test_car_is_not_masked_away():
    """Log masking also protects the CAR (it is not evidence of anything)."""
    car = "GO-5212303-27057D4194F64CE3A498B90BFAC2E5F9"
    assert "[hidden]" not in _chain().mask(car)


def test_layer_zero_helper_preserves_text_without_car():
    text = "I want to see the biomass of my farm"
    assert remove_known_scope(text) == text


def test_layer_zero_helper_does_not_swallow_document():
    assert remove_known_scope("my cpf is 710.768.971-18") == "my cpf is 710.768.971-18"


# --- Statistical tests: the false positive was probabilistic ---
def test_false_positive_in_coordinates():
    """No location pin in Brazil may ever be blocked."""
    rng = random.Random(7)
    blocked = []
    for _ in range(5000):
        text = f"Lat: {rng.uniform(-33.0, 5.0)} Long: {rng.uniform(-74.0, -34.0)}"
        if _decide_chain(text).blocked:
            blocked.append(text)
    assert not blocked, f"{len(blocked)} blocked, e.g.: {blocked[:3]}"


def test_false_positive_in_car_codes():
    """Before Layer 0, ~1 in every 3,000 CARs was blocked."""
    rng = random.Random(42)
    states = ["GO", "MT", "MS", "MG", "BA", "PA", "TO", "SP", "PR", "RO"]
    blocked = []
    for _ in range(5000):
        car = (
            f"{rng.choice(states)}-{rng.randint(1000000, 9999999)}-"
            + "".join(rng.choice("0123456789ABCDEF") for _ in range(32))
        )
        if _decide_chain(car).blocked:
            blocked.append(car)
    assert not blocked, f"{len(blocked)} blocked, e.g.: {blocked[:3]}"


# =====================================================================
# Accepted trade-offs of the shape-only policy (documented, not hidden)
# =====================================================================
def test_bare_fourteen_digit_integer_treated_as_cnpj():
    """Without check-digit validation, a bare 14-digit integer blocks.

    Implausible as legitimate data in this domain; the alternative (keeping
    validation) is what allowed mistyped real documents through before.
    """
    result = _decide_chain("I produced 12345678901234 kg of silage")
    assert result.blocked
    assert "cnpj" in result.removed


def test_bare_eleven_digit_integer_treated_as_cpf():
    assert _decide_chain("sequence 71076897118 of photos").blocked