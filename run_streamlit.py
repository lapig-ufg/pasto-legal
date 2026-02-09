
import os
import sys
import streamlit.web.cli as stcli
from dotenv import load_dotenv

# Carrega variáveis de ambiente do .env
load_dotenv()

# Adiciona o diretório atual ao sys.path para permitir imports absolutos de 'app'
sys.path.append(os.getcwd())

if __name__ == "__main__":
    sys.argv = [
        "streamlit",
        "run",
        os.path.join("app", "interfaces", "streamlit", "streamlit_webapp.py"),
        "--server.port", "8501"
    ]
    sys.exit(stcli.main())
