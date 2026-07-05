# Testes de exportação via Xee — issue #112 (mapeamento on-the-fly)

> Documento técnico completo da parte do **@ThiagoHF31** na issue #112
> ("Suporte para mapeamento on-the-fly"). Explica **o que foi pedido, o que foi feito,
> como, por quê, onde está cada arquivo e se cumpre o que foi solicitado.**
>
> Branch: `feature/112-suporte-mapeamento-on-the-fly` (criada de `origin/develop`,
> **sem push** — trabalho local de teste). Data: 2026-07-02.

---

## 1. O que foi pedido (o enunciado)

Dentro da issue #112, a tarefa específica era:

> Implementar testes de **exportação (via Xee)** considerando dois imóveis rurais
> (`car_1` & `car_2`):
> 1. Exportação das **64 features** de 2025 do **Satellite Embedding V1** para cada imóvel.
> 2. Exportação das **~101 features/datas** de 2025 da série temporal **Sentinel-2 NDVI gapfilled** para cada imóvel.
>
> Pontos importantes:
> - Converter os dados para **Int16** (exportação em Float32 pode ser bem mais lenta).
> - Persistir o xarray localmente em **zarr/geozarr**.
> - Reportar o **tempo total** de exportação do GEE + persistência local, **por imóvel**.

O objetivo maior (dito pelo James): avaliar se dá para usar o **Xee no back-end do
Pasto Legal** para fazer cruzamentos espaciais localmente (em xarray), em vez de ir
e voltar no GEE a cada operação. **Ou seja: estes testes são um _benchmark de
viabilidade_ do caminho GEE → xarray/zarr local via Xee.**

---

## 2. Conceito-chave: por que isso é Python/Xee (e não "só no GEE")

- **Xee é uma biblioteca Python** (`xee`) que abre uma `ee.ImageCollection` como um
  `xarray.Dataset`. Ela **não existe** no Code Editor (JavaScript) do GEE.
- A **computação continua no GEE** (server-side): embedding, NDVI, regressão harmônica —
  tudo roda no Google. O Xee é a **ponte de download** do resultado já computado.
- Os requisitos (persistir **zarr local** + medir **tempo de persistência local**) só
  existem no lado Python. O GEE puro exporta GeoTIFF/Asset — nunca xarray/zarr. Logo,
  **implementar o lado Python é a tarefa**; não há atalho "GEE-only".

---

## 3. Mapa de arquivos

Tudo novo fica em **`tests/xee_export/`** (isolado, no espírito do `tests/ee_scripts/`).
**Nenhum arquivo da aplicação (`app/`) foi modificado.**

| Arquivo | Papel |
|---|---|
| `tests/xee_export/export.py` | **Módulo core.** Init do GEE (high-volume), loader das geometrias, grade UTM, os dois exportadores (embedding + NDVI gapfilled), cast Int16, persistência zarr, métricas. |
| `tests/xee_export/classification.py` | **Módulo de classificação.** Duas estratégias de RF pasto/não-pasto (GEE-nativo + Xee-local) e geração do mapa de biomassa. |
| `tests/xee_export/run_benchmark.py` | **Entry-point principal.** Roda a matriz completa de exportação (2 imóveis × 2 dados × 2 dtypes = 8 combinações), imprime tabela e salva relatório JSON. |
| `tests/xee_export/run_classification.py` | **Entry-point de classificação.** Compara GEE-nativo vs Xee-local em ambos os imóveis + gera imagens. |
| `tests/xee_export/layout_experiment.py` | **Experimento de apoio.** Prova controlada de que o gargalo do Xee é o nº de variáveis, não o nº de datas. Referência para entender os resultados. |
| `tests/xee_export/__init__.py` | Torna o diretório um pacote (`import tests.xee_export...`). |
| `tests/xee_export/RESPOSTA_ISSUE.md` | Resposta em linguagem humana para postar na issue. |
| `tests/xee_export/EXPLICACAO.md` | Este documento técnico. |
| `tmp/xee_export/*.zarr` | **Saídas** (stores zarr por imóvel/teste/dtype). `tmp/` é gitignored. |
| `tmp/xee_export/benchmark_report.json` | Relatório de tempos/tamanhos gerado a cada run. |
| `tmp/xee_export/classification_report.json` | Relatório de classificação (área, tempo por metodologia). |
| `tmp/xee_export/images/` | Mapas PNG gerados: pasto GEE, pasto local, biomassa. |

