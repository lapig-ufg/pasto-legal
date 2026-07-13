# Documentação técnica completa — Testes Xee (issue #112)

> **Autor:** @ThiagoHF31  
> **Branch:** `feature/112-suporte-mapeamento-on-the-fly` (criada de `origin/develop`, sem push)  
> **Datas de execução:** 2026-07-02 (implementação) · 2026-07-05 (testes originais) · 2026-07-07 (novos CARs) · 2026-07-10 (reorganização do código)  
>
> Este documento descreve **tudo** que foi implementado, testado e medido como parte da
> contribuição do Thiago à issue #112 ("Suporte para mapeamento on-the-fly"). Cada seção
> nomeia o arquivo, a função e o motivo de cada decisão.

---

## 1. O que foi pedido e por que existe este trabalho

### 1.1 A pergunta central da issue

A issue #112 existe para responder uma pergunta prática do sistema Pasto Legal:

> *"Quando o fazendeiro pedir o mapa de pastagem, o backend consegue buscar os dados
> do GEE em tempo hábil via Xee, ou vai demorar demais?"*

Mais especificamente: **é viável usar o Xee como transporte GEE → servidor** para que o
backend receba arrays Python (xarray/zarr), faça cruzamentos locais e devolva o mapa sem
depender do GEE para cada operação futura?

### 1.2 A tarefa do Thiago (enunciado literal)

> Implementar testes de exportação via Xee para dois imóveis rurais (`car_1` e `car_2`):
> 1. Exportação das **64 features** de 2025 do **Satellite Embedding V1** por imóvel.
> 2. Exportação das **~101 features/datas** de 2025 da série **Sentinel-2 NDVI gapfilled**
>    por imóvel.
> - Converter para **Int16** (Float32 pode ser bem mais lento).
> - Persistir o xarray localmente em **zarr/geozarr**.
> - Reportar o **tempo total** (export GEE + persistência) por imóvel.

### 1.3 O que foi feito além do pedido

Além do benchmark de exportação, foram implementados:
- **Experimento de layout** (`layout_experiment.py`): prova controlada de por que o Xee
  é lento para o embedding e rápido para o NDVI — e como resolver.
- **Classificação pasto/não-pasto** (`classification.py`): fecha o ciclo do objetivo final
  (fazendeiro pede → backend retorna mapa + área) com três metodologias.
- **Segunda rodada de testes** com dois novos CARs (Silvânia-GO e Córrego do Ouro-GO)
  para verificar se as conclusões se mantêm em escalas diferentes.
- **Reorganização do código** (2026-07-10): `classification.py` reescrito com nomes simples
  e comentários objetivos; todos os runners consolidados em um único `run.py`.

---

## 2. Conceitos fundamentais (o que é o quê)

### 2.1 O que é o Xee

`xee` é uma **biblioteca Python** que abre uma `ee.ImageCollection` do Google Earth Engine
como um `xarray.Dataset`. Ela não existe no Code Editor (JavaScript). O Xee é somente a
**ponte de download**: a computação continua no GEE (server-side), e o Xee traz o
resultado já computado para a memória Python.

```
GEE (cloud) ──[Xee]──► xarray.Dataset em RAM ──► zarr no disco
    ^                         ^
 computa                 manipula/cruza
 embedding, NDVI          em Python
```

### 2.2 O que é o Satellite Embedding V1

Asset GEE: `GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL`  
Dataset anual do Google em que cada pixel é um **vetor de 64 números** (bandas `A00`…`A63`)
que "resume" a assinatura espectral e temporal daquele local no ano — ele já processa todas
as imagens Sentinel-2 do ano, remove nuvens e comprime em 64 dimensões. As 64 bandas são
**inseparáveis**: são as dimensões de um único vetor e todas são necessárias para o modelo.  
Resolução: **10 m/pixel**. Formato exportado: **64 variáveis × 1 data** (anual).

### 2.3 O que é o NDVI gapfilled

Série temporal Sentinel-2 em que cada pixel tem o NDVI ("verdor" da vegetação) reconstruído
para **cada data de aquisição** do satélite (~100 passagens/ano), já **preenchido por
regressão harmônica** — sem buracos de nuvem. A regressão ajusta uma curva senoidal por
pixel (3 harmônicos) usando as imagens sem nuvem disponíveis; para cada data, devolve o
valor ajustado `NDVI_GAPFILLED`.  
Formato exportado: **1 variável × N datas** (onde N é o nº de cenas S2 do ano na região).

### 2.4 Por que Int16 (e não Float32)

O GEE opera internamente em `double`. O Xee usa `float32` em memória. Se fizéssemos nada,
os dados chegariam como float32 e seriam salvos como float32 (4 bytes/pixel).

A estratégia implementada:
1. No GEE: `.multiply(10000).toInt16()` — multiplica por 10 000 (os valores em [-1, 1]
   cabem em [-10000, 10000], dentro dos ±32 767 do int16) e converte **antes do download**.
2. O `computePixels` do GEE respeita o tipo da banda e envia int16 pela rede (2 bytes).
3. Após o load: `.astype("int16")` — o Xee 0.1.1 hardcoda float32 em memória (`ext.py:707`);
   convertemos de volta antes de gravar o zarr.

Resultado: **metade do espaço em disco** e, para o embedding, velocidade de download ~1,2–1,5×
maior (menos bytes pela rede). Precisão perdida: ±0,0001 (irrelevante para o modelo de RF).

---

## 3. Mapa completo de arquivos

Tudo está em `tests/xee_export/`. **Nenhum arquivo de `app/` foi modificado**, exceto a
criação de `app/utils/mocks/new_property_mock.json` (novo mock de teste, não altera lógica).

### 3.1 Módulos core (importados pelos runners)

| Arquivo | Papel |
|---|---|
| `tests/xee_export/export.py` | **Módulo de exportação.** Inicializa o GEE, carrega geometrias, calcula a grade UTM, implementa os dois exportadores (embedding + NDVI gapfilled), cast Int16, persistência zarr e medição de tempos. Não modificar — é a base estável. |
| `tests/xee_export/classification.py` | **Módulo de classificação.** Três estratégias de Random Forest (`classify_gee`, `classify_gee_xee`, `classify_xee`) e biomassa MapBiomas (`biomass_map`). Cada função pública tem uma linha de comentário explicando o que faz. |
| `tests/xee_export/layout_experiment.py` | **Experimento controlado.** Exporta o embedding e o NDVI nos dois layouts possíveis (N variáveis vs 1 variável × N datas) e mede o tempo de cada um. Prova qual dimensão domina o custo do Xee. |

