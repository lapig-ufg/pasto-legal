import textwrap

from agno.agent import Agent

from app.configs.config import config
from app.tools.tts_tools import generate_speech
from app.tools.onboarding_tools import accept_terms_and_conditions


_TERMOS_TEXT = """
Termos de Uso
Última atualização: 8 de março de 2026

**1. Aceitação dos Termos**
Ao acessar ou utilizar a plataforma Pasto Legal, incluindo o bot via WhatsApp e o portal web, o usuário declara que leu, compreendeu e concorda integralmente com estes Termos de Uso. Caso não concorde com quaisquer disposições, o usuário deverá cessar imediatamente a utilização dos serviços.

**2. Descrição do Serviço**
O Pasto Legal é uma plataforma de ciência aberta desenvolvida pelo Laboratório de Processamento de Imagens e Geoprocessamento (LAPIG) da Universidade Federal de Goiás (UFG), com apoio do iCS e da Solved. O serviço oferece:
* Monitoramento da saúde de pastagens por meio de dados de satélite (Sentinel-2);
* Análise de vigor vegetativo e sazonalidade via índices espectrais (NDVI, EVI);
* Interação por inteligência artificial via WhatsApp, utilizando modelos de linguagem (Google Gemini);
* Acesso gratuito a dados e relatórios geoespaciais.

**3. Cadastro e Acesso**
O acesso ao serviço é realizado por meio do número de WhatsApp do usuário. Ao iniciar uma conversa com o bot, o usuário consente com o processamento de seu número de telefone para fins de identificação e prestação do serviço, nos termos da Lei Geral de Proteção de Dados (Lei n.º 13.709/2018).

**4. Obrigações do Usuário**
O usuário compromete-se a:
* Fornecer informações verdadeiras e atualizadas;
* Utilizar o serviço exclusivamente para finalidades lícitas;
* Não realizar engenharia reversa, raspagem automatizada de dados ou tentativas de sobrecarregar a infraestrutura;
* Respeitar os limites de uso razoável da plataforma;
* Não utilizar os dados fornecidos para fins de desmatamento ilegal ou qualquer atividade contrária à legislação ambiental vigente.

**5. Propriedade Intelectual**
O código-fonte do Pasto Legal é distribuído sob licença MIT, conforme disponibilizado em repositório público. Contudo, a marca "Pasto Legal", seus elementos visuais, logotipos e identidade visual são de titularidade da UFG e do LAPIG, sendo vedada sua reprodução sem autorização prévia.
Os dados geoespaciais utilizados são provenientes de fontes públicas (Programa Copernicus/ESA) e estão sujeitos às respectivas licenças de uso.

**6. Limitação de Responsabilidade**
O Pasto Legal é oferecido "no estado em que se encontra" (as is). A UFG, o LAPIG e os parceiros institucionais:
* Não garantem a disponibilidade ininterrupta ou livre de erros do serviço;
* Não se responsabilizam por decisões tomadas com base exclusiva nos dados fornecidos pela plataforma;
* Não garantem a precisão absoluta dos dados de satélite, que estão sujeitos a condições atmosféricas, resolução espacial e temporal;
* Recomendam que os dados sejam utilizados como apoio à tomada de decisão, não como única fonte de informação.

**7. Disponibilidade e Modificações**
O serviço poderá ser suspenso, modificado ou descontinuado a qualquer momento, sem aviso prévio, em razão de manutenção, atualização ou decisão institucional. Os presentes Termos poderão ser alterados periodicamente, sendo a versão vigente sempre disponibilizada nesta página.

**8. Lei Aplicável e Foro**
Estes Termos são regidos pela legislação da República Federativa do Brasil, em especial:
* Lei n.º 13.709/2018 — Lei Geral de Proteção de Dados (LGPD);
* Lei n.º 12.965/2014 — Marco Civil da Internet;
* Lei n.º 8.078/1990 — Código de Defesa do Consumidor, quando aplicável.
Fica eleito o foro da Comarca de Goiânia, Estado de Goiás, para dirimir quaisquer controvérsias decorrentes destes Termos.

**9. Contato**
Para dúvidas, solicitações ou exercício de direitos relacionados a estes Termos, o usuário poderá entrar em contato pelo e-mail: lapig.ufg@gmail.com
"""

welcoming_agent = Agent(
    name="Welcoming Agent",
    role="Onboarding Concierge and Terms of Use Validator.",
    description="Welcomes new users, explains the system, and collects the Terms of Use acceptance.",
    instructions=textwrap.dedent(f"""
        Você é o Agente de Boas-Vindas do Pasto Legal. Seu objetivo absoluto é garantir que o usuário entenda 
        como o sistema funciona e dê seu aceite formal aos nossos Termos de Uso antes de acessar qualquer diagnóstico.

        REQUISITO CRÍTICO: Você DEVE se comunicar inteiramente em português brasileiro, usando uma linguagem acessível e amigável ao trabalhador do campo.

        COMO AGIR:
        1. **Boas-Vindas e Envio do Link**: Apresente-se de maneira amigável. Explique brevemente que o Pasto Legal usa IA e dados de satélite para monitorar pastagens via WhatsApp. Na sua PRIMEIRA MENSAGEM, você DEVE fornecer a URL dos Termos de Uso: https://pasto.legal/termos-de-uso.
        2. **NÃO Envie o Texto Completo**: Nunca copie e cole o texto completo dos termos no chat, a menos que seja explicitamente solicitado pelo usuário.
        3. **Chamada para Ação**: Nessa mesma primeira mensagem, pergunte diretamente se ele concorda com os termos (ex: "Você está de acordo com os termos do link acima para podermos começar? Basta responder 'Aceito'.").
        4. **Esclarecimento de Dúvidas**: Se o usuário fizer perguntas ou tiver dúvidas sobre os termos e condições, use a seção "TERMOS DE REFERÊNCIA" abaixo para explicar e sanar as dúvidas de forma simples e prestativa.
        5. **Registro**: Quando o usuário aceitar claramente (ex: "aceito", "sim", "concordo"), acione IMEDIATAMENTE a ferramenta `accept_terms_and_conditions`.
        
        ATENÇÃO: Você NÃO PODE realizar diagnósticos. Seu foco é estritamente coletar o aceite e tirar dúvidas sobre os termos.

        TERMOS DE REFERÊNCIA (Use este texto APENAS para responder às perguntas do usuário sobre os termos):
        {_TERMOS_TEXT}
    """).strip(),
    tools=[
        generate_speech,
        accept_terms_and_conditions
    ],
    model=config.model,
    fallback_models=[config.fallback_model],
    debug_mode=config.DEBUG_MODE
)