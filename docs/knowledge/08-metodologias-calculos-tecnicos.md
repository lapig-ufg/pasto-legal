# Capítulo 8: Metodologias Agronômicas e Cálculos Técnicos

Este capítulo detalha as bases científicas, parâmetros e fórmulas matemáticas utilizadas pela inteligência artificial do sistema Pasto Legal para a geração de diagnósticos agronômicos. Todas as análises seguem os padrões estabelecidos pela Metodologia Lapig.

## 8.1. As quatro métricas de biomassa (e por que elas não são a mesma coisa)

O sistema trabalha com quatro grandezas distintas. Elas têm unidades diferentes, períodos diferentes e fontes diferentes, e **nunca** podem ser trocadas uma pela outra:

| Métrica | Unidade | O que responde | Fonte |
|---|---|---|---|
| Produtividade mensal de matéria seca | t MS/ha/mês | Quanto o pasto **produziu** no mês | Time2Graze uGPP (10 m) |
| Produtividade anual de matéria seca | t MS/ha/ano | Quanto o pasto **produziu** no ano | MapBiomas Coleção 10 (30 m) |
| Biomassa em pé | t MS/ha | Quanto de massa seca **está** no piquete agora | Modelo calibrado em campo |
| Forragem disponível | t MS/ha | Quanto pode ser **pastejado** | Derivada da biomassa em pé |

Produtividade é **fluxo** (produção acumulada num intervalo). Biomassa em pé é **estoque** (o que existe num instante). Forragem disponível é o estoque menos o resíduo mínimo, vezes a taxa de utilização.

Um pasto pode ter alta produtividade e pouca massa em pé (pastejo intenso), e o contrário também ocorre (pasto diferido). Por isso a conversão de GPP/uGPP em matéria seca produz **produtividade**, nunca biomassa em pé nem forragem disponível.

Toda estimativa entregue pelo sistema carrega obrigatoriamente: métrica, fonte, período, unidade, resolução do raster, resolução efetiva da máscara, cobertura válida, incerteza, versão do modelo e limitações.

### 8.1.1. Produtividade mensal (Time2Graze uGPP)

O produto `projects/wri-lcl-time2graze/assets/ugpp_cf_10m_v1` traz radiação fotossinteticamente ativa absorvida, em banda `ugpp` (uint16, 10 m, EPSG:4326). A cadeia de conversão, por pixel, é:

$$\text{t MS/ha} = DN \times 0{,}01 \times LUE_{max} \times F_{MS} \times n_{dias} \times 0{,}01$$

onde:

- **0,01** é a escala de armazenamento do asset (DN → MJ/m²/dia);
- **LUEmax = 0,50 gC/MJ** é a eficiência máxima do uso da radiação para *Urochloa* spp. em pastagem cultivada brasileira (LAPIG/MapBiomas);
- **F_MS = 2,7** converte carbono em matéria seca aérea (Metodologia LAPIG; o IPCC 2006 GL Vol.4 Cap.6 adota fração de carbono de 0,47 na biomassa de pastagem);
- **n_dias** é o número de dias do período;
- **0,01** converte g/m² em t/ha.

O intervalo de incerteza vem da faixa publicada de LUEmax (0,40 a 0,65 gC/MJ), à qual a estimativa é linear.

**Atenção: dois assets, duas escalas.** O Time2Graze publica a série uGPP em dois assets que guardam o **mesmo sinal físico em escalas diferentes**:

| Asset | Escala | Tipo | Cobertura temporal (21/09/2026) |
|---|---|---|---|
| `ugpp_cf_10m_v1` | **0,01** | uint16 | 01/01/2025 a 30/07/2026 (histórico) |
| `ugpp_prod_10m_v1` | **0,1** | int16 | 28/06/2026 a 21/08/2026 (produção corrente) |

Medida nas sete datas em comum sobre o imóvel de referência, a razão `prod`/`cf` é 0,0978 a 0,1057 — média de ~0,10. **Trocar um asset pelo outro sem trocar a escala erra a estimativa em dez vezes.** Por isso cada asset tem o seu próprio contrato em `biomass_validation`, e o módulo escolhe o asset por período, levando junto a escala correspondente.

As coberturas de tile também diferem: o imóvel de Silvânia-GO não tem nenhuma cena no `cf`, mas tem 23 no `prod`. Manter os dois cobre propriedades que um só não cobriria.