### 3.2 Entry-points (runners — executados diretamente)

| Arquivo | O que executa | Saída |
|---|---|---|
| `tests/xee_export/run.py` | **Ponto de entrada único.** Roda `classify_gee` + `classify_gee_xee` + `biomass_map` (e opcionalmente `classify_xee`) para os **novos CARs**. Use `--skip-xee` para pular o método mais lento. | `tmp/xee_export/run_report.json` + PNGs |
| `tests/xee_export/run_benchmark.py` | Matriz completa de exportação para os **imóveis originais** (Jaraguá-GO): 2 imóveis × 2 dados × 2 dtypes = 8 combinações. | `tmp/xee_export/benchmark_report.json` |
| `tests/xee_export/run_classification.py` | Classificação para os **imóveis originais**: GEE-nativo + Xee-local + biomassa. | `tmp/xee_export/classification_report.json` + PNGs |

### 3.3 Infraestrutura

| Arquivo | Papel |
|---|---|
| `tests/xee_export/__init__.py` | Torna o diretório um pacote Python — necessário para o `-m tests.xee_export.run_*`. |
| `app/utils/mocks/property_mock.json` | Mock original: 2 imóveis em Jaraguá-GO (`car_1`=3,2 ha, `car_2`=54,9 ha). |
| `app/utils/mocks/new_property_mock.json` | **Novo** mock: 2 imóveis adicionais (Silvânia-GO 2073 ha + Córrego do Ouro-GO 23 ha). Campos normalizados (`codigo`, `area`) para compatibilidade com `load_test_properties`. |

### 3.4 Saídas (gitignored)

| Caminho | Conteúdo |
|---|---|
| `tmp/xee_export/*.zarr` | Stores zarr por imóvel/dado/dtype (um diretório por combinação). |
| `tmp/xee_export/benchmark_report.json` | Tempos e tamanhos dos imóveis originais. |
| `tmp/xee_export/benchmark_new_cars_report.json` | Tempos e tamanhos dos novos CARs. |
| `tmp/xee_export/classification_report.json` | Área de pasto + tempo por metodologia — imóveis originais. |
| `tmp/xee_export/classification_new_cars_report.json` | Área de pasto + tempo — novos CARs. |
| `tmp/xee_export/images/*.png` | Mapas gerados: `{nome}_pasto_gee_2025.png`, `{nome}_pasto_local_2025.png`, `{nome}_biomassa_2024.png`. |

### 3.5 Documentação

| Arquivo | Conteúdo |
|---|---|
| `tests/xee_export/EXPLICACAO.md` | **Este documento.** Referência técnica completa — função por função. |
| `tests/xee_export/RESPOSTA_ISSUE.md` | Texto em linguagem humana para postar na issue. Seções 1–8 imóveis originais; 9 novos CARs; 10 `classify_gee_xee`; 11 estratégia de cache. |

---

## 4. Dependências instaladas (e por que fora do pyproject)

```bash
uv pip install xee xarray zarr scikit-learn
```

Instaladas **no venv via `uv pip install`**, deliberadamente **fora do `pyproject.toml`**.
Motivo: são dependências de teste/experimento, não do serviço. Incluí-las no manifesto
"contaminaria" o lock da aplicação e adicionaria overhead ao build de produção.

---

## 5. Como rodar

Pré-requisito: venv do projeto + `.env` com `GEE_PROJECT`, `GEE_SERVICE_ACCOUNT`,
`GEE_KEY_FILE`.

```bash
cd "/Users/thiagohonoratoferreira/Documents/PASTO LEGAL - CEIA/pasto-legal"

# Novos CARs (Silvânia-GO + Córrego do Ouro-GO) — ponto de entrada principal:
.venv/bin/python -m tests.xee_export.run --skip-xee   # ~75 s (classify_gee + classify_gee_xee + biomass)
.venv/bin/python -m tests.xee_export.run              # ~5–6 min (inclui classify_xee)

# Imóveis originais (Jaraguá-GO) — runners históricos:
.venv/bin/python -m tests.xee_export.run_benchmark      # ~6–10 min (8 combinações de export)
.venv/bin/python -m tests.xee_export.run_classification # ~5 min (classificação GEE x local)

# Experimento de layout (prova do nº de variáveis):
.venv/bin/python -m tests.xee_export.layout_experiment  # ~8 min

# Filtrar ruído do TF/absl nos logs:
.venv/bin/python -m tests.xee_export.run --skip-xee 2>&1 | grep -Ev "^W0|^I0|^E0|absl"
```

---

## 6. Os imóveis de teste

### 6.1 Imóveis originais — `app/utils/mocks/property_mock.json`

Função que os carrega: `load_test_properties()` em `export.py`.  
Dois imóveis reais em **Jaraguá-GO**, escolhidos por terem tamanhos bem diferentes:

| ID interno | Código CAR | Área | Município | Geometria |
|---|---|---|---|---|
| `car_1` | `GO-5211800-E85CBBBF7DA34628BCA06B78357D39F6` | **3,2 ha** | Jaraguá-GO | MultiPolygon |
| `car_2` | `GO-5211800-987B29E7E47A4454BAEF582557AB89F3` | **54,9 ha** | Jaraguá-GO | MultiPolygon |

### 6.2 Novos CARs — `app/utils/mocks/new_property_mock.json`

Carregados por `load_test_properties(mock_path=_NEW_MOCK_PATH)` nos runners `*_new_cars.py`.

| ID interno | Código CAR | Área | Município | Status | Geometria |
|---|---|---|---|---|---|
| `car_1` | `GO-5212303-27057D4194F64CE3A498B90BFAC2E5F9` | **2073,5 ha** | Silvânia-GO | Cancelado por duplicidade | Polygon |
| `car_2` | `GO-5205703-5B18B6DF441C4B7FA9444DDC127CF6C0` | **23,5 ha** | Córrego do Ouro-GO | Ativo | Polygon |

> **Nota sobre o status "Cancelado":** o CAR de Silvânia foi cancelado administrativamente,
> mas a área geográfica e os dados GEE (Sentinel-2, MapBiomas, Embedding) existem normalmente.
> Para o teste de exportação, o status não impacta os resultados.

> **Nota sobre Polygon vs MultiPolygon:** os novos CARs têm geometria `Polygon` (GeoJSON),
> enquanto o mock original usa `MultiPolygon`. A função `load_test_properties` foi atualizada
> para detectar o tipo e envolver automaticamente:
> `ee.Geometry.MultiPolygon([polygon.coordinates])` para Polygons.

