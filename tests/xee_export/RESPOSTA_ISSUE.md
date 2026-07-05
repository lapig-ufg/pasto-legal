# Testes de exportação via Xee + onde é melhor rodar o mapeamento (issue #112)

Fala, pessoal! Terminei os testes de exportação que foram pedidos e fui um pouco além pra
ajudar naquela dúvida de "processar no GEE ou trazer pro nosso servidor". No caminho, uma
pergunta boa do time me fez descobrir uma coisa importante (tem uma **correção** na seção 4).

Tá tudo na branch `feature/112-suporte-mapeamento-on-the-fly` — **não subi nada ainda**.

---

## 1. O que era pra fazer

Testar, via Xee, a exportação de dois imóveis de teste (`car_1` e `car_2`): as **64 features**
do Satellite Embedding V1 (2025) e a série de **NDVI gapfilled** do Sentinel-2 (2025),
convertendo pra **Int16**, salvando em **zarr** e **medindo o tempo** por imóvel.

## 2. Antes de tudo: o que são esses dois dados

Isso é a chave pra entender o resto, então vale explicar:

- **Satellite Embedding V1 (as "64 features"):** é um produto **anual** do Google. Pra cada
  pixel, num ano, ele dá um **vetor de 64 números** (bandas `A00`…`A63`) que "resume" a
  assinatura daquele lugar no ano (ele já junta várias imagens Sentinel, tira nuvem, e
  comprime tudo em 64 dimensões). Detalhe: pra usar o embedding (ex.: classificar), você
  **precisa das 64** — elas são as dimensões de **um vetor só**, não coisas que você escolhe.
  Formato: **64 variáveis × 1 data**.
- **NDVI gapfilled (as "~100 datas"):** é uma **série temporal**. Pra cada pixel é **um
  número** (o NDVI, o "verde" da vegetação) medido em **cada data** do ano — 100 passagens
  do Sentinel-2 em 2025, já preenchido/suavizado por regressão harmônica (sem buraco de
  nuvem). Formato: **1 variável × 100 datas**.

Ou seja, cada um tem um **formato natural diferente**: o embedding é *largo* (muitas
variáveis, 1 data); o NDVI é *comprido* (1 variável, muitas datas). Guarda isso — vai ser
crucial na seção 4.

## 3. O que estamos respondendo com essa análise

Antes de ver os números, vale deixar claro **qual pergunta esse teste responde**:

> *"Quando o fazendeiro pedir o mapa de pastagem, o backend consegue buscar os dados do
> GEE em tempo hábil via Xee, ou vai demorar demais?"*

Ou mais precisamente: **é viável usar Xee como transporte GEE→servidor** para os dois
insumos do pipeline (embedding para classificação LULC + NDVI para análise de vigor)?
E dentro disso: **Int16 ou Float32 faz diferença no tempo e no disco?**

Cada linha da tabela abaixo é uma resposta a uma fatia dessa pergunta:
- **mesmo dado, dtypes diferentes** → mostra o custo real de não usar Int16
- **mesmo dtype, imóveis diferentes** → mostra como o tempo escala com área
- **embedding vs NDVI** → mostra qual insumo é o gargalo do pipeline

## 4. Os números — matriz completa (2 imóveis × 2 dados × 2 dtypes)

Todos os testes rodaram em 2025, escala 10 m/pixel, zarr local.

**O que significa cada coluna da tabela:**

| Coluna | Significado |
|---|---|
| **dtype** | Tipo numérico do dado armazenado: `int16` (inteiro de 16 bits, ±32767) ou `float32` (ponto flutuante de 32 bits). Os valores originais do GEE (faixa [-1, 1]) são multiplicados por 10000 antes de virar int16, sem perda relevante de precisão. |
| **Dimensões (time×y×x)** | Forma do array exportado: `time` = nº de datas (embedding tem 1 data anual; NDVI tem ~100 datas); `y`/`x` = nº de pixels na grade UTM que cobre o bbox do imóvel a 10 m. |
| **t_open** | Tempo para o Xee abrir a conexão com o GEE e ler os metadados da coleção (sem baixar pixels). É sempre rápido (~1–3 s). |
| **t_export** | Tempo para baixar todos os pixels do GEE para a memória RAM local (`dataset.load()`). É o **gargalo principal** — dominado pelo número de variáveis/bandas, não pelo tamanho do imóvel. |
| **t_persist** | Tempo para gravar o array já em memória no disco em formato zarr (`.to_zarr()`). Sempre abaixo de 0,5 s nessas áreas. |
| **t_total** | Soma dos três anteriores: tempo real "do zero até o dado estar salvo em disco". É o número que importa para o backend. |
| **Tamanho** | Espaço ocupado pelo store zarr no disco após a compressão padrão. |

