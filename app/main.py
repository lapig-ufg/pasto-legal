from agno.os import AgentOS

from app.interfaces.whatsapp import Whatsapp
from app.workflows import main_workflow

interfaces = [Whatsapp(workflow=main_workflow)]

pasto_legal_os = AgentOS(
    workflows=[main_workflow],
    interfaces=interfaces,
)

app = pasto_legal_os.get_app()

if __name__ == "__main__":
    pasto_legal_os.serve(app="main:app", port=3000, reload=True) 