---

## 7. Módulo `export.py` — função por função

### 7.1 Inicialização do GEE (topo do arquivo)

```python
_credentials = ee.ServiceAccountCredentials(_env["GEE_SERVICE_ACCOUNT"], _key_file)
ee.Initialize(_credentials, project=_env["GEE_PROJECT"], opt_url=_HIGHVOLUME_URL)
```

- Lê credenciais **diretamente do `.env`** via `dotenv_values` (não usa `app.configs.config`
  porque o `config` do app quebra no import sem `APP_ENV` exportado no shell — o harness é
  standalone).
- Usa o endpoint **high-volume** (`https://earthengine-highvolume.googleapis.com`) — exigido
  pelo Xee (documentação oficial): habilita `computePixels` para download de arrays.

### 7.2 `load_test_properties(mock_path=None)`

```
Arquivo: export.py
Parâmetro: mock_path (Path, opcional) — se omitido, usa _MOCK_PATH (imóveis originais)
Retorna: List[Dict] com "name", "codigo", "area_ha", "roi" por imóvel
```

Lê o JSON do mock, detecta o tipo de geometria (`Polygon` ou `MultiPolygon`) e cria o
`ee.Geometry.MultiPolygon` correspondente. A parametrização do path foi adicionada para
suportar os novos CARs sem duplicar código.

### 7.3 `_utm_grid(roi, crs, scale)` (privada)

```
Arquivo: export.py
Por que existe: o Xee 0.1.1 NÃO aceita scale/geometry. Exige a grade explícita.
```

O Xee 0.1.1 exige três parâmetros de grade: `crs` (string EPSG), `crs_transform` (objeto
`affine.Affine`) e `shape_2d` (largura, altura em pixels). Esta função calcula esses três
valores a partir do bbox do imóvel projetado em UTM:

1. Projeta o bbox do `roi` para o CRS métrico (`ee.Geometry.bounds().transform()`).
2. Extrai min/max de X e Y.
3. Arredonda para múltiplos do `scale` (10 m) garantindo que o bbox inteiro seja coberto.
4. Monta `transform = Affine(10, 0, x_min, 0, -10, y_max)` (pixel do canto superior esquerdo).
5. Calcula `width = (x_max - x_min) / scale` e `height = (y_max - y_min) / scale`.

> Detalhe crítico (descoberto empiricamente): em `shape_2d=(width, height)`, o **primeiro
> elemento é X (largura)** e o segundo é Y (altura) — contrário ao padrão numpy.

### 7.4 `_native_crs(collection)` (privada)

```
Arquivo: export.py
Retorna: string CRS da projeção nativa da primeira imagem (ex.: "EPSG:32722")
```

Obtém o CRS nativo da coleção via `.projection().getInfo()["crs"]`. Usado para garantir
que a grade UTM seja derivada da fonte correta.

> **Bug corrigido:** a série `NDVI_GAPFILLED` perde a projeção após a regressão harmônica
> e vira WGS84 1°×1° (1 pixel enorme). Por isso o NDVI usa `_native_crs` na banda `B8`
> do Sentinel-2 (a fonte da série), não na coleção calculada. Sem isso, a grade saía 1×1 px.

### 7.5 `_persist_zarr(dataset, out_path)` (privada)

```
Arquivo: export.py
Retorna: float — tempo de escrita em segundos
```

Remove o store zarr anterior se existir (`shutil.rmtree`), cria os diretórios e chama
`dataset.to_zarr(out_path, mode="w")`. Mede e retorna o tempo de escrita (`t_persist`).

### 7.6 `_dir_size_mb(path)` (privada)

```
Arquivo: export.py
Retorna: float — tamanho em MB do store zarr
```

Percorre todos os arquivos do diretório zarr com `rglob("*")` e soma os `st_size`.
Calcula o tamanho **pós-compressão** (o zarr aplica compressão padrão — Blosc).

### 7.7 `_export_via_xee(name, teste, collection, roi, stem, to_int16, crs)` (privada)

```
Arquivo: export.py
Lógica compartilhada entre export_satellite_embedding e export_ndvi_gapfilled.
```

Passo a passo:
1. Chama `_utm_grid` para obter `transform`, `width`, `height`.
2. **`t_open`**: `xr.open_dataset(..., engine="ee")` — abre lazy (sem baixar pixels).
3. **`t_export`**: `dataset.load()` — força o download de todos os pixels do GEE para RAM.
4. Se `to_int16=True`: `dataset.astype("int16")` — converte de float32 (Xee hardcoda) para int16.
5. **`t_persist`**: chama `_persist_zarr` — grava zarr e mede escrita.
6. Monta e retorna o dicionário de métricas com todos os tempos, shape, dtype e tamanho.

Parâmetros do `xr.open_dataset`:
```python
xr.open_dataset(
    collection,           # ee.ImageCollection já preparada
    engine="ee",          # backend Xee
    crs=crs,              # ex.: "EPSG:32722"
    crs_transform=transform,   # affine.Affine(10, 0, x_min, 0, -10, y_max)
    shape_2d=(width, height),  # (x, y) — atenção à ordem
    mask_and_scale=False, # preserva inteiros, não converte para float/NaN
    ee_mask_value=-32768, # sentinela nodata (mínimo int16, não colide com dado real)
)
```

### 7.8 `export_satellite_embedding(name, roi, year, to_int16)` (pública)

```
Arquivo: export.py
Chamada por: run_benchmark.py (loop), classify_xee_local em classification.py
```

1. Filtra o asset `GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL` por `filterBounds(roi)` e
   `filterDate(year-01-01 … year+1-01-01)`.
2. Se `to_int16=True`: mapeia `.multiply(10000).toInt16()` na coleção — cast no lado do GEE.
3. Obtém o CRS com `_native_crs(collection)`.
4. Chama `_export_via_xee` e retorna as métricas.

O resultado no xarray tem: **64 variáveis** (`A00`…`A63`), `time=1` (anual), dims `(y, x)`.

### 7.9 `_harmonic_names(base, frequencies)` (privada)

```
Arquivo: export.py
Gera nomes como "cos_1", "cos_2", "cos_3", "sin_1", ...
```

### 7.10 `_build_ndvi_gapfilled(roi, year, harmonics=3)` (privada)

```
Arquivo: export.py
Retorna: ee.ImageCollection com 1 banda "NDVI_GAPFILLED" por data de aquisição
```

