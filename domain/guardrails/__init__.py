"""Brazil-specific input guardrails of the Pasto Legal domain.

One blocking guard per document type: CPF, CNPJ, RG.
"""

from .brazil_pii import CnpjGuardrail, CpfGuardrail, RgGuardrail

__all__ = ["CnpjGuardrail", "CpfGuardrail", "RgGuardrail"]