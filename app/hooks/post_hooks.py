from agno.agent import RunOutput


def format_whatsapp_markdown(run_output: RunOutput):
    """
    Hook de formatação para garantir que o markdown esta no formato do WhatsApp.
    """
    if run_output and hasattr(run_output, "content"):
        content: str = run_output.content
        content = content.replace("**", "*")

        run_output.content = content