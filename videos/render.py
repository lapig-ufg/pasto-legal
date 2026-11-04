"""
Gera os vídeos institucionais e tutoriais do Pasto Legal.

Uso:
    uv run python -m videos.render                 # todos os vídeos
    uv run python -m videos.render cadastro        # um vídeo (propaganda | primeiras_interacoes | cadastro)
"""

import sys
from pathlib import Path

from videos.engine import GREEN, INK, Chat, FeatureList, TextCard, render

OUTPUT_DIR = Path(__file__).resolve().parent / "output"

MUTED = (90, 105, 90)

VIDEOS = {
    "propaganda": lambda: [
        TextCard([("Seu pasto, na palma da mão", 56, GREEN), ("direto no WhatsApp", 36, MUTED)], 4.0),
        TextCard(
            [("Saber como está o pasto custa tempo e dinheiro", 48, INK), ("Rodar a fazenda inteira a cavalo não precisa ser o único jeito", 30, MUTED)],
            5.0, show_logo=False,
        ),
        Chat([
            ("user", "Como está o pasto da minha fazenda?"),
            ("bot", "Analisei as imagens de satélite. O vigor está bom e a biomassa aumentou desde o mês passado."),
            ("user", "Vai chover essa semana?"),
            ("bot", "Sim. A previsão indica chuva nos próximos dias. Quer ver o mapa da biomassa?"),
        ]),
        FeatureList("O que o Pasto Legal faz por você", [
            ("Mapas de satélite", "A sua propriedade vista de cima, com o contorno do CAR."),
            ("Biomassa e vigor", "Quanto pasto você tem e como ele está."),
            ("Previsão de chuva", "Planeje a lotação e o manejo com antecedência."),
            ("Boletim em PDF", "Um resumo completo da fazenda, pronto para guardar."),
        ], 7.5),
        TextCard([("Cadastre com o número do CAR", 48, GREEN), ("ou com a localização do WhatsApp", 34, MUTED)], 4.5, show_logo=False),
        TextCard([("Pasto Legal", 64, GREEN), ("Tecnologia de satélite para o produtor rural", 30, INK), ("pasto.legal", 34, MUTED), ("Uma iniciativa do LAPIG/UFG", 26, MUTED)], 5.5),
    ],
    "primeiras_interacoes": lambda: [
        TextCard([("Primeiras conversas", 56, GREEN), ("Veja como é fácil começar", 34, MUTED)], 3.5),
        Chat([
            ("user", "Oi! O que você consegue fazer?"),
            ("bot", "Oi! Eu sou o Pasto Legal. Uso imagens de satélite e inteligência artificial para acompanhar o seu pasto: mapas, biomassa, vigor e previsão de chuva."),
            ("user", "Legal! E o pasto, como fica na época da seca?"),
            ("bot", "Na seca o pasto produz menos e perde qualidade. O ideal é planejar a lotação e guardar forragem antes. Quer ver como está o seu?"),
            ("user", "Quero! Qual é a biomassa da minha fazenda hoje?"),
            ("bot", "Para analisar a sua fazenda, preciso primeiro cadastrar a propriedade. Pode me enviar o número do CAR ou a localização pelo WhatsApp?"),
        ]),
        TextCard([("Próximo passo", 52, GREEN), ("Cadastrar a sua propriedade", 36, INK)], 3.5),
    ],
    "cadastro": lambda: [
        TextCard([("Cadastro de propriedade", 54, GREEN), ("Passo a passo no WhatsApp", 34, MUTED)], 3.5),
        TextCard([("Passo 1", 40, MUTED), ("Envie o número do CAR", 52, GREEN), ("ou a localização pelo WhatsApp", 32, INK)], 4.0, show_logo=False),
        Chat([
            ("user", "Quero cadastrar minha propriedade. O meu CAR é GO-0000000-A1B2C3D4E5F6"),
            ("bot", "Procurando o seu imóvel no SICAR. Um instante."),
            ("bot", "Encontrei! Este é o contorno do imóvel: 85,9 hectares em Goiás. É essa a sua propriedade?", "map"),
            ("user", "Sim, é essa!"),
            ("bot", "Propriedade confirmada. Quer dar um nome a ela? Por exemplo: Fazenda Boa Vista."),
            ("user", "Sítio Esperança"),
            ("bot", "Pronto! O Sítio Esperança está salvo. Já posso gerar mapas e análises."),
        ], tail=2.5),
        TextCard([("Propriedade cadastrada", 48, GREEN), ("Agora é só perguntar", 36, INK)], 4.0),
    ],
}


def main(names: list[str]) -> None:
    for name in names or list(VIDEOS):
        output = render(VIDEOS[name](), OUTPUT_DIR / f"pasto_legal_{name}.mp4", progress=lambda n, total: print(f"{name}: {n}/{total}") if n % 300 == 0 else None)
        print(f"{output} ({output.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main(sys.argv[1:])
