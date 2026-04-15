import pytest
import re
from app.guardrails.pii_detection_guardrail import custom_patterns

def mask_text(text: str) -> str:
    """Simula o comportamento do guardrail usando seus padrões de Regex."""
    for label, pattern in custom_patterns.items():
        text = pattern.sub(f"[{label}]", text)
    return text

def test_car_masking():
    """Valida se o seu Regex de CAR funciona."""
    texto_sujo = "O CAR MT-5107909-6444.A5E3.1234.5678.90AB.CDEF.GHIJ.KLMN está regular."
    resultado = mask_text(texto_sujo)
    
    assert "[CAR]" in resultado
    assert "MT-5107909" not in resultado

def test_coordinates_masking():
    """Valida se o seu Regex de Coordenadas funciona."""
    texto_sujo = "Localizado em -15.123456, -47.654321."
    resultado = mask_text(texto_sujo)
    
    assert "[COORDINATES]" in resultado
    assert "-15.123456" not in resultado

def test_mixed_pii_masking():
    """Valida múltiplos dados (CPF e CAR)."""
    texto_sujo = "CPF 123.456.789-00 e CAR PA-1501408-B3C2.D1E5."
    resultado = mask_text(texto_sujo)
    
    assert "[CPF]" in resultado
    assert "[CAR]" in resultado