Dependências (`xee`, `xarray`, `zarr`, `scikit-learn`) foram instaladas **no venv via
`uv pip install`**, de propósito **fora do `pyproject.toml`/`uv.lock`** — assim as deps
de teste não "contaminam" o manifesto da aplicação nem entram num commit acidental.

---

## 4. Como rodar

Pré-requisitos: venv do projeto + `.env` com `GEE_PROJECT`, `GEE_SERVICE_ACCOUNT`,
`GEE_KEY_FILE` (já presentes).

```bash
cd "/Users/thiagohonoratoferreira/Documents/PASTO LEGAL - CEIA/pasto-legal"

# (uma vez) instalar as libs de teste no venv:
uv pip install xee xarray zarr scikit-learn

# benchmark de exportação — matriz completa (8 combinações, ~6 min):
.venv/bin/python -m tests.xee_export.run_benchmark

# classificação pasto/não-pasto — GEE-nativo vs Xee-local + imagens:
.venv/bin/python -m tests.xee_export.run_classification

# experimento de apoio — prova do "nº de variáveis domina o tempo":
.venv/bin/python -m tests.xee_export.layout_experiment
```

Uso programático (um teste, um imóvel):

```python
from tests.xee_export.export import load_test_properties, export_ndvi_gapfilled
prop = load_test_properties()[0]                 # car_1
metrics = export_ndvi_gapfilled(prop["name"], prop["roi"], year=2025)
```

---

## 5. Os imóveis de teste (car_1 / car_2)

Vêm de `app/utils/mocks/property_mock.json` (2 imóveis reais em **Jaraguá-GO**),
escolhidos porque têm **tamanhos bem diferentes** — ótimo para ver se o tempo escala
com a área:

- **car_1**: `GO-5211800-E85CBBBF7DA34628BCA06B78357D39F6`, ~**3,2 ha**.
- **car_2**: `GO-5211800-987B29E7E47A4454BAEF582557AB89F3`, ~**54,9 ha**.

Ambos são `MultiPolygon` → viram `ee.Geometry.MultiPolygon(coords)`.

---

## 6. Teste 1 — Satellite Embedding V1 (64 features, 2025)

**O que é:** o *AlphaEarth/Satellite Embedding V1* (`GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL`)
é um dataset anual de **64 bandas** (`A00`…`A63`), a 10 m, onde cada pixel é um vetor de
64 números que "resume" toda a assinatura espaço-temporal daquele local no ano. É a base
que a equipe usa para o mapeamento de uso/cobertura via Random Forest.

**Como foi implementado** (`export_satellite_embedding` em `export.py`):

```python
collection = (ee.ImageCollection("GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL")
    .filterBounds(roi).filterDate("2025-01-01", "2026-01-01"))
# cast Int16 no lado do GEE (ver seção 8):
collection = collection.map(lambda img: img.multiply(10000).toInt16()
    .copyProperties(img, ["system:time_start"]))
```

Depois abre via Xee, força o download, converte para int16 e grava o zarr. Como o
embedding é anual, há **1 imagem** com **64 bandas** → no xarray vira **64 variáveis**
(`A00`…`A63`) com `time=1`.

**Por que 64 variáveis importa:** ver seção 9 (é a razão do embedding ser lento).

---

## 7. Teste 2 — Sentinel-2 NDVI gapfilled (~100 datas, 2025)

**O método (traduzido fielmente do script EE de referência):** é um **modelo harmônico**
(regressão), não uma interpolação simples. Passo a passo (`_build_ndvi_gapfilled`):

1. **Sentinel-2 SR Harmonized** (`COPERNICUS/S2_SR_HARMONIZED`) linkado ao
   **Cloud Score+** (`GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED`) pela banda `cs_cdf`.
2. **Máscara de nuvem**: mantém pixel se `cs_cdf >= 0.60`; escala óptica `/10000`.
3. **NDVI** = `(B8 − B4) / (B8 + B4)`.
4. Monta as **variáveis independentes**: `constant`, `t` (tempo em radianos desde a época)
   e **3 harmônicos** → `cos_1..3`, `sin_1..3` (total 8 termos).