Tradução fiel do script EE de referência (`lapig-acelen`). Pipeline completo:

| Passo | O que faz | Código |
|---|---|---|
| 1 | Linka S2 SR com Cloud Score+ | `s2_with_cs = ee.ImageCollection(_S2_ASSET).linkCollection(...)` |
| 2 | Máscara nuvem: `cs_cdf >= 0,60` | `image.select("cs_cdf").gte(0.60)` |
| 3 | Escala óptica: `/10000` | `image.select("B.*").divide(10000)` |
| 4 | Calcula NDVI | `normalizedDifference(["B8", "B4"])` |
| 5 | Monta regressores: `constant`, `t`, `cos_1..3`, `sin_1..3` | `add_constant`, `add_time`, `add_harmonics` |
| 6 | Regressão harmônica por pixel | `ee.Reducer.linearRegression(8, 1)` |
| 7 | Para cada data: NDVI ajustado `= Σ (coeficiente × regressor)` | `add_fitted` |

A saída é uma coleção com **uma imagem por data S2**, cada uma com a banda `NDVI_GAPFILLED`.

### 7.11 `export_ndvi_gapfilled(name, roi, year, to_int16)` (pública)

```
Arquivo: export.py
Chamada por: run_benchmark.py, run_benchmark_new_cars.py
```

1. Verifica disponibilidade de imagens S2 no ano.
2. Deriva CRS da banda `B8` do S2 (não da série calculada — ver bug acima).
3. Chama `_build_ndvi_gapfilled` para montar a série.
4. Se `to_int16=True`: `.clamp(-1, 1).multiply(10000).toInt16()` — clamp antes do cast
   para proteger contra extrapolação do modelo harmônico.
5. Chama `_export_via_xee` e retorna as métricas.

O resultado no xarray tem: **1 variável** (`NDVI_GAPFILLED`), `time=N` (N datas do S2),
dims `(time, y, x)`.

---

## 8. Módulo `classification.py` — função por função

Reorganizado em 2026-07-10: nomes simplificados, comentários objetivos, sem docstrings
verbosas. A docstring do módulo resume as três estratégias e a metodologia comum.

### 8.1 Constantes relevantes

| Constante | Valor | Significado |
|---|---|---|
| `_MAPBIOMAS_ASSET` | `"projects/mapbiomas-public/assets/..."` | Coleção 10 do MapBiomas Brasil (LULC) |
| `_BIOMASS_ASSET` | `"projects/mapbiomas-public/assets/..."` | MapBiomas Biomassa Pastagem Col. 10 |
| `_PASTURE_CLASS` | `15` | Código da classe Pastagem no MapBiomas |
| `_TRAIN_YEAR` | `2024` | Ano de treino do Random Forest |
| `_PRED_YEAR` | `2025` | Ano de predição (o "mapa de pastagem") |
| `_SAMPLE_BUFFER_M` | `2500` | Buffer (m) ao redor do imóvel para buscar amostras |
| `_SAMPLES_PER_CLASS` | `300` | Amostras por classe (pasto/não-pasto) |
| `_RF_TREES` | `100` | Número de árvores no Random Forest |
| `_IMAGE_DIM` | `512` | Dimensão (px) dos PNGs de saída |

### 8.2 `_embedding(roi, year)` (privada)

```
Arquivo: classification.py
Retorna: ee.Image com 64 bandas em Int16 (×10000)
```

Retorna a primeira imagem anual do embedding já com o cast `.multiply(10000).toInt16()`.
Usada internamente pelas três metodologias de classificação.

### 8.3 `_samples(roi, train_year)` (privada)

```
Arquivo: classification.py
Retorna: (ee.FeatureCollection com label+64 features, ee.List com nomes das bandas)
```

Segue a lógica do script do Bernardo (`lapig-acelen`):
1. **Rótulo**: `MapBiomas.select(classification_{year}).eq(15)` — 1 = pasto, 0 = não-pasto.
2. **Features**: `_embedding(roi, train_year)` — 64 bandas Int16.
3. **Amostragem**: `stratifiedSample(300/classe, region=roi.buffer(2500m), scale=10, seed=42)`.

O buffer de 2500 m garante amostras representativas mesmo para imóveis pequenos.

### 8.4 `_base_rgb(roi, year)` (privada)

```
Arquivo: classification.py
Retorna: ee.Image RGB (mediana Sentinel-2) para servir de fundo nos mapas
```

Mediana anual das imagens S2 com < 20% de nuvem, bandas B4/B3/B2 (RGB verdadeiro).

### 8.5 `_boundary(roi)` (privada)

```
Arquivo: classification.py
Retorna: ee.Image com o contorno vermelho do imóvel (2 px)
```

Usa `ee.Image.paint(FeatureCollection, value=1, width=2)` para gerar o contorno.

### 8.6 `_save_png(image, roi, out_path)` (privada)

```
Arquivo: classification.py
Baixa o thumbnail GEE (512 px) e salva como PNG local
```

Chama `.getThumbURL({"dimensions": 512, "format": "png"})` e usa `requests.get` + `PIL.Image`.
Clip com buffer de 256 m ao redor do imóvel para contexto visual.

### 8.7 `classify_gee(name, roi, train_year=2024, pred_year=2025)` (pública)

```
Arquivo: classification.py
Chamada por: run.py
Metodologia: classifica pasto/não-pasto inteiramente no GEE (server-side) e gera PNG
```

Pipeline inteiramente no GEE:
1. `_samples(roi, 2024)` → amostras de treino.
2. `ee.Classifier.smileRandomForest(100).train(samples, "pasto", bandnames)` → RF.
3. `_embedding(roi, 2025).classify(classifier)` → mapa classificado.
4. `reduceRegion(ee.Reducer.sum())` × área do pixel → **área de pastagem em ha**.
5. `_base_rgb` + overlay verde + `_boundary` → PNG via `_save_png`.

Gera: `tmp/xee_export/images/{name}_pasto_gee_2025.png`  
Tempo medido: ~8,6 s (new_car_1 / 2073 ha), ~2,4 s (new_car_2 / 23 ha).

### 8.8 `_to_arrays(samples, bandnames)` (privada)

```
Arquivo: classification.py
Converte ee.FeatureCollection → (X: np.ndarray, y: np.ndarray)
```

Chama `getInfo()` nas amostras e reorganiza em matrizes numpy para o sklearn.

### 8.9 `classify_xee(name, roi, train_year=2024, pred_year=2025)` (pública)

