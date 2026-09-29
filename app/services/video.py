import os
import subprocess
import tempfile


def gif_bytes_to_mp4_bytes(gif_bytes: bytes) -> bytes:
    """
    Converte um GIF (saída do getVideoThumbURL do Earth Engine) em MP4 (H.264,
    yuv420p, faststart) compatível com WhatsApp e players web.

    Args:
        gif_bytes (bytes): Conteúdo do GIF de entrada.

    Returns:
        bytes: Conteúdo do MP4 convertido.

    Raises:
        RuntimeError: Quando o ffmpeg não é encontrado ou falha na conversão.
    """
    ffmpeg_env_path = os.getenv("FFMPEG_PATH")
    env = None
    if ffmpeg_env_path:
        env = {**os.environ, "PATH": os.environ["PATH"] + os.pathsep + ffmpeg_env_path}

    with tempfile.TemporaryDirectory() as tmp_dir:
        gif_path = os.path.join(tmp_dir, "input.gif")
        mp4_path = os.path.join(tmp_dir, "output.mp4")

        with open(gif_path, "wb") as f:
            f.write(gif_bytes)

        command = [
            "ffmpeg", "-y",
            "-i", gif_path,
            "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
            "-movflags", "faststart",
            "-pix_fmt", "yuv420p",
            mp4_path,
        ]

        result = subprocess.run(
            command,
            capture_output=True,
            env=env,
        )

        if result.returncode != 0 or not os.path.exists(mp4_path):
            stderr = result.stderr.decode(errors="replace")[-500:] if result.stderr else ""
            raise RuntimeError(
                f"Falha ao converter o vídeo da biomassa (ffmpeg). Detalhes: {stderr}"
            )

        with open(mp4_path, "rb") as f:
            return f.read()