**car_1 — 3,2 ha** (grade 29 × 49 px a 10 m)

| Dado | dtype | Dimensões (time×y×x) | t_open | t_export (GEE) | t_persist (zarr) | **t_total** | Tamanho |
|---|---|---|---|---|---|---|---|
| Satellite Embedding (64 features) | **int16** | 1 × 29 × 49 | 1,4 s | 74,7 s | 0,3 s | **76,4 s** | 0,23 MB |
| Satellite Embedding (64 features) | float32 | 1 × 29 × 49 | 1,2 s | 70,3 s | 0,2 s | **71,6 s** | 0,25 MB |
| NDVI gapfilled (~100 datas) | **int16** | 100 × 29 × 49 | 2,8 s | 5,5 s | 0,03 s | **8,4 s** | 0,27 MB |
| NDVI gapfilled (~100 datas) | float32 | 100 × 29 × 49 | 1,7 s | 10,7 s | 0,03 s | **12,4 s** | 0,51 MB |

**car_2 — 54,9 ha** (grade 117 × 144 px a 10 m)

| Dado | dtype | Dimensões (time×y×x) | t_open | t_export (GEE) | t_persist (zarr) | **t_total** | Tamanho |
|---|---|---|---|---|---|---|---|
| Satellite Embedding (64 features) | **int16** | 1 × 117 × 144 | 1,5 s | 59,9 s | 0,2 s | **61,5 s** | 0,92 MB |
| Satellite Embedding (64 features) | float32 | 1 × 117 × 144 | 0,3 s | 75,8 s | 0,2 s | **76,3 s** | 1,11 MB |
| NDVI gapfilled (~100 datas) | **int16** | 100 × 117 × 144 | 3,0 s | 9,7 s | 0,03 s | **12,7 s** | 2,91 MB |
| NDVI gapfilled (~100 datas) | float32 | 100 × 117 × 144 | 1,5 s | 9,5 s | 0,03 s | **11,0 s** | 5,79 MB |

### O que os números revelam

**1. Int16 vale a pena, especialmente em disco e em propriedades maiores:**
- Embedding `car_2`: Int16 leva **61,5 s vs 76,3 s** no float32 — **1,2× mais rápido**.
- NDVI `car_1` em disco: **0,27 MB vs 0,51 MB** — Int16 ocupa **metade**.
- NDVI `car_2` em disco: **2,91 MB vs 5,79 MB** — Int16 ocupa **metade**.
- Não há razão para usar float32 — o custo de precisão (±0,0001) é irrelevante pro modelo.

**2. O tempo do embedding é quase independente do tamanho do imóvel:**
- `car_1` (3 ha): 76,4 s | `car_2` (55 ha, 17× maior): 61,5 s — mesmos ~60–80 s.
- O gargalo é o **número de variáveis** (64 bandas = ~64 requisições ao GEE), não os pixels.

**3. O NDVI escala suavemente com a área:**
- `car_1` (3 ha): 8,4 s | `car_2` (55 ha): 12,7 s — cresce ~1,5×, não 17×.
- 1 variável × 100 datas = ~1 requisição eficiente. É o formato natural de série temporal.

**4. NDVI é o insumo rápido; embedding é o gargalo do pipeline:**
- NDVI fica abaixo de 13 s em qualquer imóvel e qualquer dtype.
- Embedding fica entre 61–76 s — é onde está o custo com o layout atual.

## 5. Por que o embedding é lento — e a correção que eu devo a vocês

Alguém no time fez a pergunta certa: *"faz sentido comparar 64 variáveis × 1 data com 1
variável × 100 datas? O embedding precisa das 64, isso não é o que importa?"* **Sim, precisa
das 64 — e foi justamente investigar isso que revelou o pulo do gato.**

