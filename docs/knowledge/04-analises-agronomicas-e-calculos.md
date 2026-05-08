# Manual do Usuário: Geração de Imagens e Mapas Temáticos

Este documento detalha o funcionamento do módulo de inteligência espacial do sistema, orientando sobre como os usuários podem solicitar, visualizar e interpretar imagens de satélite e mapas temáticos associados às suas propriedades rurais.

---

## 1. Uso: Capacidades e Como Gerar

O sistema oferece uma interface conversacional e automatizada para a geração de inteligência geográfica. Não é necessário navegar por menus complexos; o usuário pode simplesmente pedir os mapas no chat.

### 1.1. Capacidades do Sistema
* **Recorte Preciso (Clip):** Todas as imagens de satélite e mapas são rigorosamente recortados para respeitar os limites exatos (geometria/polígonos) da propriedade rural cadastrada.
* **Múltiplas Geometrias:** Caso uma propriedade seja composta por diferentes glebas, áreas descontínuas ou múltiplas matrículas agrupadas, o sistema identificará essa característica e gerará uma imagem individualizada para cada porção (feature) do imóvel, garantindo alta resolução e precisão no detalhamento.
* **Geração Sob Demanda:** O processamento ocorre em tempo real após a solicitação, consultando bases de dados geoespaciais em nuvem (como o Google Earth Engine).

### 1.2. Como solicitar uma imagem
Para que o assistente virtual compreenda e execute a geração do mapa sem falhas, o pedido do usuário deve conter, preferencialmente, três informações essenciais:
1. **O Tema do Mapa:** Qual o tipo de dado desejado (ex: Biomassa, Uso do Solo).
2. **O Ano de Referência:** Qual o ano do registro histórico. Caso não seja informada uma data, o sistema usa o ano atual.

### 1.3. Exemplos de Prompts para o Usuário
* *"Gere um mapa de biomassa."*
* *"Por favor, gere os mapas temáticos."*
* *"Quero ver a imagem de satélite com o uso do solo da minha área, no ano de 2020."*
* *"Você consegue puxar a biomassa de 2018 da Fazenda São João?"*

---

## 2. Dados: Catálogo e Especificações Técnicas

Esta seção cataloga todas as bases de dados espaciais integradas ao sistema, detalhando suas origens, resoluções temporais e limitações científicas. 

> **Aviso sobre o Gap Temporal:** Como utilizamos dados validados cientificamente, é comum haver uma defasagem (gap) de cerca de dois anos entre o ano corrente e a última coleção disponível. Os dados mais recentes, consolidados e auditados disponíveis referem-se ao ano de 2024.

### 2.1. Mapa de Biomassa Vegetal

A biomassa vegetal é um indicador crucial para estimar a quantidade de matéria seca (forragem) disponível em áreas de pastagem, bem como o vigor da vegetação nativa.

* **Origem do Dado:** MapBiomas - Coleção de Biomassa.
* **Período Disponível:** 2000 a 2024.
* **Periodicidade:** Anual (Gera um mapa consolidado representando o cenário daquele ano).
* **Descrição Detalhada:** Este mapa utiliza imagens de satélite e algoritmos de aprendizado de máquina validados pelo projeto MapBiomas para estimar a densidade da biomassa acima do solo acumulada no ano de referência.
* **Exemplos de Prompts Específicos:**
    * *"Faça a análise espacial de biomassa."*
    * *"Gere a imagem de biomassa de 2015."*