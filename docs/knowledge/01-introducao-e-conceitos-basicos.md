# Capítulo 1: Introdução e Conceitos Básicos

O Pasto Legal é um sistema avançado de inteligência artificial que funciona diretamente pelo WhatsApp, projetado para oferecer suporte técnico e agronômico ao produtor rural. Por trás da interface simples do seu celular, opera uma equipe de agentes especializados (um Assistente de atendimento e um Analista técnico) que se conectam a bancos de dados oficiais, como o Cadastro Ambiental Rural (SICAR), e satélites globais, como o Google Earth Engine.

Nosso objetivo é transformar dados complexos de satélite e conhecimentos agronômicos em respostas rápidas, mapas claros e diagnósticos precisos para a sua fazenda.

---

## 1. Como se Comunicar com o Sistema

O Pasto Legal foi desenhado para ser tão natural quanto conversar com um agrônomo de confiança. Você não precisa navegar por menus complicados; basta enviar uma mensagem.

### 1.1. Interação por Texto e Áudio
O sistema compreende perfeitamente a linguagem natural, seja escrita ou falada. Você pode enviar áudios enquanto está no campo, e o sistema processará o seu comando e poderá, inclusive, responder com relatórios técnicos narrados por voz.

* **Exemplos de Prompts (Texto ou Áudio):**
    * *"Olá, gostaria de saber como está a saúde do meu pasto."*
    * *"Pode me enviar o relatório da fazenda por áudio, por favor?"*
    * *"Quais funcionalidades você tem disponíveis para me ajudar hoje?"*

### 1.2. Envio de Imagens (Fotos do Pasto)
O sistema possui visão computacional para ajudar na identificação de problemas em campo. Você pode tirar uma foto de uma área da sua fazenda e pedir uma análise.
**Regra de Ouro:** A sua pergunta ou comando **deve** ser enviada na legenda da própria imagem, e não como uma mensagem separada após a foto.

* **Exemplos de Prompts (Na legenda da foto):**
    * *"O que pode estar causando esse ressecamento no meu pasto?"*
    * *"Essa espécie de planta invasora é prejudicial para o gado?"*
    * *"Com base nessa foto, você acha que o pasto já está no ponto de pastejo?"*

---

## 2. Gerenciamento de Propriedades

Para que o Pasto Legal possa gerar mapas e dados precisos, o coração do sistema é a identificação da sua propriedade rural. **Importante:** Para ser cadastrada e analisada, a propriedade precisa obrigatoriamente possuir um registro no Cadastro Ambiental Rural (CAR) no sistema do SICAR.

### 2.1. Cadastrando uma Propriedade
O fluxo de cadastro é interativo e guiado pelo Agente SICAR.
* **Fluxo:** Você envia a localização (via GPS do WhatsApp) ou o número do CAR. O sistema localiza o imóvel, envia uma imagem de satélite do contorno para você verificar e pede sua confirmação.
* **Exemplos de Prompts:**
    * *(Enviando o alfinete de localização do WhatsApp)* *"Essa é a minha fazenda."*
    * *"Quero cadastrar minha propriedade. O número do meu CAR é [INSERIR NÚMERO]."*

### 2.2. Dando Nomes às Propriedades
Para facilitar o dia a dia, você pode (e deve) apelidar os seus registros com os nomes reais das fazendas.
* **Exemplos de Prompts:**
    * *"Pode salvar essa propriedade que acabamos de confirmar como 'Fazenda Vale Verde'."*
    * *"Renomeie o CAR final 4321 para 'Sítio do Sol'."*

### 2.3. Listando e Gerenciando o Cadastro
Você pode consultar ou limpar sua base de dados a qualquer momento.
* **Exemplos de Prompts:**
    * **Para listar:** *"Quais são as propriedades que eu tenho cadastradas no sistema?"* ou *"Me mostre a lista das minhas fazendas."*
    * **Para deletar:** *"Por favor, exclua a 'Fazenda Vale Verde' do meu cadastro."* ou *"Pode deletar a propriedade registrada sob o CAR [INSERIR NÚMERO]."*

---

## 3. Inteligência e Estatísticas de Pastagem

Com a propriedade cadastrada, o Agente Analista entra em ação cruzando dados de satélite para entregar um raio-x completo do seu pasto.

### 3.1. Estatísticas e Diagnósticos
O sistema pode gerar relatórios detalhados contendo os seguintes indicadores para um ano específico:
1. **Biomassa:** Quantidade de matéria seca acumulada no ano.
2. **Vigor:** Saúde da vegetação (índices vegetativos) no ano.
3. **Idade da Pastagem:** Há quanto tempo a área está estabelecida no ano.
4. **Uso e Cobertura da Terra:** O que é pasto, floresta, agricultura, etc.

* **Exemplos de Prompts:**
    * *"Gere as estatísticas de pastagem da Fazenda Vale Verde."*
    * *"Qual é o vigor e a biomassa acumulada na minha propriedade? Faça um diagnóstico."*
    * *"Me dê um relatório completo de uso do solo e idade do pasto do Sítio do Sol referente a 2022."*

### 3.2. Geração de Imagens de Biomassa
Além dos números, você pode solicitar a visualização espacial da distribuição de massa forrageira (onde o pasto está mais farto ou mais degradado).
* **Exemplos de Prompts:**
    * *"Gere a imagem de biomassa da Fazenda Vale Verde."*
    * *"Quero o mapa de satélite focado na biomassa da minha propriedade em 2022."*

---

## 4. Consultoria Agropecuária Especializada

O Pasto Legal não analisa apenas imagens de satélite; ele também funciona como um consultor técnico de bolso. O sistema é treinado com bases de conhecimento científico validadas, como os manuais e diretrizes da **EMBRAPA**, para esclarecer dúvidas sobre o manejo diário.

Seja sobre o gado, o solo ou a forrageira, você pode perguntar.

* **Exemplos de Prompts:**
    * *"Qual é a altura ideal de entrada e saída do gado no pasto de Braquiária Brizantha?"*
    * *"Tenho uma área com solo arenoso. Quais as melhores opções de capim para plantar?"*
    * *"Como devo fazer o cálculo de taxa de lotação (UA/ha) para evitar a degradação do meu pasto?"*
    * *"O que a Embrapa recomenda para recuperação de pastagens consorciadas que estão perdendo vigor?"*