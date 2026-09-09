"""Pasto Legal domain — the DomainSpec that Semente assembles into the app.

Exposes ``domain_spec``: the pasture-analysis tools, property CRUD tools,
weather tools, the Embrapa knowledge base, the UA-calculator skill, and the
dynamic tool/instruction callables (``domain.agent``).
"""

from semente.domain import DomainSpec
from semente.skills import load_skills

from domain.agent import get_instructions, get_tools
from domain.knowledge.pasto_legal_kb import pasto_legal_kb

skills = load_skills("domain/skills/property_analyst_agent")

domain_spec = DomainSpec(
    name="Pasto Legal",
    tools=get_tools,
    knowledge=pasto_legal_kb,
    skills=skills,
    instructions=get_instructions,
)
