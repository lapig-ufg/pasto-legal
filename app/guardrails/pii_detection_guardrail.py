import re
from agno.guardrails import PIIDetectionGuardrail

custom_patterns = {}


custom_patterns['CPF'] = re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")
custom_patterns['CNPJ'] = re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}/\d{4}-?\d{2}\b")


custom_patterns['CAR'] = re.compile(r"\b[A-Z]{2}-\d{7}-[A-F0-9.]+\b", re.IGNORECASE)
custom_patterns['COORDINATES'] = re.compile(r"(-?\d{1,3}\.\d{4,}\s*,\s*-?\d{1,3}\.\d{4,})")

pii_detection_guardrail: PIIDetectionGuardrail = PIIDetectionGuardrail(custom_patterns=custom_patterns)