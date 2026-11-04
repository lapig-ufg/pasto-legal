# Vídeos do Pasto Legal

Animações institucionais e tutoriais, geradas por código a partir da identidade visual do projeto (`assets/logos` e `assets/fonts`), em MP4 H.264 vertical (720x1280, 30 fps), compatível com envio pelo WhatsApp.

| Arquivo | Conteúdo | Roteiro |
|---|---|---|
| `output/pasto_legal_propaganda.mp4` | Vídeo completo (propaganda) | `roteiros/01-propaganda.md` |
| `output/pasto_legal_primeiras_interacoes.mp4` | Tutorial de primeiras interações | `roteiros/02-tutorial-primeiras-interacoes.md` |
| `output/pasto_legal_cadastro.mp4` | Tutorial de cadastro de propriedade | `roteiros/03-tutorial-cadastro-propriedade.md` |

## Gerar

Requer `ffmpeg` com libx264 no PATH.

```bash
uv run python -m videos.render              # todos
uv run python -m videos.render cadastro     # propaganda | primeiras_interacoes | cadastro
```

## Alterar um vídeo

O conteúdo de cada vídeo está em `render.py` (dicionário `VIDEOS`), como lista de cenas: `TextCard`, `Chat` e `FeatureList`. O motor de desenho está em `engine.py`. Os textos devem refletir o roteiro aprovado.