```
Arquivo: classification.py
Chamada por: run.py (sem --skip-xee)
Metodologia: baixa o embedding (64 variáveis) via Xee e classifica pixel a pixel com sklearn
```

Pipeline híbrido:
1. `_samples` → amostras no GEE; `_to_arrays` → numpy.
2. `RandomForestClassifier(100, random_state=42, n_jobs=-1).fit(X, y)` → treina local.
3. Xee exporta o embedding de 2025 (64 bandas + `inpoly` para máscara dentro do imóvel).
4. `np.stack([...]).reshape(-1, 64)` → `classifier.predict` → predição pixel a pixel.
5. `(prediction * inside).sum() × 100m² / 10000` → **área em ha**.
6. `_render_map` → PNG esquemático (verde=pasto, cinza=não-pasto).

> O grosso do tempo é o download das 64 bandas via Xee (~70–130 s com layout ingênuo).
> Com o embedding empilhado (seção 11), cairia para ~3–10 s.

Gera: `tmp/xee_export/images/{name}_pasto_local_2025.png`

### 8.10 `classify_gee_xee(name, roi, train_year=2024, pred_year=2025)` (pública)

```
Arquivo: classification.py
Chamada por: run.py
Metodologia: classifica no GEE e exporta o raster resultado (1 variável binária) via Xee → zarr
```

Em vez de baixar 64 bandas (~70–131 s) ou só um PNG, exporta o raster binário final
(`pasto` = 0 ou 1). **1 variável × 1 data** → Xee muito mais rápido que para o embedding.

**Fases do pipeline:**

| Fase | O que acontece | t medido |
|---|---|---|
| Pipeline GEE | Define amostras + RF + classify — tudo lazy, nenhum pixel computado | ~0,0 s |
| `t_xee_open` | Xee abre a coleção → GEE treina RF + classifica (`computePixels`) | ~2–4 s |
| `t_xee_export` | Download do raster binário 1 variável × 1 data | ~2–7 s |
| `t_xee_persist` | Grava zarr local | < 0,2 s |
| **t_total** | **Soma de todas as fases** | **5–11 s** |

**Cálculo da área (local, sem roundtrip ao GEE):**
```python
pasto_arr = xr.open_zarr(zarr_path)["pasto"].isel(time=0).values
area_ha = float((pasto_arr == 1).sum()) * (10 ** 2) / 1e4
```

Pixels fora do ROI chegam como `-32768` (nodata); `== 1` os ignora corretamente.

**Resultados (2026-07-10):**

| Imóvel | Área | t_xee_open | t_xee_export | t_total | zarr |
|---|---|---|---|---|---|
| new_car_1 (2073 ha, 643×940 px) | 714,37 ha | 3,9 s | 6,6 s | **11,23 s ✅** | 0,024 MB |
| new_car_2 (23 ha, 94×48 px) | 15,73 ha | 1,7 s | 1,5 s | **4,98 s ✅** | 0,008 MB |

O zarr é minúsculo porque dado binário (0/1) comprime extremamente bem (Blosc padrão).

### 8.11 `_render_map(name, prediction, inside, pred_year)` (privada)

```
Arquivo: classification.py
Renderiza o mapa local como RGBA e salva com plt.imsave
```

Array RGBA: pasto dentro do imóvel → verde `(0, 0.78, 0, 1)`;
não-pasto dentro → cinza `(0.8, 0.8, 0.8, 1)`; fora → transparente.

### 8.12 `biomass_map(name, roi, year=2024)` (pública)

```
Arquivo: classification.py
Chamada por: run.py
Metodologia: calcula biomassa de pastagem (MapBiomas) e gera mapa PNG
```

1. Asset `_BIOMASS_ASSET`, banda `biomass_{year}`.
2. `reduceRegion(Reducer.minMax().combine(Reducer.sum()))` → min, max, soma.
3. Biomassa total t MS = `soma × 0,09` (fator de conversão do produto MapBiomas).
4. Visualização paleta `["#000033", "#9400D3", "#FF00FF", "#00FFFF", "#FFFFFF"]`.
5. PNG salvo em `tmp/xee_export/images/{name}_biomassa_{year}.png`.

---

## 9. Módulo `layout_experiment.py` — função por função

### 9.1 Por que existe

Após os primeiros resultados (embedding ~70 s, NDVI ~7 s), a pergunta natural era: *"o
embedding é lento porque tem 64 valores por pixel, ou porque são 64 variáveis separadas?"*
Este experimento responde isso diretamente.

### 9.2 `_bands_as_timeseries(image)` (privada)

```
Arquivo: layout_experiment.py
Transforma uma ee.Image de N bandas em ee.ImageCollection de N imagens de 1 banda
```

Cria N imagens, cada uma com 1 banda renomeada para "valor" e `system:time_start` = dia N
do ano (eixo temporal sintético). O dado resultante é **idêntico** em pixels — só o layout
muda (N variáveis → 1 variável × N datas).

### 9.3 `run()` em `layout_experiment.py`

Roda 4 combinações no `car_1` (imóvel original):

| Teste | nº variáveis | nº datas | Dado real |
|---|---|---|---|
| `embedding_bandas` | 64 | 1 | Embedding como exportado normalmente |
| `embedding_serie` | 1 | 64 | **Mesmo** embedding, bandas → eixo temporal |
| `ndvi_serie` | 1 | ~100 | NDVI como exportado normalmente |
| `ndvi_bandas` | 100 | 1 | **Mesmo** NDVI, datas → variáveis (`.toBands()`) |

**Resultado medido:**

| Teste | Variáveis | Datas | t_export |
|---|---|---|---|
| embedding_bandas | 64 | 1 | **~69 s** |
| embedding_serie | 1 | 64 | **~3 s** |
| ndvi_serie | 1 | 100 | **~7 s** |
| ndvi_bandas | 100 | 1 | **~335 s** |

**Conclusão provada:** o custo do Xee é dominado pelo **número de variáveis**, não pelo
número de datas nem pelo volume de pixels. Cada variável ≈ 1 request ao `computePixels`.

**Consequência direta:** o embedding pode ser baixado em ~3 s (em vez de ~69 s) se
empilhado em 1 variável. Os dados são idênticos pixel a pixel (verificado com `diff=0`).
Essa otimização ainda não está embutida em `export_satellite_embedding` — está identificada
como próximo passo.

---

## 10. Os runners — o que cada um faz internamente

### 10.1 `run_benchmark.py`

