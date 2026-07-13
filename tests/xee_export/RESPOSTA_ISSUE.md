# Resposta — testes de exportação Xee (issue #112)

Branch: `feature/112-suporte-mapeamento-on-the-fly` — sem push ainda.

---

## Pergunta 1: quanto tempo leva exportar os dados brutos via Xee?

Testado: **Satellite Embedding V1 (64 features)** e **NDVI gapfilled (~100 datas)**, Int16, zarr local.

### Satellite Embedding — 64 features × 1 data (Int16)

| Imóvel | Área | Grid (px) | t_open | t_export | t_persist | **t_total** | Disco |
|---|---|---|---|---|---|---|---|
| car_1 — Jaraguá | 3,2 ha | 1 × 29 × 49 | 1,4 s | 74,7 s | 0,3 s | **76,4 s** | 0,23 MB |
| car_2 — Jaraguá | 54,9 ha | 1 × 117 × 144 | 1,5 s | 59,9 s | 0,2 s | **61,5 s** | 0,92 MB |
| new_car_1 — Silvânia | 2073,5 ha | 1 × 643 × 940 | 1,5 s | 131,8 s | 0,4 s | **133,7 s** | 25,6 MB |
| new_car_2 — Córrego do Ouro | 23,5 ha | 1 × 94 × 48 | 0,4 s | 51,0 s | 0,2 s | **51,6 s** | 0,40 MB |

### NDVI Gapfilled — 1 variável × ~100 datas (Int16)

| Imóvel | Área | Datas | t_open | t_export | t_persist | **t_total** | Disco |
|---|---|---|---|---|---|---|---|
| car_1 — Jaraguá | 3,2 ha | 100 | 2,8 s | 5,5 s | 0,03 s | **8,4 s** | 0,27 MB |
| car_2 — Jaraguá | 54,9 ha | 100 | 3,0 s | 9,7 s | 0,03 s | **12,7 s** | 2,91 MB |
| new_car_1 — Silvânia | 2073,5 ha | 100 | 2,1 s | 48,3 s | 0,1 s | **50,6 s** | 104,6 MB |
| new_car_2 — Córrego do Ouro | 23,5 ha | 404¹ | 7,8 s | 11,9 s | 0,03 s | **19,7 s** | 1,43 MB |

> ¹ Córrego do Ouro cobre múltiplos tiles S2 sobrepostos → GEE retorna ~404 cenas.

**Por que o embedding é mais lento que o NDVI?** O Xee faz ~1 requisição por variável. Embedding = 64 variáveis → lento. NDVI = 1 variável × N datas → rápido. Não é o volume de pixels, é o número de variáveis.

---

## Pergunta 2: e o mapa de pastagem — GEE ou local?

Pipeline: MapBiomas classe 15 → amostras → Random Forest → classifica embedding 2025. Dois caminhos testados.

### `classify_gee` — tudo no GEE server-side

| Imóvel | Área pasto | **t_total** | Resultado |
|---|---|---|---|
| car_1 — Jaraguá (3 ha) | 0,35 ha | **~2 s** | PNG |
| car_2 — Jaraguá (55 ha) | 12,08 ha | **~4 s** | PNG |
| new_car_1 — Silvânia (2073 ha) | 711,55 ha | **9,78 s** | PNG |
| new_car_2 — Córrego do Ouro (23 ha) | 15,18 ha | **12,37 s** | PNG |

### `classify_xee` — Xee baixa embedding, sklearn classifica local

| Imóvel | Área pasto | **t_total** | t_download Xee | t_predict sklearn |
|---|---|---|---|---|
| car_1 — Jaraguá (3 ha) | 0,33 ha | **~79 s** | ~76 s | <1 s |
| car_2 — Jaraguá (55 ha) | 12,60 ha | **~70 s** | ~69 s | <1 s |
| new_car_1 — Silvânia (2073 ha) | 758,17 ha | **136 s** | 131 s | 0,22 s |
| new_car_2 — Córrego do Ouro (23 ha) | 16,18 ha | **50 s** | 47 s | 0,03 s |