**Sobre a escala inferida.** A documentação de unidade do produtor ainda não foi publicada, então as escalas estão registradas como *inferidas* e toda estimativa derivada carrega a sinalização `asset_scale_inferred`. A inferência tem evidências independentes:

1. **Checagem física.** Em janeiro de 2026, a média bruta sobre o imóvel de referência é 638. Com escala 0,01 isso dá 6,4 MJ/m²/dia de APAR, coerente com a radiação solar de ~19 MJ/m²/dia em Goiás em janeiro (PAR = 0,45 × 19 = 8,6; fPAR ≈ 0,8 → ~6,9). Com escala 0,1 daria 63,8 MJ/m²/dia — 3,4 vezes a radiação solar incidente total, o que é fisicamente impossível.
2. **Validação cruzada.** Acumulando o ano de 2025 inteiro no mesmo imóvel, a escala 0,01 produz 14,5 t MS/ha/ano contra 21,1 t MS/ha/ano do MapBiomas; a escala 0,1 produziria 144,9 t MS/ha/ano, cerca de sete vezes o MapBiomas.
3. **Concordância entre os assets.** Em julho de 2026 os dois, cada um com a sua escala, dão 1,15 e 1,34 MJ/m²/dia de APAR — uma diferença de ~16%, não de dez vezes.

**Limitações conhecidas do produto:**

- **Cobertura espacial parcial.** O piloto cobre poucos tiles MGRS. Propriedades fora deles não têm estimativa mensal — e nesse caso o sistema informa a ausência, em vez de entregar o valor anual do MapBiomas como se fosse mensal.
- **Cobertura temporal.** Verificada de 01/01/2025 a 30/07/2026 (em 21/09/2026). Os meses mais recentes podem não ter dado.
- **Cadência real de 13 a 20 cenas por mês** (revisita Sentinel-2), não diária. A fração de observações válidas por pixel varia de ~13% (estação úmida, muita nuvem) a ~92% (estação seca). A acumulação mensal é uma **extrapolação** da média das observações válidas para os dias do mês, e a cobertura válida é sempre reportada.
- **Outlier conhecido:** a cena de 03/07/2025 tem média bruta cerca de dez vezes o normal do mês e é excluída da série.

### 8.1.2. Produtividade anual (MapBiomas)

O asset `mapbiomas_brazil_collection10_pasture_biomass_v2` traz bandas anuais `biomass_2000` a `biomass_2024`. Os valores de pixel **já estão em t MS/ha/ano** — não há escala a aplicar, e multiplicar a legenda por qualquer fator é erro. A banda é sempre selecionada **pelo nome** (`biomass_2024`), nunca por índice.

Para o total da propriedade usa-se `ee.Image.pixelArea()`, jamais um multiplicador fixo por resolução: a área real do pixel varia com a latitude e com a projeção do asset.

Esta é a série histórica e a linha de base do sistema. Ela **não** é a condição atual da pastagem e nunca deve ser apresentada como estimativa mensal.

### 8.1.3. Série histórica on-the-fly 2000-2024 (issue #112)

A série histórica vem do `ggpp-30m/v1/ugpp_m` do Global Pasture Watch, uma imagem por ano de 2000 a 2024, grade nativa de 27,83 m. Apesar do sufixo `_m` no nome, o suporte é **anual**: `system:time_start` é 1º de janeiro e `system:time_end` é 31 de dezembro.

**A banda chama-se `gc_m2`, mas guarda uGPP — não carbono já convertido.** O LUEmax ainda precisa ser aplicado, exatamente como no pipeline mensal do Time2Graze. A cadeia é a do script oficial do GPW/LAPIG:

$$\text{t MS/ha/ano} = uGPP \times LUE_{max} \times F_{MS} \times 0{,}01$$

que reproduz o `DRY_BIOMASS_FACTOR = GRASS_LUEMAX_FACTOR \times IPCC\_FACTOR \times UNIT\_CONVERSION\_FACTOR` do script de referência.

**LUEmax**: 0,50 gC/m²/dia/MJ para *Urochloa* cultivada no Brasil. O script também traz 0,86 (MOD17A2, global) — que nos imóveis de referência quase dobra o valor do MapBiomas (+97%) e não se aplica ao Brasil.

**Fator carbono → matéria seca**: duas variantes documentadas no mesmo script.