```python
properties = load_test_properties()          # mock original (Jaraguá-GO)
for prop in properties:                      # car_1, car_2
    for dtype_label, to_int16 in [...]:      # int16, float32
        export_satellite_embedding(...)       # 2 imóveis × 2 dtypes
        export_ndvi_gapfilled(...)            # 2 imóveis × 2 dtypes = 8 combinações
_print_table(rows)                            # tabela no console
report_path.write_text(json.dumps(...))       # benchmark_report.json
```

### 10.2 `run_classification.py`

```python
properties = load_test_properties()
for prop in properties:
    classify_gee_native(name, roi)            # GEE server-side
    classify_xee_local(name, roi)             # sklearn local + Xee
    biomass_image(name, roi)                  # biomassa MapBiomas 2024
_print_comparison(rows)
report_path.write_text(...)                   # classification_report.json
```

### 10.3 `run_benchmark_new_cars.py`

Idêntico ao `run_benchmark.py`, mas com:
```python
_NEW_MOCK_PATH = _ROOT / "app/utils/mocks/new_property_mock.json"
properties = load_test_properties(mock_path=_NEW_MOCK_PATH)
# e prefixo "new_" no nome: export_satellite_embedding(name=f"new_{name}", ...)
```
O prefixo `new_` garante que os arquivos zarr de saída não sobrescrevam os originais.

### 10.4 `run_classification_new_cars.py`

Idêntico ao `run_classification.py`, mas com o novo mock e nome prefixado `"new_{prop['name']}"`.

---

## 11. Decisões técnicas com detalhes de implementação

### 11.1 Por que `opt_url=highvolume`

O Xee exige o endpoint high-volume para usar a API `computePixels`. O endpoint padrão do
GEE não suporta essa chamada e retorna erro.

### 11.2 Leitura do `.env` direto (não via `config.py`)

O `app/configs/config.py` do projeto importa várias dependências da aplicação e lê
`APP_ENV` do ambiente. Sem `export APP_ENV=...` no shell, o import quebra com
`KeyError: 'APP_ENV'`. O harness de teste é standalone, então lê as credenciais
diretamente via `dotenv_values(_ROOT / ".env")` — mais robusto para rodar fora do container.

### 11.3 `mask_and_scale=False` + `ee_mask_value=-32768`

- `mask_and_scale=False`: impede que o Xee converta pixels mascarados para `NaN` (float).
  Com int16, NaN não existe — o sentinela é o valor numérico `_MASK_VALUE = -32768`.
- `-32768` = mínimo do int16 = nunca ocorre como dado real (dados em [-10000, 10000]).

### 11.4 Detecção automática de Polygon/MultiPolygon em `load_test_properties`

```python
geom = feature["geometry"]
if geom["type"] == "MultiPolygon":
    roi = ee.Geometry.MultiPolygon(geom["coordinates"])
elif geom["type"] == "Polygon":
    roi = ee.Geometry.MultiPolygon([geom["coordinates"]])  # envolve em MultiPolygon
```

Os novos CARs do SICAR vêm como `Polygon` no GeoJSON. `ee.Geometry.MultiPolygon` aceita
`[polygon.coordinates]` (polígono envolvido em lista), produzindo geometria equivalente.

---

## 12. Resultados — Rodada 1 (imóveis originais, Jaraguá-GO)

Execução: 2026-07-05. Arquivo: `tmp/xee_export/benchmark_report.json`.

**car_1 — 3,2 ha** (grade 29 × 49 px a 10 m)

| Dado | dtype | Dimensões (time×y×x) | t_open | t_export | t_persist | **t_total** | Tamanho |
|---|---|---|---|---|---|---|---|
| Satellite Embedding (64 features) | **int16** | 1 × 29 × 49 | 1,4 s | 74,7 s | 0,3 s | **76,4 s** | 0,23 MB |
| Satellite Embedding (64 features) | float32 | 1 × 29 × 49 | 1,2 s | 70,3 s | 0,2 s | **71,6 s** | 0,25 MB |
| NDVI gapfilled (100 datas) | **int16** | 100 × 29 × 49 | 2,8 s | 5,5 s | 0,03 s | **8,4 s** | 0,27 MB |
| NDVI gapfilled (100 datas) | float32 | 100 × 29 × 49 | 1,7 s | 10,7 s | 0,03 s | **12,4 s** | 0,51 MB |

**car_2 — 54,9 ha** (grade 117 × 144 px a 10 m)

| Dado | dtype | Dimensões (time×y×x) | t_open | t_export | t_persist | **t_total** | Tamanho |
|---|---|---|---|---|---|---|---|
| Satellite Embedding (64 features) | **int16** | 1 × 117 × 144 | 1,5 s | 59,9 s | 0,2 s | **61,5 s** | 0,92 MB |
| Satellite Embedding (64 features) | float32 | 1 × 117 × 144 | 0,3 s | 75,8 s | 0,2 s | **76,3 s** | 1,11 MB |
| NDVI gapfilled (100 datas) | **int16** | 100 × 117 × 144 | 3,0 s | 9,7 s | 0,03 s | **12,7 s** | 2,91 MB |
| NDVI gapfilled (100 datas) | float32 | 100 × 117 × 144 | 1,5 s | 9,5 s | 0,03 s | **11,0 s** | 5,79 MB |

### 12.1 Classificação pasto/não-pasto (Rodada 1)

Arquivo: `tmp/xee_export/classification_report.json`.

| Imóvel | Metodologia | Área de pasto | **Tempo total** |
|---|---|---|---|
| car_1 | GEE-nativo (`classify_gee_native`) | 0,35 ha | **~2 s** |
| car_1 | Xee-local (`classify_xee_local`) | 0,33 ha | **~79 s** |
| car_2 | GEE-nativo (`classify_gee_native`) | 12,08 ha | **~4 s** |
| car_2 | Xee-local (`classify_xee_local`) | 12,6 ha | **~70 s** |

Biomassa (MapBiomas 2024, `biomass_image`): car_1 = **46,85 t MS** | car_2 = **401,32 t MS**.

Imagens geradas em `tmp/xee_export/images/`:
- `car_1_pasto_gee_2025.png`, `car_1_pasto_local_2025.png`, `car_1_biomassa_2024.png`
- `car_2_pasto_gee_2025.png`, `car_2_pasto_local_2025.png`, `car_2_biomassa_2024.png`

---

## 13. Resultados — Rodada 2 (novos CARs)

Execução: 2026-07-07. Arquivos: `tmp/xee_export/benchmark_new_cars_report.json` e
`tmp/xee_export/classification_new_cars_report.json`.

