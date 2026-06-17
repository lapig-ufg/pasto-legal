import textwrap

from agno.memory import MemoryManager

from app.database.agno_db import db
from app.configs.config import config


memory_manager: MemoryManager = MemoryManager(
    model=config.model,
    memory_capture_instructions=textwrap.dedent("""
        Memories should capture personal information about the user that is relevant to the current conversation, such as:
        - Personal facts: name, age, occupation, interests, and preferences
        - Opinions and preferences: what the user likes, dislikes, enjoys, or finds frustrating
        - Significant life events or experiences shared by the user
        - Important context about the user's current situation, challenges, or goals
        - Any other details that offer meaningful insight into the user's personality, perspective, or needs
    """).strip(),
    additional_instructions="""Don't store any memories about coordinates, SICAR code or Google Map's URLs.""",
    db=db,
)