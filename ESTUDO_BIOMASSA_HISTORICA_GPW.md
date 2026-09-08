# Biomassa Histórica de Pastagem (GPW) — guia de estudo

Documento pra entender: (1) o que a issue #112 pediu, (2) o que o script de
referência do GEE faz linha por linha, e (3) o que a gente implementou e por
que essa abordagem é boa. Fontes: issue real no GitHub (via API), script que
você colou na conversa, e o código que ficou pronto na branch
`feature/112-suporte-mapeamento-on-the-fly`.

---

## Parte 1 — A issue #112, contexto completo

### O que é

A issue **#112 "Suporte para mapeamento on-the-fly"** (milestone `v0.4`,
aberta por `leandroleal`) não é só sobre biomassa — é um épico com 5
subtarefas, cada uma atribuída a uma pessoa:

| # | Subtarefa | Responsável | Status |
|---|---|---|---|
| 1 | **Uso e cobertura da terra** — treinar Random Forest com amostras do MapBiomas 10m + Satellite Embedding V1, prever 2024/2025 | @boliveirageo | ✅ feito |
| 2 | **Biomassa de pastagem** — calibrar `uGPP` do GPW com `LUE Factor = 0.5` | @vieiramesquita | 🔲 (é a nossa parte) |
| 3 | **Idade do pasto** — downsampling 30m→10m dos dados do MapBiomas + interpolação simplificada pra 2025 | @boliveirageo | 🔲 |
| 4 | **Vigor de pastagem** — modelagem de séries temporais harmônicas a 10m | @vieiramesquita | 🔲 |
| 5 | **Integração** no Pasto Legal | @James-jamames | 🔲 |

A subtarefa 1 (uso e cobertura da terra) é **exatamente** o
`classify_pasture_on_the_fly` que já existe no código (RandomForest treinado
com MapBiomas + embedding, prevê o ano seguinte) — foi implementada e
integrada em **15/07**, antes da nossa sessão.

### Linha do tempo (o que já rolou nessa issue antes de chegarmos)

1. **11/05** — `leandroleal` abre a issue com as 5 subtarefas.
2. **24/06** — `vieiramesquita` sugere harmonizar Sentinel-2 + Cloud Score+.
3. **25/06** — `leandroleal` pede pra você (`ThiagoHF31`) testar **exportação
   via Xee** (a lib que baixa dados do GEE pro Python como array) pra dois
   imóveis reais, medindo tempo de: Satellite Embedding (64 bandas) vs. NDVI
   com ~100 datas. Pergunta central: *"quando o fazendeiro pedir o mapa, o
   backend consegue buscar do GEE em tempo hábil, ou é melhor rodar tudo na
   nuvem?"*
4. **05/07** — você reporta os números reais (esses viraram a base do nosso
   plano agora):

   | Dado | Variáveis | Datas | Tempo de export |
   |---|---|---|---|
   | Satellite Embedding | 64 bandas | 1 | **~70–150 s** |
   | NDVI gapfilled | 1 banda | ~100 | **~8–53 s** |

   Ou seja: **o que pesa é o número de bandas/variáveis, não o número de
   datas**. 64 bandas numa data só é muito mais lento que 1 banda em 100
   datas. Esse achado é a razão de termos exportado os 25 anos de biomassa
   como **1 banda com 25 passos de tempo**, e não 25 bandas — e por isso ficou
   rápido (~7–10s na prática, você viu rodando).

   Você também mediu o mapa de pastagem em si: rodar a classificação **toda
   dentro do GEE** e baixar só o resultado (1 banda binária) levava **~4–12s**,
   contra **~65–145s** baixando os dados brutos (embedding) e classificando
   localmente. Aí que veio a decisão: classificar no GEE, exportar só o
   resultado via Xee.

5. **07/07** — `leandroleal` confirma: exporte só a classificação, se ficar
   abaixo de 20s é uma ótima solução (tem storage dedicado no LAPIG pra isso).
6. **15/07** — você entrega: `classify_pasture_on_the_fly` (hoje em
   `pasture_classification.py`), tool `generate_pasture_classification_image`
   registrada no `analyst_agent`, cache em `.zarr` local (24s primeira vez,
   1,4s com cache), `xee`/`xarray`/`zarr`/`affine` viram dependências reais.
