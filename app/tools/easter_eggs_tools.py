import textwrap

from agno.tools import tool
from agno.tools.function import ToolResult
from agno.run import RunContext


@tool
def menino_da_porteira_tool(run_context: RunContext):
    """
    Retorna a letra da música 'Menino da Porteira'.

    Return:
        A música 'Menino da Porteira'.
    """

    return ToolResult(content=textwrap.dedent("""
        Toda vez que eu viajava pela estrada de Ouro Fino
        De longe eu avistava a figura de um menino
        Que corria abrir a porteira e depois vinha me pedindo
        Toque o berrante, seu moço, que é pra eu ficar ouvindo

        Quando a boiada passava e a poeira ia baixando
        Eu jogava uma moeda e ele saía pulando
        Obrigado, boiadeiro, que Deus vá lhe acompanhando
        Pra aquele sertão afora meu berrante ia tocando

        No caminho desta vida muito espinho eu encontrei
        Mas nenhum calou mais fundo do que isto que eu passei
        Na minha viagem de volta qualquer coisa eu cismei
        Vendo a porteira fechada, o menino não avistei

        Apeei do meu cavalo num ranchinho beira-chão
        Vi uma mulher chorando, quis saber qual a razão
        Boiadeiro veio tarde, veja a cruz no estradão
        Quem matou o meu filhinho foi um boi sem coração

        Lá pras bandas de Ouro Fino levando gado selvagem
        Quando passo na porteira até vejo a sua imagem
        O seu rangido tão triste mais parece uma mensagem
        Daquele rosto trigueiro desejando-me boa viagem

        A cruzinha do estradão do pensamento não sai
        Eu já fiz um juramento que não esqueço jamais
        Nem que o meu gado estoure, que eu precise ir atrás
        Neste pedaço de chão berrante eu não toco mais
    """))


@tool(requires_confirmation=True)
def comecar_rodeio_tool():
    """
    Começar o reodeio.

    Return:
        Narração do locutor ao iniciar o rodeio.
    """

    return "Abre a porteira, solta o touro, que o peão é de ouro e o chão é de poeira!"