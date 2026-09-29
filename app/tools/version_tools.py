from pathlib import Path

from agno.tools import tool
from agno.utils.log import log_debug, log_warning, log_error

from app.configs.prompts import get_tool_description, get_tool_result_text


@tool(description=get_tool_description("version_tools", "consult_update_notes"))
def consult_update_notes() -> str:
    """
    Lê e retorna as notas de atualização (patch notes) do sistema Pasto Legal.
    Use esta ferramenta quando o usuário perguntar sobre a versão atual, novidades ou atualizações.
    """
    log_debug("consult_update_notes: iniciando leitura das notas de versão")
    base_path = Path(__file__).resolve().parent.parent.parent
    folder_path = base_path / "docs" / "release_notes"
    
    if not folder_path.exists():
        log_warning(f"Diretório de notas de versão não encontrado: {folder_path}")
        return get_tool_result_text("version_tools", "consult_update_notes", "release_dir_not_found")
        
    try:
        files = sorted(folder_path.glob("*.md"))
        if not files:
            log_warning(f"Nenhuma nota de versão encontrada em {folder_path}")
            return get_tool_result_text("version_tools", "consult_update_notes", "no_release_notes")
        target_file = files[-1]
            
        if not target_file.exists():
            log_warning(f"Arquivo de notas não encontrado: {target_file}")
            return get_tool_result_text("version_tools", "consult_update_notes", "release_file_not_found")
            
        with open(target_file, "r", encoding="utf-8") as f:
            conteudo = f.read()

        log_debug(f"consult_update_notes: notas lidas de {target_file.name}")
        return get_tool_result_text("version_tools", "consult_update_notes", "success", content=conteudo)
        
    except Exception as e:
        log_error(f"consult_update_notes: erro ao ler notas de versão: {e}")
        return get_tool_result_text("version_tools", "consult_update_notes", "error", error=e)