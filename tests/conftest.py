"""Shared test setup.

Domain tool modules resolve their descriptions at import time via the
semente prompts loader, which needs the app's prompts dir. At runtime
``semente.build.build_app`` applies it from the manifest; in tests, apply it
here before any domain import.
"""

import os

from semente.configs.prompts import set_prompts_dir

set_prompts_dir(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "domain", "prompts")
)