Testei a **mesma base** nos dois formatos (car_1, Int16):

| Exportei | nº de variáveis | nº de datas | tempo |
|---|---|---|---|
| embedding como **64 variáveis** | 64 | 1 | ~69 s |
| o **mesmo** embedding **empilhado** (1 variável) | 1 | 64 | **~3 s** |
| NDVI como **série** (1 variável) | 1 | 100 | ~7 s |
| o **mesmo** NDVI como **100 variáveis** | 100 | 1 | **~335 s** |

O que isso diz: o Xee fica lento quando o dado vem quebrado em **muitas variáveis** (ele faz
mais ou menos **1 requisição por variável**). Não é o volume de dado nem o número de datas —
é o **número de variáveis**.

**A correção importante:** eu tinha dito que "exportar o embedding é caro (~70 s)". Isso
**não está totalmente certo**. Peguei o embedding empilhado (o de 3 s) e **conferi pixel a
pixel**: são **exatamente os mesmos 64 valores** (diferença zero). Ou seja, **os 69 s eram
culpa do LAYOUT, não do embedding.** Se você empacota as 64 features numa variável só (com um
eixo "banda"), baixa **o mesmo dado ~24× mais rápido**. Então: **dá sim pra exportar o
embedding rápido via Xee — é só estruturar direito.**

> ⚠️ Esse empilhamento ainda **não está embutido** no código de exportação atual
> (`xee_export.py` usa layout de 64 variáveis). Os ~61–69 s da tabela acima são o custo
> real com o layout ingênuo; com a otimização cairia para ~3–5 s.

## 6. E o mapa de pastagem (a classificação de verdade)

O objetivo final é o fazendeiro pedir o **mapa de pastagem** e receber a **imagem
classificada + a área**. Implementei isso seguindo a lógica do script do Bernardo (amostra
MapBiomas + embedding → Random Forest, treina 2024 → prevê 2025) de **dois jeitos**:

| Imóvel | Jeito | Área de pasto | **Tempo total** |
|---|---|---|---|
| car_1 | **GEE (nuvem)** | 0,35 ha | **~2 s** |
| car_1 | Xee (local) | 0,33 ha | ~79 s |
| car_2 | **GEE (nuvem)** | 12,08 ha | **~4 s** |
| car_2 | Xee (local) | 12,6 ha | ~70 s |

- **As duas dão a mesma área** (0,35≈0,33; 12≈12,6) → o método funciona: treina num ano,
  prevê no outro.
- **Ressalva:** o ~78 s do caminho local é porque exportei o embedding do jeito ingênuo
  (64 variáveis, tabela da seção 4). Com o empilhamento da seção 5, esse download cai pra
  ~3 s → o caminho local deve cair pra **~10 s** (a confirmar rodando).

## 7. Então, onde é melhor rodar? (revisado)

- **Pro mapa/área hoje:** GEE (nuvem) ainda é o mais simples e direto (~2–4 s).
- **Mas o "local" não é mais o vilão lento que eu pintei** — com o embedding empilhado, trazer
  o dado pra cá é rápido (~3–5 s). Então a escolha vira menos "quem é mais rápido" e mais
  **"eu quero o dado aqui pra cruzar com outras camadas / usar modelo próprio (GeoCLAP)?"**.
- **Em qualquer caso, a chave é cachear:** processar uma vez e **salvar o resultado no
  S3/MinIO**, pra não refazer do zero a cada requisição — especialmente em propriedades
  grandes onde o download bruto (sem otimização) passa de 1 min.
- **Int16 sempre:** não tem razão pra usar float32 — é mais lento, ocupa o dobro em disco e
  a precisão perdida (±0,0001) é irrelevante pro modelo.

## 8. Como rodar / onde tá o código

```bash
uv pip install xee xarray zarr scikit-learn

.venv/bin/python -m tests.xee_export.run_benchmark          # matriz completa (8 combinações)
.venv/bin/python -m tests.xee_export.run_classification     # classificação GEE x local + imagens
.venv/bin/python -m tests.xee_export.layout_experiment      # prova do "nº de variáveis"
```

Tudo em `tests/xee_export/`. Detalhes técnicos completos em `EXPLICACAO.md`. Qualquer dúvida
é só chamar!
