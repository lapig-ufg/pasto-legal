from pathlib import Path
from importlib.metadata import version

from agno.tools import tool


@tool
def consult_update_notes() -> str:
    """
    Lê e retorna as notas de atualização (patch notes) do sistema Pasto Legal.
    Use esta ferramenta quando o usuário perguntar sobre a versão atual, novidades ou atualizações.
    """
    base_path = Path(__file__).resolve().parent.parent.parent
    folder_path = base_path / "docs" / "release_notes"
    
    if not folder_path.exists():
        return "Erro: O diretório de notas de versão não foi encontrado no sistema."
        
    try:
        files = sorted(folder_path.glob("*.md"))
        if not files:
            return "Aviso: Nenhuma nota de versão foi encontrada no repositório."
        target_file = files[-1]
            
        if not target_file.exists():
            return f"Erro: As notas de atualização não foram encontradas."
            
        with open(target_file, "r", encoding="utf-8") as f:
            conteudo = f.read()
            
        return (
            f"Conteúdo do patch:\n\n{conteudo}\n\n"
            "Repasse essas informações INTEGRALMENTE ao usuário utilizando ESTRITAMENTE a formatação de texto do WhatsApp (*negrito*, _itálico_). "
            "Não utilize formatação Markdown como #, ## ou **."
        )
        
    except Exception as e:
        return f"Erro inesperado ao tentar ler o arquivo de patch: {str(e)}"