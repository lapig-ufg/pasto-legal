import json
import os
from datetime import datetime

# TODO: No futuro, migrar para uma tabela no banco de dados Postgres.
def registrar_feedback(
    pergunta_original: str, 
    motivo_frustracao: str, 
    resposta_desejada: str
) -> str:
    """
    Registra o feedback de correção do usuário no banco de dados para melhorar a IA no futuro.
    Use esta ferramenta SEMPRE que o usuário demonstrar frustração com uma resposta,
    informando que a resposta foi ruim, incorreta ou inútil, e após você perguntar
    e ele fornecer a resposta esperada.

    Args:
        pergunta_original (str): A pergunta ou requisição inicial do usuário que gerou a frustração.
        motivo_frustracao (str): O motivo pelo qual o usuário não gostou da resposta anterior.
        resposta_desejada (str): A resposta ideal ou a correção que o usuário forneceu para nos ensinar.
    """
    try:
        # Diretório da base de dados do app (pode ser ajustado conforme a arquitetura)
        log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'database')
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, 'feedbacks.jsonl')
        
        feedback_data = {
            "timestamp": datetime.now().isoformat(),
            "pergunta_original": pergunta_original,
            "motivo_frustracao": motivo_frustracao,
            "resposta_desejada": resposta_desejada
        }
        
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(feedback_data, ensure_ascii=False) + "\n")
            
        return "Feedback registrado com sucesso no sistema. Muito obrigado por ajudar a melhorar o Pasto Legal!"
    except Exception as e:
        return f"Erro ao registrar feedback: {str(e)}"
