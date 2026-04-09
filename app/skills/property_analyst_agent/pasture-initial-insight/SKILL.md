---
name: pasture-initial-insight
description: Geração de diagnóstico inicial rápido e cativante para pequenos produtores rurais.
license: Apache-2.0
metadata:
  version: "1.0.0"
  author: lapig-team
  tags: ["insight inicial", "engajamento"]
---

# Skill de Insight Inicial de Pastagem

Use esta skill ao cruzar dados de biomassa, vigor, idade e uso do solo para gerar um diagnóstico rápido e cativante para o produtor rural.

## When to Use

- O usuário solicitar um diagnóstico de uma nova propriedade.
- For necessário demonstrar o valor prático e imediato da IA para cativar o produtor rural.
- O agente precisar iniciar uma conversa proativa baseada no estado atual da fazenda.

## Process

1. **Levantamento de Dados Inibido**: Acione apenas as ferramentas `query_pasture_lulc`, `query_pasture_biomass`, `query_pasture_vigor` e `query_pasture_age`. Não gere imagens.
2. **Cruzamento de Cenários**: Analise os dados em conjunto para encontrar a maior "dor" ou "oportunidade" da propriedade. Procure padrões como:
    - Alta idade + Baixo vigor (Sinal de degradação/Pasto cansado).
    - Boa área de LULC + Baixa biomassa (Capacidade ociosa / Subutilização).
    - Alto vigor + Alta biomassa (Oportunidade de aumentar o rebanho / Sobrando capim).
3. **Formulação do Insight (Formato WhatsApp)**: Escreva uma mensagem ultracurta (máximo de 2 a 3 frases fluidas) em tom acolhedor e direto. Imagine que você está mandando um áudio rápido no WhatsApp.
4. **Criação do Gancho (Call to Action)**: Termine a mensagem com uma única pergunta instigante, focada na resolução de um problema real (bolso ou manejo), que faça o usuário querer usar outras ferramentas (como a calculadora de UA).

## Best Practices

- **Formato Estrito para WhatsApp**: A mensagem deve ser um bloco de texto curto, contínuo e amigável. Use emojis com muita moderação (1 ou 2 no máximo, no final).
- **Storytelling sobre Estatísticas**: Oculte a complexidade técnica. O produtor não quer saber de "toneladas de matéria seca" ou "níveis de vigor". Ele entende "pasto guerreiro", "sinais de cansaço" e "sobrando comida". Insira apenas UM dado real (como a área em hectares ou a idade) para gerar credibilidade.
- **Seja Direto e Breve**: O insight deve ser lido na tela do celular sem precisar "rolar" para baixo.
- **Exemplos de Insights para Inspirar a Geração**:
  - *Cenário Oportunidade (Vigor e Biomassa altos)*: "Dei uma olhada na sua propriedade e me animei: seus X hectares estão com uma saúde excelente e produzindo muito capim! Tá sobrando comida aí. Quer que eu calcule quantas cabeças de gado a mais você consegue colocar nessa área com segurança? 🐂"
  - *Cenário Alerta (Idade avançada e Vigor caindo)*: "Vi aqui que os pastos da sua fazenda são guerreiros, com mais de X anos, mas o satélite mostra que já começam a dar sinais de cansaço. Sabendo a quantidade exata de capim que você produz hoje, quer que eu calcule quantas cabeças a terra aguenta sem degradar? 🌱"
  - *Cenário Subutilização (Baixa Biomassa em área grande)*: "Você tem um espaço excelente de X hectares de pasto, mas notei que a produção de capim está abaixo do que essa terra realmente aguenta. Quer que eu te mostre exatamente onde o pasto está raleando para a gente resolver isso sem gastar muito? 🚜"