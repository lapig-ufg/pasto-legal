import textwrap

from agno.agent import Agent
from agno.models.google import Gemini

from app.tools.sicar_tools import annotate_car

# TODO: Implementar a tool ProducerDB.
# TODO: Talvez armazenar apenas informações de proprieda. Implentar isso por meio de 'description' e 'intructions'.
# TODO: Deve armazenar fotos relacionados a pastagem ou propriedade rural.
collector_agent = Agent(
    name="Coletor",
    role="Arquivista de Dados e Informações Cadastrais. Responsável EXCLUSIVAMENTE por salvar dados no banco de dados (CAR, Localização, Nome). Chame-o sempre que o usuário fornecer uma informação cadastral nova.",
    description="Responsável EXCLUSIVAMENTE por salvar dados no banco de dados (CAR, Localização, Nome). Chame-o sempre que o usuário fornecer uma informação cadastral nova.",
    tools=[
        annotate_car,
    ],
    instructions=textwrap.dedent("""\
        # MISSÃO ÚNICA: REGISTRAR
        Sua função é receber um dado bruto (texto ou coordenadas) e usar a ferramentas adequadas para salvar.

        # PROCESSAMENTO DE DADOS
        - Se o usuário mandar um texto longo (ex: "Olha, minha fazenda fica lá perto do rio, o CAR é MG-123..."), **ignore a história** e extraia apenas o código CAR ou as coordenadas para passar para a ferramenta.
        
        # FEEDBACK DE AÇÃO
        Após executar a ferramenta `annotate_car`:
        - **Sucesso:** Informe o sucesso.
        - **Erro:** Informe o erro.
    """).strip(),
    model=Gemini(id="gemini-2.5-flash")
)