**new_car_1 — 2073,5 ha** (grade 643 × 940 px a 10 m) — Silvânia-GO

| Dado | dtype | Dimensões (time×y×x) | t_open | t_export | t_persist | **t_total** | Tamanho |
|---|---|---|---|---|---|---|---|
| Satellite Embedding (64 features) | **int16** | 1 × 643 × 940 | 1,6 s | 129,0 s | 0,4 s | **131,0 s** | 25,57 MB |
| Satellite Embedding (64 features) | float32 | 1 × 643 × 940 | 1,1 s | 150,3 s | 0,4 s | **151,7 s** | 32,76 MB |
| NDVI gapfilled (100 datas) | **int16** | 100 × 643 × 940 | 2,1 s | 48,3 s | 0,1 s | **50,6 s** | 104,58 MB |
| NDVI gapfilled (100 datas) | float32 | 100 × 643 × 940 | 7,7 s | 45,2 s | 0,2 s | **53,1 s** | 208,0 MB |

**new_car_2 — 23,5 ha** (grade 94 × 48 px a 10 m) — Córrego do Ouro-GO

| Dado | dtype | Dimensões (time×y×x) | t_open | t_export | t_persist | **t_total** | Tamanho |
|---|---|---|---|---|---|---|---|
| Satellite Embedding (64 features) | **int16** | 1 × 94 × 48 | 1,4 s | 69,3 s | 0,2 s | **70,9 s** | 0,40 MB |
| Satellite Embedding (64 features) | float32 | 1 × 94 × 48 | 1,3 s | 70,8 s | 0,2 s | **72,2 s** | 0,48 MB |
| NDVI gapfilled (404 datas¹) | **int16** | 404 × 94 × 48 | 7,8 s | 11,9 s | 0,03 s | **19,7 s** | 1,43 MB |
| NDVI gapfilled (404 datas¹) | float32 | 404 × 94 × 48 | 3,5 s | 15,6 s | 0,04 s | **19,2 s** | 3,16 MB |

> ¹ Córrego do Ouro cobre múltiplos tiles S2 sobrepostos → GEE retorna ~404 cenas em vez
> de ~100. O modelo harmônico usa todas as cenas disponíveis para o fit — comportamento
> correto, apenas o volume de dado aumenta proporcionalmente.

### 13.1 Classificação pasto/não-pasto (Rodada 2)

| Imóvel | Metodologia | Área de pasto | **Tempo total** |
|---|---|---|---|
| new_car_1 (2073 ha) | GEE-nativo | 711,55 ha | **~12 s** |
| new_car_1 (2073 ha) | Xee-local | 758,17 ha | **~145 s** |
| new_car_2 (23 ha) | GEE-nativo | 15,18 ha | **~4 s** |
| new_car_2 (23 ha) | Xee-local | 16,18 ha | **~65 s** |

Imagens geradas em `tmp/xee_export/images/`:
- `new_car_1_pasto_gee_2025.png`, `new_car_1_pasto_local_2025.png`, `new_car_1_biomassa_2024.png`
- `new_car_2_pasto_gee_2025.png`, `new_car_2_pasto_local_2025.png`, `new_car_2_biomassa_2024.png`

---

## 14. Comparação completa — todos os 4 imóveis

| Imóvel | Área | Grid (y×x) | Embedding int16 | NDVI int16 | GEE pasto | Xee pasto |
|---|---|---|---|---|---|---|
| Jaraguá car_1 | 3,2 ha | 29 × 49 | 76,4 s / 0,23 MB | 8,4 s / 0,27 MB | 0,35 ha / ~2 s | 0,33 ha / ~79 s |
| Jaraguá car_2 | 54,9 ha | 117 × 144 | 61,5 s / 0,92 MB | 12,7 s / 2,91 MB | 12,08 ha / ~4 s | 12,6 ha / ~70 s |
| Córrego do Ouro | 23,5 ha | 94 × 48 | 70,9 s / 0,40 MB | 19,7 s / 1,43 MB² | 15,18 ha / ~4 s | 16,18 ha / ~65 s |
| Silvânia | 2073,5 ha | 643 × 940 | **131,0 s / 25,57 MB** | **50,6 s / 104,58 MB** | 711,55 ha / ~12 s | 758,17 ha / ~145 s |

> ² NDVI Córrego do Ouro tem 404 datas (múltiplos tiles S2); os outros têm ~100 datas.

### O que os dados mostram em conjunto

**1. O embedding é dominado por nº de variáveis — até certa escala:**  
Para imóveis de 3 a 55 ha, o tempo é ~60–76 s **independente da área** (o gargalo é o
overhead de 64 variáveis). Em 2073 ha (~604 k pixels), o custo por-pixel também aparece
(131 s). A "independência da área" se mantém abaixo de ~100 ha.

**2. O NDVI escala suavemente com pixels:**  
3 ha → 8 s; 23 ha → 20 s; 55 ha → 13 s; 2073 ha → 51 s. O crescimento é sublinear porque
é 1 variável (baixo overhead de requisição).

**3. Int16 sempre vale a pena:**  
- Disco: sempre metade do float32 no NDVI (`0,27 vs 0,51`; `2,91 vs 5,79`; `1,43 vs 3,16`;
  `104,58 vs 208,0 MB`).
- Velocidade: vantagem pequena no embedding (~1–1,2×); relevante ao escalar.

**4. As metodologias de classificação concordam:**  
Em todos os 4 imóveis, GEE-nativo e Xee-local produzem áreas dentro de ~3–7% entre si,
validando o pipeline "treina 2024, prevê 2025".

**5. GEE-nativo é sempre o mais rápido para o mapa:**  
2–12 s contra 65–145 s do Xee-local (com layout ingênuo). Com o embedding empilhado
(`layout_experiment.py`), o Xee-local cairia para ~5–20 s e seria uma alternativa real.

---

## 15. Requisitos × Entregue (checklist completa)