| Fator | Origem | Viés vs MapBiomas (10 pares imóvel-ano) |
|---|---|---|
| **2,3** (padrão) | "more conservative way (MapBiomas Brazil)" | **−2,4%** (|máx| 7,7%) |
| 2,7 | Padrão IPCC | +14,5% (|máx| 17,3%) |

O padrão é 2,3 porque é a variante que concorda com o produto de biomassa do MapBiomas — no imóvel de Córrego do Ouro a diferença fica dentro de ±0,3% em todos os anos. O intervalo de incerteza é a distância entre as duas variantes.

**Resolução.** O produto é de 30 m. A série histórica não é, e não deve ser apresentada como, uma análise de 10 m.

**Exportação pixel a pixel.** Além das estatísticas agregadas, a série é exportada para zarr com **todos os pixels** da propriedade (via Xee, em grade UTM métrica derivada do centroide do imóvel), persistida no S3 em produção e em `tmp/` em desenvolvimento. Os valores são gravados em int16 como t MS/ha/ano × 1000, e os pixels fora da máscara de pastagem recebem o sentinela **−32768**, distinto de uma produtividade nula legítima. O arquivo carrega nos seus atributos a proveniência completa.

> **Armadilha do Xee:** o sentinela gravado no arquivo e o `ee_mask_value` passado ao Xee precisam ser **valores diferentes**. Usando o mesmo número nos dois papéis, o Xee converte o sentinela em NaN e o cast para int16 transforma o NaN em 0 — o pixel sem pastagem passaria a valer zero de produtividade. Além disso o `unmask` precisa de `sameFootprint=False`, senão os pixels fora do recorte continuam mascarados.

### 8.1.4. Biomassa em pé

Modelo supervisionado treinado **offline** e versionado, cujo alvo é massa seca em pé **medida em campo** (kg MS/ha ou t MS/ha). O modelo nunca é treinado contra GPP.

Covariáveis: Sentinel-2 (B2, B3, B4, B5, B6, B7, B8, B8A, B11, B12), Sentinel-1 (VV, VH, VV/VH e estatísticas temporais), índices (NDVI, EVI2, NDRE, LSWI e red-edge), chuva acumulada em 15/30/60/90 dias, temperatura, radiação, déficit hídrico, relevo, solo, bioma, sazonalidade e a máscara de pastagem. A composição óptica usa janela de 30 dias com filtragem por Cloud Score+ (`cs_cdf` ≥ 0,60).

Validação obrigatória e dupla: **espacial** por fazenda (`GroupKFold` por `farm_id`, para que parcelas vizinhas não apareçam em treino e teste) e **temporal** por safra (treino nas safras anteriores, teste na seguinte). São reportados RMSE, MAE, viés e R², por estrato. O intervalo de incerteza vem dos quantis P10/P50/P90, reordenados na inferência porque modelos quantílicos independentes se cruzam numa fração das amostras.

A inferência roda sob demanda sobre a propriedade; o treino, não. **Enquanto não houver um modelo calibrado registrado, esta métrica fica indisponível** — e o sistema diz isso, em vez de derivar um número a partir de GPP.

### 8.1.5. Máscara de pastagem e resolução efetiva

A máscara define a resolução **efetiva** da análise. Um produto de 10 m recortado por uma máscara de 30 m é, na prática, uma análise de 30 m, e a interface informa isso.

Estratégias disponíveis:

1. **Oficial** — Global Pasture Watch (`ggc-30m/v1-1`, resolução medida de 27,83 m).
2. **On-the-fly** — Satellite Embedding V1 + RandomForest, a 10 m, para os anos mais recentes.
3. **Híbrida** — as duas, expondo a **fração de divergência** entre os classificadores em vez de escolher uma silenciosamente.

Toda máscara reporta fonte, versão, ano de referência, resolução, área de pastagem, percentual da propriedade considerado pastagem e, na estratégia híbrida, a divergência.

## 8.2. Forragem disponível

Calculada **somente** a partir da biomassa em pé:

$$\text{Forragem disponível} = \max(\text{Biomassa em pé} - \text{Resíduo mínimo},\ 0) \times \text{Taxa de utilização}$$

Descontar resíduo de uma **produtividade** misturaria fluxo com estoque, e o sistema recusa essa operação.

Nenhum parâmetro tem valor universal. Os padrões por sistema de manejo são:

