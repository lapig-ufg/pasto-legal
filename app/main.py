from agno.os import AgentOS

from app.agents.main_team import pasto_legal_team
from app.interfaces.whatsapp import Whatsapp
from app.database.agno_db import db

interfaces = [Whatsapp(team=pasto_legal_team)]

pasto_legal_os = AgentOS(
    db=db,
    teams=[pasto_legal_team],
    interfaces=interfaces,
)

app = pasto_legal_os.get_app()

if __name__ == "__main__":
    pasto_legal_os.serve(app="main:app", port=3000, reload=True) 