> O sklearn é quase instantâneo — todo o custo é o Xee baixando 64 variáveis.

---

## Pergunta 3 (nova task @leandroleal): exportar só o `classified` via Xee fica abaixo de 20 s?

### ✅ Sim. Resultado: `classify_gee_xee`

GEE classifica inteiramente no servidor (mesmo pipeline do `classify_gee`). Xee baixa só o raster resultado — **1 variável binária** (pasto=1 / não-pasto=0) × 1 data.

| Imóvel | Área pasto | t_xee_open | t_xee_export | t_xee_persist | **t_total** | Disco (zarr) |
|---|---|---|---|---|---|---|
| new_car_1 — Silvânia (2073 ha) | 714,37 ha | 0,98 s | 4,30 s | 0,03 s | **7,49 s ✅** | 0,024 MB |
| new_car_2 — Córrego do Ouro (23 ha) | 15,73 ha | 1,02 s | 1,24 s | 0,03 s | **3,92 s ✅** | 0,008 MB |

Ambos **bem abaixo de 20 s**.

---

## Comparação final — os 3 métodos

| Imóvel | `classify_gee` | `classify_gee_xee` | `classify_xee` |
|---|---|---|---|
| **new_car_1 (2073 ha)** | 9,78 s — só PNG | **7,49 s** — zarr 24 KB | 136 s — zarr 26 MB |
| **new_car_2 (23 ha)** | 12,37 s — só PNG | **3,92 s** — zarr 8 KB | 50 s — zarr 0,4 MB |

| Imóvel | Área `classify_gee` | Área `classify_gee_xee` | Área `classify_xee` |
|---|---|---|---|
| new_car_1 (2073 ha) | 711,55 ha | 714,37 ha | 758,17 ha |
| new_car_2 (23 ha) | 15,18 ha | 15,73 ha | 16,18 ha |

`classify_gee` e `classify_gee_xee` concordam em <0,4% (mesmo RF no GEE). O `classify_xee` difere ~6% porque sklearn e `smileRandomForest` do GEE são implementações distintas.

---

## Por que `classify_gee_xee` e não `classify_gee`?

A diferença é o que você tem em mãos depois de rodar:

| O que você quer fazer | `classify_gee` | `classify_gee_xee` |
|---|---|---|
| Saber a área de pasto | ✅ | ✅ |
| Cachear e reusar o resultado | ❌ | ✅ |
| Exportar GeoTIFF / servir tiles | ❌ | ✅ |
| Sobrepor com outro shapefile local | ❌ | ✅ |
| Análise espacial local | ❌ | ✅ |
| Funcionar offline após o primeiro run | ❌ | ✅ |

Com `classify_gee` o raster classificado fica no servidor do GEE — você recebe apenas um número e um PNG estático. Próxima consulta do mesmo imóvel: paga os ~9–12 s novamente.

Com `classify_gee_xee` o raster está em disco (zarr, ~8–24 KB). Próxima consulta: leitura local em < 1 s, sem tocar o GEE.

## Recomendação

**`classify_gee_xee` é a solução.** É o método mais rápido dos três, persiste o raster completo em disco (zarr) e abre caminho para cache no storage do LAPIG:

- **Primeira requisição:** ~4–8 s → GEE classifica, Xee baixa o raster, salva no cache.
- **Requisições seguintes:** leitura do zarr em cache → **< 1 s**.

---

## Como rodar

```bash
# Benchmark completo (todos os 3 métodos + export de dados brutos):
.venv/bin/python -m tests.xee_export.run

# Só classificação, sem classify_xee (~75 s):
.venv/bin/python -m tests.xee_export.run --skip-xee --skip-embed

# Benchmark NDVI gapfilled:
.venv/bin/python -m tests.xee_export.run_ndvi
```

Código em `tests/xee_export/`. Detalhes técnicos em `EXPLICACAO.md`.