5. **`ee.Reducer.linearRegression`** ajusta o modelo harmônico **por pixel** → coeficientes.
6. Para **cada data de aquisição**, calcula o **NDVI ajustado**
   `NDVI_GAPFILLED = Σ (termo × coeficiente)` — uma curva suave, **sem nuvens/gaps**.

### Decisão importante: dimensão `time` em vez de `.toBands()`

No Xee exporto a **coleção** (mantendo o eixo temporal): dims **`(time≈100, y, x)`**
com **1 variável** `NDVI_GAPFILLED` — em vez das 100 bandas/variáveis do `.toBands()`.

Por quê:
- É a representação **idiomática de "série temporal"** em xarray (fácil de fatiar por data).
- É **muito mais rápida**: o gargalo do Xee é o **nº de variáveis** (cada banda = 1 request).
  100 variáveis seriam ~100 requests (lento); 1 variável × 100 datas é ~1 request eficiente.
  **Medido: NDVI ~7-10 s vs embedding ~60-70 s** (seção 9).
- É **equivalente** ao `.toBands()` — só muda o layout (eixo `time` vs 100 nomes de banda).

> Nota: saiu **`time=100`** porque é o nº real de cenas S2 sobre os imóveis em 2025;
> o "~101" do enunciado é a ordem de grandeza típica da região.

---

## 8. Detalhes técnicos que exigiram decisão (e o porquê)

### 8.1 A API do `xee 0.1.1` é de baixo nível
A versão instalada **não** aceita `scale`/`geometry`/`projection`. Ela exige a **grade de
pixels explícita**: `crs` + `crs_transform` (um `affine.Affine`) + `shape_2d`. Por isso a
função `_utm_grid` calcula o bbox do imóvel projetado em UTM e monta:
`transform = Affine(10, 0, x_min, 0, -10, y_max)` e `shape_2d = (width, height)`.
> Descoberto empiricamente (e confirmado em `xee/ext.py:709`): `shape_2d[0]→x`, `[1]→y`.

### 8.2 Int16 — onde e por quê
- **Cast no lado do GEE** (`.multiply(10000).toInt16()`): faz a **transferência pela rede
  ser int16** (2 bytes) em vez do `double` nativo (8 bytes), porque o `computePixels`
  devolve no tipo da banda.
- **Fator 10000**: o embedding ∈ [-1, 1] e o NDVI ∈ [-1, 1] → ×10000 cabe folgado no
  int16 ([-32768, 32767]). No NDVI aplico `.clamp(-1, 1)` antes, por segurança contra
  extrapolação do modelo harmônico.
- **`dataset.astype("int16")` depois do load**: o `xee 0.1.1` **hardcoda float32** em
  memória (`ext.py:707`), ignorando o tipo da banda. Converto de volta para int16 antes
  de gravar o zarr — garantindo o **armazenamento em Int16**. É lossless (os valores já
  são inteiros na faixa do int16).

### 8.3 CRS derivado da **fonte**, não da banda calculada
Bug real encontrado e corrigido: a série `NDVI_GAPFILLED`, após regressão/`arrayFlatten`,
**perde a projeção nativa e vira WGS84 (1 grau)**. Se derivasse o CRS dela, a grade sairia
como **1×1 pixel**. Solução: derivar o CRS da **banda B8 do Sentinel-2** (fonte, que tem
EPSG:32722 a 10 m) e passar explicitamente ao exportador.

### 8.4 nodata
`ee_mask_value = -32768` (mínimo do int16, sentinela que não colide com dado real) com
`mask_and_scale=False` (para preservar inteiros, sem virar float/NaN).

### 8.5 Medição dos tempos
Separo três fases (o enunciado pede "export do GEE + persistência"):
- `t_open`: montar o dataset lazy (metadados).
- **`t_export`**: `dataset.load()` → força o **download do GEE** para a memória.
- **`t_persist`**: `to_zarr()` → **persistência local**.
- `t_total = open + export + persist`.

---

## 9. Resultados — matriz completa (2 imóveis × 2 dados × 2 dtypes)

Execução de 2026-07-05 (`tmp/xee_export/benchmark_report.json`):