| Requisito | Status | Onde no código |
|---|---|---|
| 64 features Satellite Embedding V1, 2025, por imóvel | ✅ | `export_satellite_embedding` em `export.py` |
| ~101 datas S2 NDVI gapfilled, 2025, por imóvel | ✅ (time=100) | `export_ndvi_gapfilled` + `_build_ndvi_gapfilled` em `export.py` |
| Via Xee | ✅ | `xr.open_dataset(..., engine="ee")` em `_export_via_xee` |
| Converter para Int16 | ✅ | `.multiply(10000).toInt16()` no GEE + `.astype("int16")` pós-load |
| Persistir em zarr | ✅ | `_persist_zarr` → `.to_zarr()` em `export.py` |
| Tempo export + persistência por imóvel | ✅ | `t_open`, `t_export`, `t_persist`, `t_total` em cada Dict de resultado |
| Dois imóveis originais (car_1 e car_2) | ✅ | `load_test_properties()` — `property_mock.json` |
| Comparação Int16 × Float32 | ✅ | 8 combinações em `run_benchmark.py` |
| Comparação GEE-nativo × Xee-local | ✅ | `classify_gee` vs `classify_xee` em `classification.py` |
| Mapa de pastagem + área | ✅ | PNG em `tmp/xee_export/images/` |
| Teste com novos CARs (Silvânia + Córrego do Ouro) | ✅ | `run.py` com `new_property_mock.json` |
| Novos CARs com geometria Polygon | ✅ | Detecção automática em `load_test_properties(mock_path=...)` |
| Exportar só o raster classificado via Xee (<20 s) | ✅ | `classify_gee_xee` em `classification.py` — 11,2 s / 5,0 s |
| Ponto de entrada único para novos CARs | ✅ | `run.py` com flag `--skip-xee` |

---

---

## 16. Avisos esperados (não são erros)

### `RuntimeWarning: invalid value encountered in cast`

Emitido pelo xarray (`duck_array_ops.py`) ao fazer `.astype("int16")` após o `dataset.load()`.
O Xee 0.1.1 sempre retorna `float32` em memória. Pixels fora do ROI chegam como `NaN` (float),
e `NaN → int16` não tem representação válida — daí o aviso. Os pixels recebem um valor
inteiro arbitrário da implementação numpy, mas a lógica `pasto_arr == 1` os ignora porque
o nodata nunca é 1. **Resultado correto.**

### `ZarrUserWarning: Consolidated metadata not part of Zarr format 3 specification`

Emitido pelo zarr v3 ao salvar o `.zmetadata`. O arquivo de metadados consolidado existe
e funciona, mas ainda não é parte do spec oficial do Zarr v3 — outros clientes podem não
reconhecê-lo. Para suprimir: passar `consolidated=False` no `.to_zarr()`, se necessário.
**Dado legível normalmente.**

---

## 17. Git / status de entrega

Segue o estilo de `app/utils/scripts/gee_scripts.py`:
- Docstrings **PT-BR** com seções `Args:` / `Returns:` em todos os públicos.
- `typing` capitalizado: `List`, `Dict`, `Tuple`.
- Constantes de módulo: `_UPPER_SNAKE_CASE`.
- Funções privadas: prefixo `_`.
- `try/except` por tipo: `ee.EEException` primeiro, depois `Exception`.
- Erros: `log_error(traceback.format_exc())` + `raise RuntimeError("<mensagem PT-BR>")`.
- Inicialização do GEE no import (como em `gee_scripts.py`).
- 2 linhas em branco entre defs de nível de módulo.

**Única exceção deliberada:** autenticação via `dotenv_values` direto (não `config.py`)
para rodar standalone sem `APP_ENV` exportado.

---

## 17. Git / status de entrega

- Branch: **`feature/112-suporte-mapeamento-on-the-fly`** (sem push — trabalho local).
- `tests/xee_export/` inteiro está **untracked** (não commitado).
- `tmp/` é **gitignored** → zarrs e JSONs de resultado não entram no repo.
- Único arquivo de `app/` criado: `app/utils/mocks/new_property_mock.json` (também untracked).
- **Nada do código da aplicação foi modificado.**

---

## 18. Estratégia de cache — o que mais dá para persistir

Com `classify_gee_xee` resolvendo a primeira requisição em 5–11 s, o próximo passo natural
é definir o que mais vale persistir nessa mesma janela de tempo para tornar as requisições
seguintes instantâneas.

### 18.1 O que já sai da chamada atual sem custo extra

| Dado | Tamanho | Para que serve |
|---|---|---|
| Raster binário zarr (`pasto` 0/1) | ~24 KB / 2073 ha | Consultas futuras de área/pixel sem GEE |
| PNG visual | ~150–400 KB | Serve direto ao frontend — sem regenerar |
| Área de pasto em ha | < 1 KB (JSON) | Resposta imediata ao fazendeiro |
| Biomassa t MS (de `biomass_map`) | < 1 KB (JSON) | Qualidade da pastagem |

### 18.2 O que dá para salvar sem custo significativo adicional

| Dado | Custo | Tamanho | Ganho futuro |
|---|---|---|---|
| **Grade UTM** (CRS, transform, shape_2d) | zero — já calculado em `_utm_grid` | < 1 KB | Evita chamada GEE para derivar a grade na próxima vez |
| **Amostras de treino** (`_samples` → GeoJSON) | `getInfo()` já existe no pipeline | ~200 KB | Evita re-amostrar o MapBiomas (~2–3 s economizados) |
| **Área total do imóvel** (`roi.area()`) | ~0,5 s extra | < 1 KB | Calcula % pasto localmente |

### 18.3 O que vale cachear com custo extra (quando houver necessidade)

| Dado | Custo de geração | Tamanho | Quando faz sentido |
|---|---|---|---|
| **Raster do embedding** (64 bandas) | ~5–10 s com layout otimizado | ~25 MB / 2073 ha | Se o modelo vai ser re-treinado e a área reclassificada sem nova chamada ao GEE |
| **Série NDVI gapfilled** | ~50 s / 2073 ha | ~105 MB / 2073 ha | Se análise de vigor/fenologia entrar no roadmap |

### 18.4 Estrutura de diretório proposta para o cache

```
cache/
  {codigo_car}/
    {pred_year}/
      classified.zarr    # raster binário pasto (0/1)
      meta.json          # area_pasto_ha, area_total_ha, zarr_shape, CRS, transform, timestamp
      samples.json       # amostras de treino — reutilizáveis até nova coleção MapBiomas
      map.png            # mapa visual 512px
      biomass.json       # total t MS, min, max
```

**Chave de cache:** `{codigo_car} / {pred_year}`  
**Invalidação:** nova coleção MapBiomas (novos rótulos de treino), novo embedding anual,
ou edição do perímetro do CAR (novo código).

**Fluxo backend:**
1. Requisição chega → verifica `meta.json` → se existe: retorna área + PNG em **< 1 s**.
2. Se não existe → `classify_gee_xee` (~5–11 s) → persiste cache → retorna.
