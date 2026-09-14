---
name: ua-calculator
description: Cálculo de Unidade Animal (UA) segundo a metodologia do Lapig.
license: Apache-2.0
metadata:
  version: "1.0.0"
  author: lapig-team
  tags: ["metodologia", "unidade animal"]
---

# Cálculo de UA

Use esta skill quando precisar calcular a lotação ou capacidade de suporte animal, e explicar a metodologia adotada pelo laboratório.

## When to Use

- O usuário solicitar o cálculo da lotação real de uma propriedade.
- O usuário perguntar sobre a capacidade de suporte ideal de uma pastagem.
- O usuário pedir a conversão de um rebanho para Unidades Animais (UA).
- For necessário interpretar estatísticas de biomassa ou forragem retornadas pelo GEE.

## Process

1. **Coletar Dados**: Utilize a tool `get_pasture_stats` para recuperar a biomassa de pastagem (matéria seca) da propriedade.
2. **CRÍTICO — Verificar o período antes de qualquer conta**: o resultado de biomassa vem com um campo `period` que é **"mensal"** (fonte T2G, valor acumulado em só 1 mês) ou **"anual"** (fallback GPW, valor já é o total do ano). A fórmula abaixo espera SEMPRE um total **anual**.
   - Se `period == "anual"`: use o valor de `amount` direto na fórmula.
   - Se `period == "mensal"`: **multiplique o valor por 12** antes de usar (aproximação assumindo produção mensal aproximadamente constante ao longo do ano) e **avise explicitamente o usuário** que a capacidade de suporte foi estimada a partir de uma extrapolação de 1 mês, não de um total anual medido — isso é uma aproximação, não um dado direto.
   - Nunca divida um valor mensal por 8,2 sem antes multiplicar por 12. Fazer isso subestima a forragem anual em ~12x e distorce completamente a lotação recomendada.
3. **Formular a Equação**: Identifique a variável desejada e monte a expressão matemática usando estritamente os pilares da Metodologia Lapig (450 kg para UA e 8,2 para demanda), já com o valor de biomassa anualizado do passo 2.
4. **Calcular com Ferramenta**: Envie a expressão matemática formulada diretamente para a sua ferramenta de calculadora.
5. **Explicar e Diagnosticar**: Apresente o resultado calculado e detalhe de forma didática os fatores utilizados no cálculo, incluindo se houve anualização de valor mensal (passo 2). Forneça um breve diagnóstico se a área suporta ou não o rebanho atual.

## Best Practices

- **Aplique as Fórmulas Corretas do Lapig**:
  - *UA Total do Rebanho* = Peso Total do Rebanho (kg) / 450
  - *Lotação Real (UA/ha)* = UA Total do Rebanho / Área da Pastagem (ha)
  - *Capacidade Ideal (UA Ideal Total)* = Forragem Total Disponível (t MS/ano) / 8.2
  - *Capacidade Ideal por Hectare* = Capacidade Ideal Total / Área da Pastagem (ha)
- **Justifique a Referência de UA**: Sempre deixe claro que o cálculo assume 1 UA como 450 kg de peso vivo (padrão Nelore).
- **Explique o Fator de Proteção (Demanda)**: Ao mencionar o divisor de 8,2 t MS/UA/ano, esclareça que ele representa o dobro do consumo animal (que é 2,5% do peso vivo). Explique que o Lapig adota essa folga pois 50% da biomassa é perdida pelo pisoteio, garantindo o desempenho animal e a preservação do pasto.
- **Transparência**: Mostre os números substituídos na fórmula durante a explicação (ex: "Dividimos as 10.000 toneladas de forragem por 8,2...").
- **Nunca pule a checagem de período**: sempre declare no cálculo se o valor de biomassa usado já era anual ou se foi anualizado a partir de um mês (ver Process, passo 2). Essa checagem é obrigatória, não opcional.