| Imóvel | Área | Dado | dtype | Dimensões (time×y×x) | t_open | t_export | t_persist | **t_total** | Disco |
|---|---|---|---|---|---|---|---|---|---|
| car_1 | 3,2 ha | Embedding (64 var) | **int16** | 1 × 29 × 49 | 1,5 s | 67,1 s | 0,3 s | **68,8 s** | 0,23 MB |
| car_1 | 3,2 ha | Embedding (64 var) | float32 | 1 × 29 × 49 | 1,1 s | 72,0 s | 0,2 s | **73,3 s** | 0,25 MB |
| car_1 | 3,2 ha | NDVI gapfilled (100 datas) | **int16** | 100 × 29 × 49 | 2,0 s | 5,2 s | 0,02 s | **7,3 s** | 0,27 MB |
| car_1 | 3,2 ha | NDVI gapfilled (100 datas) | float32 | 100 × 29 × 49 | 1,9 s | 5,8 s | 0,03 s | **7,7 s** | 0,51 MB |
| car_2 | 54,9 ha | Embedding (64 var) | **int16** | 1 × 117 × 144 | 1,1 s | 59,7 s | 0,2 s | **61,0 s** | 0,92 MB |
| car_2 | 54,9 ha | Embedding (64 var) | float32 | 1 × 117 × 144 | 1,0 s | 93,5 s | 0,2 s | **94,7 s** | 1,11 MB |
| car_2 | 54,9 ha | NDVI gapfilled (100 datas) | **int16** | 100 × 117 × 144 | 1,4 s | 8,4 s | 0,02 s | **9,8 s** | 2,91 MB |
| car_2 | 54,9 ha | NDVI gapfilled (100 datas) | float32 | 100 × 117 × 144 | 2,3 s | 12,5 s | 0,03 s | **14,8 s** | 5,79 MB |

**Leitura dos números:**

1. **O tempo do embedding (~60-70 s) é quase independente da área** (car_2 é 17× maior e
   leva tempo similar). O gargalo não é volume de pixels, é o **overhead de requisição por
   variável**: 64 variáveis ≈ 64 chamadas ao GEE.
2. **A série NDVI é ~7–15 s** mesmo com 100 datas, porque é **1 variável** (1 request).
   → Xee é ótimo para séries temporais e caro para imagens multibanda largas.
3. **Int16 vale a pena no embedding** (61 s vs 95 s no car_2 = 1,5× mais rápido) **e
   especialmente no disco do NDVI** (2,9 MB vs 5,8 MB = 2× menor). Use sempre Int16.

> O campo `n_features` no JSON = nº de **variáveis** do xarray (embedding=64; NDVI=1).
> O nº de datas do NDVI fica em `shape.time` (=100).

---

## 10. Por que o layout de exportação explica tudo

Experimento controlado (`layout_experiment.py`, roda no car_1, Int16):

| Dado exportado | nº variáveis | nº datas | tempo |
|---|---|---|---|
| embedding como **64 variáveis** | 64 | 1 | ~69 s |
| **mesmo** embedding empilhado (1 variável) | 1 | 64 | **~3 s** |
| NDVI como **série** (1 variável) | 1 | 100 | ~7 s |
| **mesmo** NDVI como 100 variáveis | 100 | 1 | **~335 s** |

Conclusão provada: **o custo do Xee é por variável, não por pixel nem por data.**
Isso tem uma consequência importante para o backend: se empilhar as 64 bandas do embedding
em 1 variável (eixo "banda" sintético), o download cai de ~70 s para ~3 s. Os dados são
identicos (diferença pixel a pixel = zero, verificado).

---

## 11. Análise 2 — Classificação de pastagem (comparação de metodologias)

> Fecha o ciclo do objetivo final: **CAR → treina Random Forest → prevê o mapa de
> pastagem do ano seguinte + área**. Implementado seguindo a lógica do script do Bernardo
> (`lapig-acelen`). Código em `classification.py` + `run_classification.py`.

**O que faz (pasto/não-pasto, treina 2024 → prevê 2025):**
1. **Amostras automáticas**: rótulo = classe **Pastagem do MapBiomas** (`classification_2024 == 15`),
   binário pasto/não-pasto, amostrado (`stratifiedSample`, 300/classe) num **buffer de 2,5 km**
   ao redor do imóvel; features = 64 bandas do **Satellite Embedding** de 2024.
