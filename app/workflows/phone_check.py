"""Standalone phone-number authorization helper.

Reads the user's phone number from session_state and checks it against the
allowed list in `phone_numbers.in`. Not currently wired into any workflow
step; kept here for reuse when the entry authorization gate is added.
"""
from agno.run import RunContext
from agno.utils.log import log_error


# Check user phone number authorization.
def phone_number_check(run_context: RunContext):
    session_state = run_context.session_state

    user_id = session_state.get('user_id', None)

    if user_id is None:
        return False

    user_phone_number = user_id.replace("wa:", "")

    try:
        with open(f'phone_numbers.in', 'r', encoding='utf-8') as file:

            for line in file:
                if line.strip() == user_phone_number.strip():
                    return

    except FileNotFoundError:
        log_error("FileNotFoundError: phone_numbers.in.")
    except Exception as e:
        log_error(f"Exception: {e}.")