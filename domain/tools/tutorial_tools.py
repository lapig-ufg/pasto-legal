from pathlib import Path

from semente import ToolResult, Video, tool
from semente.configs.prompts import get_tool_description, get_tool_result_text
from semente.context import Context as RunContext
from semente.logging import log_debug, log_error

TUTORIAL_VIDEOS_DIR = Path(__file__).resolve().parents[2] / "assets" / "videos"

TUTORIAL_VIDEOS = {
    "primeiras_interacoes": "Primeiras conversas com o Pasto Legal",
    "cadastro": "Cadastro de propriedade",
    "propaganda": "Apresentação do Pasto Legal",
}


@tool(description=get_tool_description("tutorial_tools", "send_tutorial_video"))
def send_tutorial_video(run_context: RunContext, video: str) -> ToolResult:
    """
    Envia ao usuário um vídeo tutorial ou de apresentação do Pasto Legal (MP4 animado).

    params:
        video (str): "primeiras_interacoes", "cadastro" ou "propaganda".

    Return:
        ToolResult: Texto de confirmação e o vídeo MP4 para envio.
    """
    log_debug(f"send_tutorial_video: video={video}")
    try:
        path = TUTORIAL_VIDEOS_DIR / f"pasto_legal_{video}.mp4"
        if video not in TUTORIAL_VIDEOS or not path.is_file():
            return ToolResult(content=get_tool_result_text(
                "tutorial_tools", "send_tutorial_video", "unknown_video", video=video, options=", ".join(TUTORIAL_VIDEOS),
            ))

        return ToolResult(
            content=get_tool_result_text("tutorial_tools", "send_tutorial_video", "success", title=TUTORIAL_VIDEOS[video]),
            videos=[Video(content=path.read_bytes(), mime_type="video/mp4", format="mp4")],
        )
    except Exception as e:
        log_error(f"send_tutorial_video: {e}")
        return ToolResult(content=get_tool_result_text("tutorial_tools", "send_tutorial_video", "error", error=e))
