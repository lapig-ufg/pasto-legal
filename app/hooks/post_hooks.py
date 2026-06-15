from agno.run import RunContext
from agno.utils.log import log_debug

def pos_debug_session_state(run_context: RunContext):
    log_debug(f"\033[32mRUN CONTEXT\033[0m")
    log_debug("", center=True)
    log_debug(run_context.session_state)