7. **05/08** — `leandroleal` reabre o assunto: *"Ainda precisamos implementar
   o cálculo on-the-fly para algumas camadas de pastagem"* e pede
   especificamente a **biomassa histórica**, com o texto exato:

   > **@ThiagoHF31** Utilize esse script para estimar a biomassa histórica
   > (2000-2024) on-the-fly para as áreas de pastagens, com 10-m de resolução
   > espacial, dentro da propriedade rural: [script GEE]
   >
   > Use o script acima apenas como referência para acessar o ImageCollection
   > (`ee.ImageCollection("projects/global-pasture-watch/assets/ggpp-30m/v1/ugpp_m")`)
   > e estimar a biomassa para a totalidade dos pixels da propriedade rural,
   > exportando todos os pixels para zarr e salvando no S3.

   Essa é a mensagem que puxou o trabalho que fizemos agora.

### Por que LUE = 0.5 (a ciência por trás do número)

Fui atrás da discussão científica que a issue original linka
([wri/global-pasture-watch#2](https://github.com/wri/global-pasture-watch/discussions/2)).
Resumo:

- O dado bruto do GPW (`ugpp_m`) é calculado com um **LUEmax genérico de 1
  gC/m²/dia/MJ** — sem diferenciar tipo de vegetação.
- Pra grassland em geral, o MODIS usa **0,86**.
- Pra pastagem cultivada **brasileira** especificamente (dominada por
  *Urochloa brizantha*, a braquiária), o MapBiomas determinou um valor mais
  conservador: **0,5** — é a esse número que o `LUE Factor = 0.5` da issue se
  refere.

Ou seja: `GRASS_LUEMAX_FACTOR = 0.50` não é um número arbitrário — é uma
recalibração *land-cover-specific* do dado genérico do GPW, validada pelo
MapBiomas pra pastagem brasileira. É por isso que reaproveitamos exatamente
esse valor (e não inventamos um novo) tanto no script de referência quanto no
nosso código.

---

## Parte 2 — O script de referência, linha por linha

Esse é o script completo que o `leandroleal` linkou (você colou ele na
conversa):

```javascript
var ugppVis = {min: 0, max: 25, palette: "f95737,edf899,f7d56e,8da82f,093823"}

var estimateGrassDryBiomass = function(year, conversion_factor, region) {
  var grassland_mask = grassland_c.filterDate(year+'-01-01',year+'-12-31')
    .first()
    .clip(region)
    .gte(1)

  return ugpp_m.filterDate(year+'-01-01',year+'-12-31')
    .first()
    .mask(grassland_mask)
    .multiply(conversion_factor)
    .rename('t_ha_year')
}

var GRASS_LUEMAX_FACTOR = 0.50 // gC/m²/day/MJ
var IPCC_FACTOR = 2.7
var UNIT_COVERSION_FACTOR = 0.01
var YEAR = 2022

var DRY_BIOMASS_FACTOR = GRASS_LUEMAX_FACTOR * IPCC_FACTOR * UNIT_COVERSION_FACTOR
var country = fao_gaul.filter(ee.Filter.eq('ADM0_NAME', 'Brazil'))

print("Biomass conversion factor:", DRY_BIOMASS_FACTOR)
var grassDryBiomass = estimateGrassDryBiomass(YEAR, DRY_BIOMASS_FACTOR, country)

Map.addLayer(grassDryBiomass, ugppVis, "Grassland dry biomass "+YEAR+" (T/ha/year)");
```

`grassland_c`, `ugpp_m` e `fao_gaul` não aparecem definidos no script — no GEE
Code Editor eles vêm da seção "Imports" (não colada), e correspondem a:

- `grassland_c` → `ee.ImageCollection("projects/global-pasture-watch/assets/ggc-30m/v1-1/grassland_c")`
- `ugpp_m` → `ee.ImageCollection("projects/global-pasture-watch/assets/ggpp-30m/v1/ugpp_m")`
- `fao_gaul` → dataset padrão do GEE com limites administrativos de países (FAO GAUL)

Confirmei ao vivo contra o GEE: as duas primeiras collections têm **25
imagens cada, uma por ano, 2000→2024** — é literalmente o período "histórico"
que a issue pediu.

### Bloco por bloco

**1. Parâmetros de visualização**
```javascript
var ugppVis = {min: 0, max: 25, palette: "f95737,edf899,f7d56e,8da82f,093823"}
```
Só define como o resultado vai ser **pintado no mapa** do GEE Code Editor:
valores de 0 a 25 t/ha, gradiente de laranja-avermelhado (baixo) até verde
escuro (alto). Não afeta o cálculo, só a cor na tela.

**2. A função principal**
```javascript
var estimateGrassDryBiomass = function(year, conversion_factor, region) {
  var grassland_mask = grassland_c.filterDate(year+'-01-01',year+'-12-31')
    .first()
    .clip(region)
    .gte(1)

  return ugpp_m.filterDate(year+'-01-01',year+'-12-31')
    .first()
    .mask(grassland_mask)
    .multiply(conversion_factor)
    .rename('t_ha_year')
}
```
Recebe um ano, um fator de conversão e uma região geográfica. Passo a passo:

| Linha | O que faz |
|---|---|
| `grassland_c.filterDate(year+'-01-01', year+'-12-31')` | Filtra a collection de máscara de pastagem pra pegar só a imagem daquele ano específico (a collection tem 1 imagem/ano) |
| `.first()` | Pega essa única imagem resultante do filtro |
| `.clip(region)` | Corta a imagem pros limites da `region` (não carrega dado do mundo inteiro) |
| `.gte(1)` | "Maior ou igual a 1" — vira uma máscara binária: 1 onde é pastagem, 0 onde não é |
| `ugpp_m.filterDate(...).first()` | Mesmo padrão, mas pega a imagem de produtividade (GPP) daquele ano |
| `.mask(grassland_mask)` | Aplica a máscara: pixels fora de pastagem viram "sem dado" (NaN) |
| `.multiply(conversion_factor)` | Multiplica cada pixel restante pelo fator — converte GPP em biomassa |
| `.rename('t_ha_year')` | Renomeia a banda resultante pra um nome legível ("toneladas/hectare/ano") |

**3. As constantes de calibração**
```javascript
var GRASS_LUEMAX_FACTOR = 0.50 // gC/m²/day/MJ
```
Fator de eficiência de uso da luz específico da braquiária brasileira (ver
Parte 1). Recalibra o dado genérico do GPW pra essa espécie de pasto.

```javascript
var IPCC_FACTOR = 2.7
```
Converte massa de **carbono** pra massa de **biomassa seca**. Plantas não são
carbono puro — esse fator "desfaz" a fração de carbono assumida no cálculo de
GPP e devolve o peso total de matéria seca.

```javascript
var UNIT_COVERSION_FACTOR = 0.01
```
Isso aqui é só matemática de unidades, não biologia: o dado vem em **gramas
de carbono por m²** (gC/m²) e queremos **toneladas por hectare** (t/ha).
1 hectare = 10.000 m² e 1 tonelada = 1.000.000 g, então:
`10.000 / 1.000.000 = 0,01`.

```javascript
var YEAR = 2022
```
Só escolhe qual ano visualizar nessa rodada do script (é uma demo de 1 ano só
— a gente generalizou isso pra rodar os 25 anos de uma vez).

**4. Monta o fator final e executa**
```javascript
var DRY_BIOMASS_FACTOR = GRASS_LUEMAX_FACTOR * IPCC_FACTOR * UNIT_COVERSION_FACTOR
```
Multiplica os três: `0,5 × 2,7 × 0,01 = 0,0135`. **Esse número único** é o
que multiplica cada pixel de GPP pra virar biomassa seca em t/ha — é
exatamente essa constante que reaproveitamos no nosso código
(`DRY_BIOMASS_FACTOR` em `pasture_biomass.py`).

```javascript
var country = fao_gaul.filter(ee.Filter.eq('ADM0_NAME', 'Brazil'))
```
Pega o polígono do **Brasil inteiro** como região de análise (o script é uma
demo em escala de país). No nosso caso, trocamos isso pelo polígono da
**propriedade rural específica** do usuário — mesma lógica, escala menor.

```javascript
print("Biomass conversion factor:", DRY_BIOMASS_FACTOR)
```
Só imprime o valor no console do GEE, pra conferência visual (0,0135).

```javascript
var grassDryBiomass = estimateGrassDryBiomass(YEAR, DRY_BIOMASS_FACTOR, country)
```
Chama a função de verdade: ano 2022, o fator calculado, o Brasil como região.

```javascript
Map.addLayer(grassDryBiomass, ugppVis, "Grassland dry biomass "+YEAR+" (T/ha/year)");
```
Desenha o resultado no mapa interativo do GEE Code Editor — só pra
inspeção visual no navegador, não exporta nem salva nada.

### Exemplo numérico prático

Um pixel qualquer com valor bruto de `ugpp_m` = **1500 gC/m²/ano**:

```
biomassa = 1500 × 0,0135 = 20,25 t/ha/ano
```

Isso bate com a ordem de grandeza real que vimos rodando pra propriedade de
teste (`GO-5205703-...`): média entre **23,6 e 28 t/ha/ano** ao longo de
2000-2024 — dentro da faixa `min: 0, max: 25` que o próprio `ugppVis` do
script assume como "normal".

---

## Parte 3 — O que a gente implementou, e por que é bom

### O que já existia (T2G) e por que não bastava

Antes dessa sessão, a biomassa no chat (`generate_biomass_image`,
`get_pasture_stats`) vinha de outra fonte: `wri-lcl-time2graze/ugpp_10m_v1`
(T2G). Dois problemas reais:

1. **Cobertura limitada** — só funciona pra propriedades dentro de uma lista
   fixa de 43 tiles Sentinel-2, hardcoded no código.
2. **Sem histórico** — quando a propriedade cai fora desses tiles, o sistema
   caía num fallback de outro asset (MapBiomas) travado no ano de 2024, sem
   nenhuma série temporal.

O pedido do `leandroleal` resolve os dois de uma vez: o GPW é global (não
uma lista de tiles) e tem 25 anos publicados.

### O que construímos

- **`app/services/geospatial/pasture_biomass.py`** (novo) — usa a *mesma*
  fórmula e os *mesmos* assets do script de referência, mas: (a) a região é a
  propriedade do usuário, não o Brasil inteiro; (b) roda os **25 anos numa
  única exportação** (1 banda × 25 datas, não 25 bandas — pelo achado do
  05/07 na issue); (c) baixa **todos os pixels** via Xee (não só estatística
  agregada) e cacheia em `.zarr` local (S3 configurado, mas não ativo em
  dev, como você pediu); (d) gera um gráfico de tendência.
- **`app/services/geospatial/gee.py`** — o fallback de `get_biomass` e a nova
  `retrieve_gpw_biomass_image` passaram a usar essa mesma fonte GPW no lugar
  do MapBiomas antigo, mantendo o T2G como primeira tentativa (você pediu
  pra manter a granularidade mensal quando disponível).
- **Nova tool `get_pasture_biomass_history`** — pra você testar a série
  completa direto no chat (validamos ao vivo: pico em 2000 com 27,93 t/ha,
  mínimo em 2016 com 23,62 t/ha, batendo com os dados calculados).

### Por que essa abordagem é boa

1. **Reaproveita ciência já validada** — o fator `0,5 × 2,7 × 0,01` não foi
   inventado por nós; é a calibração que o próprio MapBiomas/GPW publicou
   pra pastagem brasileira. Zero risco de reinventar biologia errado.
2. **Reaproveita engenharia já validada** — o padrão "1 variável × N datas é
   barato, N variáveis é caro" não foi um palpite: são números reais que
   você mesmo mediu e documentou na issue em 05/07. Testamos e bateu:
   ~7-10s pra baixar 25 anos de dado, pixel a pixel, de uma propriedade real.
3. **Resolve os dois problemas reais do T2G** — cobertura nacional (não 43
   tiles) e histórico de verdade (25 anos, não 1 ano fixo) — sem quebrar o
   que já funcionava (T2G continua sendo tentado primeiro).
4. **Achamos e corrigimos um bug real no caminho**: os assets do GPW são
   nativos em graus (EPSG:4326), diferente do Satellite Embedding (UTM
   métrico) que o resto do código já usava — sem perceber isso, a grade de
   exportação virava 1×1 pixel (todo NaN). Corrigido derivando o UTM certo a
   partir do centroide de cada propriedade.
5. **Validado de ponta a ponta**: testes automatizados contra o GEE real +
   testado manualmente no chat de verdade, com propriedade real, produzindo
   número e gráfico coerentes com o que o próprio script de referência
   descreve.
