# Relatório em PDF — Sumário da Implementação

Documento de referência técnica descrevendo **como** um relatório em PDF foi
implementado em Go, para servir de base a propostas em outros projetos.
O conteúdo é genérico: não expõe credenciais, rotas internas, nomes de
serviços ou regras de negócio específicas.

---

## 1. Objetivo

Gerar, sob demanda, um relatório em PDF que consolida dados provenientes de
múltiplas fontes (banco/serviço de dados + armazenamento de arquivos) em um
único documento navegável, com:

- Seções organizadas (dados gerais, sub-registros, tabelas de itens);
- **Anexos**: arquivos armazenados fora do PDF (ex.: notas, comprovantes),
  acessíveis por **links de download temporários** ou empacotados em um **ZIP**;
- Layout consistente (cabeçalho/rodapé repetidos, paginação, quebra de linha
  automática) sem depender de um motor HTML→PDF.

## 2. Stack

| Camada | Escolha |
|--------|---------|
| Linguagem | Go |
| Geração de PDF | [`github.com/go-pdf/fpdf`](https://github.com/go-pdf/fpdf) |
| HTTP | framework web (handler REST) |
| Armazenamento de anexos | serviço compatível com S3 (ex.: MinIO) |
| IDs de arquivo | `github.com/google/uuid` |

O `fpdf` foi escolhido por ser **puro Go, sem dependências nativas** (não
precisa de Chromium/wkhtmltopdf), o que simplifica muito o deploy em
container. O custo é escrever o layout de forma imperativa (coordenadas,
larguras, quebras), em vez de declarar HTML/CSS.

## 3. Arquitetura em camadas

O fluxo foi separado em três responsabilidades bem definidas, o que mantém a
lógica de PDF reutilizável e independente do domínio:

```
 HTTP handler            → recebe requisição, autentica, busca e NORMALIZA os dados
   │                        (traduz o payload cru em uma struct de relatório)
   ▼
 Report builder          → recebe a struct e decide O QUE aparece no PDF
   │  (relatorio/*.go)      (seções, ordem, agrupamentos, quais campos exibir)
   ▼
 PDFHelper               → sabe COMO desenhar (tabelas, títulos, avisos, links)
      (utils/pdf/*.go)      — genérico, sem conhecimento do domínio
```

**Por que separar?** O `PDFHelper` não conhece "produtor", "lote" nem nenhum
termo de negócio — só conhece "tabela chave-valor", "tabela de dados",
"título de seção". Isso o torna reaproveitável para qualquer outro relatório.

### 3.1 Struct de dados do relatório

O handler converte o payload cru (um `map[string]interface{}` vindo da fonte
de dados) em uma struct tipada e "achatada", com todos os campos já como
`string` formatada. Exemplo simplificado:

```go
type ReportData struct {
    Codigo      string
    DataEmissao time.Time

    Cabecalho   HeaderInfo
    Itens       []ItemInfo   // renderizados como tabela / blocos
    Anexos      []AnexoInfo  // arquivos externos com link de download
}
```

Vantagem: toda a "sujeira" de acesso ao payload (checagens de tipo,
`nil`, formatos de data variados) fica concentrada no handler; o builder
recebe dados limpos e só se preocupa com apresentação.

## 4. O `PDFHelper` — o núcleo reutilizável

Uma pequena "biblioteca" acima do `fpdf`, configurada por struct:

```go
helper := pdf.NewPDFHelper(pdf.PDFHelperConfig{
    LogoPath:    logoPath,     // PNG opcional
    NomeEmpresa: nomeEmpresa,  // texto do cabeçalho
    OutputDir:   "/tmp/reports",
})

helper.AddHeader("Título do Relatório") // cabeçalho repetido em toda página
helper.AddFooter()                       // rodapé "Página X/N"
helper.NewPage()
```

Configuração base: A4 retrato, unidade `mm`, `SetAutoPageBreak(true, 15)`,
margens lidas do próprio `fpdf` para calcular a largura útil.

### 4.1 Cabeçalho e rodapé automáticos

O `fpdf` chama funções registradas via `SetHeaderFunc` / `SetFooterFunc` **em
cada nova página**. O cabeçalho posiciona logo (opcional), nome e título, e
desenha uma linha divisória; o rodapé usa `AliasNbPages` para renderizar
`Página X/{nb}` com total de páginas resolvido no fechamento.

### 4.2 Primitivas de conteúdo

| Método | Papel |
|--------|-------|
| `SectionTitle(t)` | Barra colorida de seção. Também **memoriza** a seção corrente. |
| `SubSectionTitle(t)` | Subtítulo (ex.: agrupamento por categoria). |
| `KeyValueTable(rows)` | Tabela 2 colunas (rótulo → valor), zebrada. |
| `KeyValueTableWithLinks(rows, links)` | Idem, com valores que viram hyperlink. |
| `DataTable(cfg)` | Tabela multi-coluna com cabeçalho, alinhamento e links. |
| `Warning(t)` | Caixa de destaque (aviso). |
| `Text(t)` | Bloco de texto livre. |
| `SaveToFile(prefix)` | Grava o PDF e devolve o caminho. |

### 4.3 Detalhes que "fazem o PDF parecer profissional"

Estes são os pontos que costumam dar mais trabalho e valem destacar na
proposta, porque o `fpdf` **não** os resolve sozinho:

1. **Altura de linha dinâmica (word-wrap real).**
   Em `DataTable`, para cada célula o texto é pré-quebrado com
   `SplitLines(texto, largura)`; a altura da linha é
   `maxLinhas × alturaLinha`. As células são desenhadas como retângulos
   (`Rect`) da altura total e o texto é centralizado verticalmente — assim
   colunas com muito texto não estouram a linha (equivalente a
   `word-wrap: break-word`).

2. **Quebra de tokens longos sem espaço.**
   `SplitLines` só quebra em espaços, então hashes, chaves de bucket e códigos
   longos vazariam a célula. Um pré-processador (`breakLongTokens`) mede cada
   token com `GetStringWidth` e insere pontos de quebra a cada trecho que
   ainda cabe na largura — respeitando `\n` já existentes.

3. **Cabeçalho "grudento" + contexto de seção em tabelas longas.**
   Antes de desenhar cada linha, verifica-se se ela cabe na página; se não,
   força-se `AddPage()` e **redesenha-se** a barra da seção corrente + o
   cabeçalho da tabela no topo (equivalente a `table-header-group` na
   impressão CSS). Por isso o helper memoriza a `currentSection`.

4. **Normalização de larguras de coluna.**
   As larguras informadas são ajustadas ao número de colunas e escaladas para
   somar exatamente a largura útil da página, mantendo todas as tabelas
   alinhadas às margens.

5. **Acentuação com fontes built-in.**
   As fontes nativas do `fpdf` (Arial/Helvetica etc.) não são UTF-8. Todo
   texto passa por um tradutor
   (`UnicodeTranslatorFromDescriptor("")` → ISO-8859-1) antes de ir para a
   página. Encapsular isso num helper `utf8(...)` evita esquecer a conversão
   em algum ponto e ver acentos quebrados.

## 5. Anexos: duas estratégias de saída

Arquivos ficam **fora** do PDF, em armazenamento compatível com S3. O
relatório oferece dois formatos, selecionados por parâmetro na requisição:

- **`pdf` (padrão)** — para cada anexo gera-se um **link de download
  pré-assinado** com validade limitada (ex.: 7 dias) e insere-se como
  hyperlink clicável na célula correspondente. O PDF fica leve.
  Como os links expiram, o relatório imprime um **aviso** com a data de
  emissão e a data de expiração dos links.

- **`zip`** — baixa os anexos do armazenamento para um diretório temporário e
  monta um **ZIP** com o PDF do relatório + os arquivos, organizados em
  subpastas. O empacotamento faz **streaming** (`io.Copy`) para não carregar
  arquivos grandes inteiros em memória, e deduplica anexos repetidos. Se não
  houver anexos, cai de volta para o PDF simples.

Arquivos temporários (PDF e diretório do ZIP) são removidos via `defer` após
a resposta.

## 6. Testabilidade — comando de mock

Para iterar no layout sem depender da fonte de dados real, há um pequeno
`main` (`cmd/mock_relatorio`) que monta a struct do relatório com dados
fictícios e chama o mesmo builder, gerando um PDF local. Isso permite
ajustar espaçamentos, quebras e cores rapidamente.

```bash
go run ./cmd/mock_relatorio   # gera um PDF de exemplo em /tmp/reports
```

## 7. Aprendizados / recomendações para reuso

- **Separe "montar dados" de "desenhar".** O helper de PDF não deve saber
  nada do domínio — só primitivas visuais. Isso o torna reaproveitável.
- **`fpdf` é imperativo.** Você controla tudo (bom para consistência e
  deploy sem dependências nativas), mas layout complexo dá trabalho; invista
  cedo nas primitivas de word-wrap, cabeçalho grudento e conversão de encoding.
- **Trate anexos como cidadãos externos.** Links pré-assinados mantêm o PDF
  leve; ofereça o ZIP para quem precisa do pacote completo offline. Sempre
  sinalize a validade dos links no próprio documento.
- **Tenha um gerador de mock** desde o início — encurta muito o ciclo de
  ajuste visual.

---

*Referência de implementação em Go com `go-pdf/fpdf`. Adapte nomes de campos,
seções e regras de anexos ao domínio do projeto de destino.*