2. **Treina Random Forest** (100 árvores) e **classifica o embedding de 2025**; calcula a
   **área de pastagem** dentro do imóvel e gera a **imagem do mapa**.

**Duas metodologias:**
- **GEE-nativo** (`classify_gee_native`): `ee.Classifier.smileRandomForest` treina e classifica
  **server-side**; área via `reduceRegion`; mapa via `getThumbURL`. Nenhum pixel sai da nuvem.
- **Xee-local** (`classify_xee_local`): amostra no GEE (via `getInfo`), treina **sklearn
  RandomForest** local, **exporta o embedding 2025 via Xee** e prevê **pixel a pixel** na máquina.

**Resultados:**

| Imóvel | Metodologia | Área pasto (ha) | **Tempo total** |
|---|---|---|---|
| car_1 | GEE-nativo | 0,35 | **~2 s** |
| car_1 | Xee-local | 0,33 | **~79 s** |
| car_2 | GEE-nativo | 12,08 | **~4 s** |
| car_2 | Xee-local | 12,6 | **~70 s** |

**Conclusões:**
1. **As áreas concordam** (0,35≈0,33; 12,08≈12,6) → pipeline válido: treina em um ano, prevê outro.
2. **GEE-nativo ~20–30× mais rápido** com o layout atual. Esse fator cai para ~2–5× se o
   embedding for empilhado (veja seção 10); o gargalo do Xee-local é inteiramente o export.
3. **Imagens geradas** (`tmp/xee_export/images/`): mapa classificado sobre satélite (pasto
   em verde, contorno vermelho) + mapa local esquemático + biomassa MapBiomas.
   Biomassa: car_1 = 46,85 t MS; car_2 = 401,32 t MS (produto MapBiomas 2024, LUE=0,5).

---

## 12. Requisitos × entregue (checklist)

| Requisito do enunciado | Status | Onde |
|---|---|---|
| 64 features do Satellite Embedding V1, 2025, por imóvel | ✅ | `export_satellite_embedding` em `export.py` |
| ~101 datas do S2 NDVI gapfilled, 2025, por imóvel | ✅ (time=100) | `export_ndvi_gapfilled` + `_build_ndvi_gapfilled` |
| Via **Xee** | ✅ | `xr.open_dataset(..., engine="ee")` |
| Converter para **Int16** | ✅ | cast no GEE + `astype("int16")` |
| Persistir xarray em **zarr** | ✅ | `_persist_zarr` (`.to_zarr`) |
| Reportar **tempo export + persistência por imóvel** | ✅ | tabela + `benchmark_report.json` |
| Dois imóveis (car_1 & car_2) | ✅ | `load_test_properties` (mock) |
| Comparação Int16 × Float32 | ✅ | matriz completa na seção 9 |
| Comparação GEE-nativo × Xee-local | ✅ | `classification.py` seção 11 |

---

## 13. Aderência ao padrão de código do projeto

Segue o estilo do `app/utils/scripts/gee_scripts.py`: docstrings **PT-BR** com `Args:`/`Returns:`,
`typing` capitalizado (`List`/`Dict`/`Tuple`), aspas duplas, constantes de módulo `_UPPER`,
funções privadas com `_`, `try/except` por tipo + `log_error(traceback.format_exc())` +
`raise RuntimeError("<mensagem PT>")`, init do GEE no import (como o `gee_scripts.py`),
2 linhas em branco entre defs.

Única fuga consciente do padrão: a autenticação lê o `.env` **direto via `dotenv`** em vez
de `from app.configs.config import config`, porque o `config` quebra no import se `APP_ENV`
não estiver **exportado no ambiente** (ele é feito para rodar dentro do container). Como este
harness é standalone, ler o `.env` é mais robusto.

---

## 14. Git / entrega

- Branch **`feature/112-suporte-mapeamento-on-the-fly`** (de `origin/develop`, **sem upstream**).
- **Nada foi enviado ao git** (conforme combinado — só testes locais). `tests/xee_export/`
  está *untracked*; `tmp/` é gitignored.
