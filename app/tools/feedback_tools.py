import sqlite3
import os
from datetime import datetime

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
        db_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'database')
        os.makedirs(db_dir, exist_ok=True)
        db_path = os.path.join(db_dir, 'feedbacks.db')
        
        # Conecta ao SQLite (cria o arquivo se não existir)
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Cria a tabela caso ainda não exista
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS feedbacks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                pergunta_original TEXT,
                motivo_frustracao TEXT,
                resposta_desejada TEXT
            )
        ''')
        
        # Insere o novo feedback
        cursor.execute('''
            INSERT INTO feedbacks (timestamp, pergunta_original, motivo_frustracao, resposta_desejada)
            VALUES (?, ?, ?, ?)
        ''', (datetime.now().isoformat(), pergunta_original, motivo_frustracao, resposta_desejada))
        
        conn.commit()
        conn.close()
            
        return "Feedback registrado com sucesso no sistema. Muito obrigado por ajudar a melhorar o Pasto Legal!"
    except Exception as e:
        return f"Erro ao registrar feedback: {str(e)}"
