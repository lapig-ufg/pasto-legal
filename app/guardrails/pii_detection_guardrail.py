import re

from agno.guardrails import PIIDetectionGuardrail

custom_patterns = {}

# TODO: Garantir que valide todos os casos? 12312312312, 123.123.123-12, 123123.123-12, ...
custom_patterns['CPF'] = re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b")
custom_patterns['CNPJ'] = re.compile(r"\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b")

pii_detection_guardrail: PIIDetectionGuardrail = PIIDetectionGuardrail(custom_patterns=custom_patterns)
