"""Feedback persistence and the final merge step.

These steps run after the parallel branches complete: they read the normal
agent response, persist frustrated/amazed interactions to the DB for future
fine-tuning, and merge the evaluation branch with the normal response.
"""
from typing import Any, Dict
from datetime import datetime

from agno.run import RunContext
from agno.workflow.types import StepInput, StepOutput


from app.database.session import SessionLocal, engine

from app.tools.feedback_tools import _mask_pii

