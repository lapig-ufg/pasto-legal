from pathlib import Path

from agno.tools import tool


@tool
def consult_update_notes() -> str:
    """
    Lê e retorna as notas de atualização (patch notes) do sistema Pasto Legal.
    Use esta ferramenta quando o usuário perguntar sobre a versão atual, novidades ou atualizações.
    """
    diretorio_base = Path(__file__).resolve().parent.parent.parent
    pasta_notas = diretorio_base / "docs" / "release_notes"
    
    if not pasta_notas.exists():
        return "Erro: O diretório de notas de versão não foi encontrado no sistema."
        
    try:
        arquivos_md = sorted(pasta_notas.glob("*.md"))
        if not arquivos_md:
            return "Aviso: Nenhuma nota de versão foi encontrada no repositório."
        arquivo_alvo = arquivos_md[-1]
            
        if not arquivo_alvo.exists():
            return f"Erro: As notas de atualização não foram encontradas."
            
        with open(arquivo_alvo, "r", encoding="utf-8") as f:
            conteudo = f.read()
            
        return (
            f"Conteúdo do patch lido com sucesso:\n\n{conteudo}\n\nBuild: XXXX001\n\n"
            "INSTRUÇÃO DO SISTEMA: Repasse essas informações ao usuário utilizando "
            "ESTRITAMENTE a formatação de texto do WhatsApp (*negrito*, _itálico_). "
            "Não utilize formatação Markdown como #, ## ou **."
        )
        
    except Exception as e:
        return f"Erro inesperado ao tentar ler o arquivo de patch: {str(e)}"