from agno.agent import Agent
from agno.models.google import Gemini
from agno.tools import tool

import dotenv

dotenv.load_dotenv()

def safe_operation() -> str:
    """This runs automatically without confirmation."""
    return "Safe operation completed"

@tool(requires_confirmation=True)
def risky_operation() -> str:
    """This requires user confirmation."""
    return "Risky operation completed"

agent = Agent(
    model=Gemini(id="gemini-2.5-flash"),
    tools=[safe_operation, risky_operation],
)

run_response = agent.run("Perform both operations")

if run_response.is_paused:
    # Only the risky_operation will be in tools_requiring_confirmation
    for tool in run_response.tools_requiring_confirmation:
        # Handle confirmation...
        tool.confirmed = True

    response = agent.continue_run(run_id=run_response.run_id, updated_tools=run_response.tools)

    print('confirmed', response.content)


print('not confirmed', run_response.content)