from agno.os import AgentOS

from app.utils.whatsapp import Whatsapp

from app.agents.main_agent import pasto_legal_team

pasto_legal_os = AgentOS(
    teams=[pasto_legal_team],
    interfaces=[Whatsapp(team=pasto_legal_team)],
)

app = pasto_legal_os.get_app()

if __name__ == "__main__":
    pasto_legal_os.serve(app="main:app", port=3000, reload=True) 