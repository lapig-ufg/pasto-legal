# Vídeos do Pasto Legal

Animações institucionais e tutoriais, geradas por código a partir da identidade visual do projeto (`assets/logos` e `assets/fonts`), em MP4 H.264 Main sem B-frames, vertical (720x1280, 30 fps, bt709, faststart), no formato recomendado pela Meta para o WhatsApp.

Os arquivos finais ficam em `assets/videos/` e são enviados ao usuário pela ferramenta `send_tutorial_video` (`domain/tools/tutorial_tools.py`), disponível ao agente quando o usuário pede um vídeo ou tutorial.

| Arquivo | Conteúdo | Roteiro |
|---|---|---|
| `assets/videos/pasto_legal_propaganda.mp4` | Vídeo completo (propaganda) | `roteiros/01-propaganda.md` |
| `assets/videos/pasto_legal_primeiras_interacoes.mp4` | Tutorial de primeiras interações | `roteiros/02-tutorial-primeiras-interacoes.md` |
| `assets/videos/pasto_legal_cadastro.mp4` | Tutorial de cadastro de propriedade | `roteiros/03-tutorial-cadastro-propriedade.md` |

## Gerar

Requer `ffmpeg` com libx264 no PATH. Rode a partir da raiz do repositório.

```bash
uv run python -m videos.render                          # todos
uv run python -m videos.render cadastro propaganda      # os escolhidos
```

## Alterar um vídeo

O conteúdo de cada vídeo está em `render.py` (dicionário `VIDEOS`), como lista de cenas: `TextCard`, `Chat` e `FeatureList`. O tempo de cada balão e cartão cresce com o número de palavras (3 palavras por segundo). O motor de desenho está em `engine.py`. Os textos devem refletir o roteiro aprovado; depois de alterar, gere de novo e confira os tempos nos roteiros.

A fonte da marca no repositório (DejaVu Sans Bold) não tem emojis; evite-os nos textos.