| Sistema | Resíduo mínimo (t MS/ha) | Taxa de utilização |
|---|---|---|
| Contínuo | 2,0 | 40% |
| Rotacionado | 1,5 | 55% |
| Diferido | 1,0 | 65% |

No pastejo contínuo o resíduo é mais alto e a utilização menor, porque o animal seleciona e o rebaixamento é desigual. No rotacionado o resíduo segue a meta de altura pós-pastejo e a utilização é maior, com o piquete ocupado por poucos dias. No diferido, a massa é acumulada na seca com utilização alta, assumindo recuperação nas águas.

A taxa de utilização ainda recebe ajuste sazonal — águas 1,00; transição 0,85; seca 0,70 — porque na seca o rebrote é lento e a pressão de pastejo precisa ser menor para não comprometer a rebrota das águas.

São igualmente configuráveis: espécie forrageira, intervalo de descanso, categoria animal, suplementação, lotação atual e áreas excluídas (degradadas, em recuperação ou não pastejáveis). **Os parâmetros efetivamente usados sempre acompanham o resultado.**

Referências: Embrapa Gado de Corte (manejo do pastejo de *Urochloa* spp.); Da Silva & Nascimento Jr. (2007), metas de altura e resíduo pós-pastejo.

## 8.3. Cálculo de Unidade Animal (UA) e Capacidade de Suporte

### 8.3.1. O Padrão de Unidade Animal (UA)

Para padronizar os cálculos de rebanho, a Metodologia Lapig adota uma referência fixa de peso. No sistema, **1 Unidade Animal (UA) equivale estritamente a 450 kg de peso vivo**, utilizando o padrão da raça Nelore.

A conversão do rebanho físico para UA é feita através da seguinte equação:

$$UA_{Total} = \frac{\text{Peso Total do Rebanho (kg)}}{450}$$

### 8.3.2. Cálculo da Lotação Real

Para entender a pressão atual que o rebanho exerce sobre o pasto, o sistema calcula a Lotação Real dividindo a quantidade total de Unidades Animais pela área útil da pastagem:

$$\text{Lotação Real (UA/ha)} = \frac{UA_{Total}}{\text{Área da Pastagem (ha)}}$$

### 8.3.3. O Fator de Demanda (o divisor 8,2)

Um animal consome em média 2,5% do seu peso vivo diariamente em matéria seca. O sistema assume ainda que **50% da biomassa é perdida por pisoteio, fezes e senescência**, e por isso dobra a demanda. O divisor não é uma constante mágica: ele é derivado dos seus componentes.

$$\text{Demanda} = \frac{450 \times 0{,}025 \times 2}{1000} \times 365 = 8{,}21\ \text{t MS/UA/ano}$$

Ao garantir que metade da matéria seca permaneça intocada, o sistema assegura tanto o desempenho nutricional adequado do animal quanto a preservação e rebrota sustentável do pasto.

### 8.3.4. As quatro grandezas da capacidade de suporte

O sistema **nunca** apresenta um único número de "capacidade". Ele separa:

- **Capacidade anual potencial** — o que a produtividade anual sustenta, em UA e UA/ha;
- **Capacidade no período** — o que a forragem disponível sustenta por um horizonte de pastejo informado;
- **Lotação atual informada** — o que o produtor declarou;
- **Saldo forrageiro estimado** — oferta menos demanda, em t MS.

$$\text{Capacidade anual potencial (UA)} = \frac{\text{Produtividade anual (t MS/ha/ano)} \times \text{Área (ha)}}{8{,}21}$$

$$\text{Capacidade no período (UA)} = \frac{\text{Forragem disponível (t MS/ha)} \times \text{Área (ha)}}{\text{Demanda diária} \times n_{dias}}$$

### 8.3.5. A restrição temporal (por que não se divide biomassa mensal por 8,2)

A demanda é expressa em **t MS por UA por ANO**. Dividir uma produtividade **mensal** por esse denominador subestima a capacidade em cerca de doze vezes.

O cálculo em base anual só é liberado quando:

- a estimativa tem suporte temporal anual (MapBiomas); **ou**
- existe uma série mensal completa de 12 meses consecutivos, sem buracos e sem meses faltando valor, somada em produtividade anual; **ou**
- o usuário fornece manejo e o cálculo é feito **por período**, a partir de forragem disponível — e nesse caso o resultado é rotulado como capacidade no período, nunca como anual.

Séries mensais incompletas, com buracos ou com meses sem valor são recusadas pela anualização.
