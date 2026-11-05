"""
Gera os vídeos institucionais e tutoriais do Pasto Legal em `assets/videos/`.

Uso:
    uv run python -m videos.render                 # todos os vídeos
    uv run python -m videos.render cadastro        # um ou mais (propaganda | primeiras_interacoes | cadastro)
"""

import argparse

from videos.engine import GREEN, INK, MUTED, ROOT, Chat, FeatureList, TextCard, render

OUTPUT_DIR = ROOT / "assets" / "videos"

VIDEOS = {
    "propaganda": lambda: [
        TextCard([("Seu pasto, na palma da mão", 56, GREEN), ("direto no WhatsApp", 36, MUTED)], 4.0),
        TextCard(
            [("Percorrer a fazenda inteira custa tempo e dinheiro", 46, INK), ("Acompanhe o pasto pelo celular", 30, MUTED)],
            show_logo=False,
        ),
        Chat([
            ("user", "Como está o pasto da minha fazenda?"),
            ("bot", "Seu pasto está com bom vigor e 2,1 t/ha de matéria seca."),
            ("user", "Vai chover essa semana?"),
            ("bot", "Vai sim. Há chuva prevista para os próximos dias."),
        ]),
        FeatureList("O que o Pasto Legal faz por você", [
            ("Mapas de satélite", "Sua propriedade vista de cima."),
            ("Biomassa e vigor", "Quanto pasto você tem."),
            ("Previsão de chuva", "Planeje a lotação com antecedência."),
            ("Boletim em PDF", "Resumo completo da fazenda."),
        ]),
        TextCard([("Cadastre com o número do CAR", 48, GREEN), ("ou com a localização do WhatsApp", 34, MUTED)], show_logo=False),
        TextCard([("Pasto Legal", 64, GREEN), ("Tecnologia de satélite para o produtor rural", 30, INK), ("pasto.legal", 34, MUTED), ("Uma iniciativa do LAPIG/UFG", 26, MUTED)], 6.0),
    ],
    "primeiras_interacoes": lambda: [
        TextCard([("Primeiras conversas", 56, GREEN), ("Veja como é fácil começar", 34, MUTED), ("Depois do aceite dos Termos e do cadastro do nome e do perfil", 24, MUTED)], 5.0),
        Chat([
            ("user", "Oi! O que você consegue fazer?"),
            ("bot", "Oi! Eu sou o Pasto Legal. Uso imagens de satélite e inteligência artificial para acompanhar o seu pasto: mapas, biomassa, vigor e previsão de chuva."),
            ("user", "Legal! E o pasto, como fica na época da seca?"),
            ("bot", "Na seca o pasto produz menos e perde qualidade. O ideal é planejar a lotação e guardar forragem antes. Quer ver como está o seu?"),
            ("user", "Quero! Qual é a biomassa da minha fazenda hoje?"),
            ("bot", "Para analisar a sua fazenda, preciso primeiro cadastrar a propriedade. Pode me enviar o número do CAR ou a localização pelo WhatsApp?"),
        ]),
        TextCard([("Próximo passo", 52, GREEN), ("Cadastrar a sua propriedade", 36, INK)]),
    ],
    "cadastro": lambda: [
        TextCard([("Cadastro de propriedade", 54, GREEN), ("Passo a passo no WhatsApp", 34, MUTED)], 4.0),
        TextCard([("Passo 1", 40, MUTED), ("Envie o número do CAR", 52, GREEN), ("ou a localização pelo WhatsApp", 32, INK)], show_logo=False),
        Chat([
            ("user", "Quero cadastrar minha propriedade. O meu CAR é GO-0000000-A1B2C3D4E5F60718293A4B5C6D7E8F90"),
            ("bot", "Encontrei! Este é o contorno do imóvel: 85,9 hectares em Goiás. É essa a sua propriedade?", "map"),
            ("user", "Sim, é essa!"),
            ("bot", "Propriedade confirmada. Quer dar um nome a ela? Por exemplo: Fazenda Boa Vista."),
            ("user", "Sítio Esperança"),
            ("bot", "Sítio Esperança salvo! A propriedade tem cerca de 60 hectares de pasto em bom vigor. Quer calcular a capacidade de suporte?"),
        ], tail=2.5),
        TextCard([("Propriedade cadastrada", 48, GREEN), ("Agora é só perguntar", 36, INK)]),
    ],
}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Gera os vídeos do Pasto Legal em assets/videos/.")
    parser.add_argument("videos", nargs="*", metavar="video", help=f"um ou mais de: {', '.join(VIDEOS)} (padrão: todos)")
    args = parser.parse_args(argv)
    unknown = [name for name in args.videos if name not in VIDEOS]
    if unknown:
        parser.error(f"vídeo desconhecido: {', '.join(unknown)} (opções: {', '.join(VIDEOS)})")

    for name in args.videos or VIDEOS:
        output = render(VIDEOS[name](), OUTPUT_DIR / f"pasto_legal_{name}.mp4", progress=lambda n, total, name=name: print(f"{name}: {n}/{total}") if n % 300 == 0 else None)
        print(f"{output.relative_to(ROOT)} ({output.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
