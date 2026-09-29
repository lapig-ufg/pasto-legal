# Histórico — revisão e entrega do mapeamento on-the-fly (issue #112)

Registro do que foi investigado, corrigido e validado na branch
`feature/112-suporte-mapeamento-on-the-fly` antes da abertura do PR pra
`develop`. Serve de referência pra não perder o contexto ao continuar o
trabalho (ex.: melhorias do boletim em PDF, numa branch nova a partir desta).

## Contexto de partida

A branch já tinha as quatro camadas da issue #112 implementadas (uso do solo,
biomassa histórica, idade e vigor de pastagem, todas on-the-fly) — nenhuma
delas existe em `develop` hoje; é o PR desta branch que leva isso pra lá pela
primeira vez. O trabalho desta sessão foi: sincronizar com 43 commits de
`develop`, revisar o que já existia, corrigir um erro de unidade real, e
validar tudo ao vivo antes do PR.

## 1. Correção de unidade — total de biomassa

`get_biomass()` (`app/services/geospatial/gee.py`) somava a densidade de
biomassa (t/ha) de cada pixel multiplicando por uma constante fixa de
hectare/pixel (0,09 ha pro pixel "de 30m" do GPW, 0,01 ha pro "de 10m" do
Time2Graze) pra chegar no total da propriedade. Área real de pixel varia com
latitude/projeção — trocado por `ee.Image.pixelArea()`, mesmo padrão que
idade/vigor/LULC já usavam nesse arquivo. Medido: -4,6% a -4,7% de diferença
nas propriedades de teste.

No mesmo commit: rótulo do eixo Y do gráfico histórico corrigido de "t/ha"
(ambíguo, parece estoque) pra "t MS/ha/ano" (fluxo, o que a série realmente
mede), e dpi do gráfico aumentado (120→160) pra ficar mais nítido.

## 2. Sincronização com `develop`

43 commits trazidos, 7 arquivos com conflito real, reconciliados função a
função (não commitei os detalhes de resolução de conflito na mensagem do PR —
só o resultado final). Pontos que valem lembrar caso apareça alguma dúvida
depois:

- `get_biomass()`, `get_pasture_age/vigor/land_use_land_cover` e
  `query_pasture_statistics`: mantida a versão desta branch — a de `develop`
  ainda tinha a constante de área fixa e travava idade/vigor/LULC no ano 2024
  fixo (regressão), em vez de usar o ano pedido.
- Mapa de biomassa T2G (`retrieve_t2g_biomass_image`): adotada a versão de
  `develop`, que evoluiu com filtro de data ruim conhecida do satélite,
  fallback de mês e paleta melhor — mas a duplicação do fator de conversão
  (LUEmax × IPCC × conversão) foi removida, voltando a vir só de
  `pasture_biomass.py`.
- Mapa de biomassa MapBiomas (imagem estática): `develop` tinha uma versão
  própria (`retrieve_mapbiomas_biomass_image`) com os MESMOS bugs que
  acabamos de corrigir (banda por índice, constante de área fixa na legenda)
  — descartada em favor de `retrieve_gpw_biomass_image` desta branch.
- `pasture_classification.py` e `pasture_cache.py`: mantida a versão desta
  branch (superset — extrai `_classify()`/`xee_grid.py` pra reuso por idade e
  vigor, que `develop` não tem).
- As 3 tools novas (`get_pasture_biomass_history`,
  `get_pasture_age_on_the_fly`, `get_pasture_vigor_on_the_fly`) foram
  migradas do padrão antigo (`car_codes: list[str]`, busca manual em
  `session_state`, schema `RuralProperty`) pro padrão atual do arquivo
  (`feature_id: str` + `resolve_feature()` + schema `Feature`), já que o
  schema antigo foi removido em `develop`.
- Bug real pego só rodando os testes (não pelos marcadores de conflito): um
  `target_year` órfão sobrou do merge automático dentro de
  `_get_t2g_biomass_image`, que não tem mais esse parâmetro (agora
  `start_year`/`end_year`) — corrigido e coberto pelo teste real.

## 3. Mapa de pastagem — título e legenda

`_render_classification_image` (`pasture_classification.py`) só desenhava a
sobreposição verde crua, sem título nem legenda — diferente dos mapas de
idade/vigor/biomassa, que já usam `append_discrete_legend`/
`append_continuous_colorbar`. Adicionado o mesmo acabamento (título
"Classificação de Pastagem (ano)" + legenda "Pastagem"). `_CACHE_VERSION`
bumpada de v1 pra v2 pra invalidar imagens já cacheadas sem o acabamento
novo.

## 4. Validação ao vivo (ambiente limpo)

Container Docker reconstruído do zero (`--no-cache`), `tmp/` inteiro limpo
(cache de pastagem/idade/vigor/biomassa, banco de sessões), sessão de usuário
nova. Testado no navegador, nessa ordem, tudo confirmado funcionando:
cadastro de propriedade → mapa de pastagem → mapa de biomassa → série
histórica de biomassa → mapa de idade → mapa de vigor → capacidade de suporte
→ boletim em PDF.

Suíte automatizada: 70 testes rápidos (sem GEE) + testes reais contra o Earth
Engine de biomassa histórica, classificação de pastagem, idade e boletim —
todos passando. Vigor teve 1 falha de timeout de rede do próprio Earth Engine
(pré-existente, não relacionada ao trabalho).

## 5. Problemas encontrados e NÃO corrigidos (fora do escopo deste PR)

Dois problemas reais, confirmados com teste real, ficaram registrados pra
resolver depois — não foram mexidos porque não fazem parte do que essa
entrega pedia:

### 5.1 Capacidade de suporte — extrapolação mensal × 12

Quando só há dado mensal de biomassa disponível, o cálculo de capacidade de
suporte extrapola linearmente esse único mês pra estimar a produção anual
(ex.: 4,60 t MS/ha em agosto × ~12 ≈ 55,14 t MS/ha/ano) — ignora sazonalidade,
o mesmo erro já identificado e corrigido na branch irmã `feature/biomassa_on_the_fly`
(que tem uma tool dedicada `get_stocking_capacity` com trava explícita contra
essa conta). Essa correção nunca foi portada pra esta branch.

### 5.2 Classificação de pastagem — desbalanceamento de amostras

O RandomForest de uso do solo (`_samples()` em `pasture_classification.py`)
treina com proporção fixa de amostras (600 pastagem / 4400 não-pastagem,
~12%/88%) dentro de um buffer de 3km. Testado na propriedade Rio Verde-GO
(1.463 ha, região de lavoura): com essa proporção, o modelo previu 4,68 ha de
pastagem no próprio ano de treino, contra 23,92 ha que o MapBiomas (o rótulo
usado pra treinar) aponta pra mesma propriedade/ano — quase 5x abaixo.
Balanceando a amostra (50/50), o resultado inverte pro lado oposto: ~42 ha,
agora superestimando. A proporção de treino desloca fortemente o resultado
pra qualquer lado; nenhum dos dois extremos testados acerta o alvo. Precisa
de calibração cuidadosa, testando em propriedades de perfis diferentes antes
de fixar uma proporção nova.

## 6. PR aberto

Branch: `feature/112-suporte-mapeamento-on-the-fly` → `develop`.
Descrição do PR cobre: o que foi pedido (issue #112), o que foi revisado, o
que foi corrigido, como cada camada é gerada (metodologia de uso do solo,
biomassa histórica, idade e vigor) e o que foi testado. Os itens da seção 5
acima foram comentados na issue #112 separadamente, não citados no PR (ainda
não corrigidos).
