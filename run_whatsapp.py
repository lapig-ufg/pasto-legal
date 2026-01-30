
import os
import sys
from dotenv import load_dotenv

# Carrega variáveis de ambiente do .env
load_dotenv()

# Adiciona o diretório atual ao sys.path para permitir imports absolutos de 'app'
sys.path.append(os.getcwd())

if __name__ == "__main__":
    from app.main import pasto_legal_os
    
    app = pasto_legal_os.get_app()
    # Executa o servidor uvicorn (Agno OS)
    pasto_legal_os.serve(app="app.main:app", port=3000, reload=True)
