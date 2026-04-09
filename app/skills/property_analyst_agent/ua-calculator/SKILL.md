---
name: ua-calculator
description: Assistência na análise de pastagens e cálculo matemático de Unidade Animal (UA) segundo a metodologia exclusiva do Lapig.
license: Apache-2.0
metadata:
  version: "1.0.0"
  author: lapig-team
  tags: ["unidade animal", "metodologia"]
---

# When to Use

- O usuário solicitar o cálculo da lotação real de uma propriedade.
- O usuário perguntar sobre a capacidade de suporte ideal de uma pastagem.
- O usuário pedir a conversão de um rebanho para Unidades Animais (UA).
- For necessário interpretar estatísticas de biomassa ou forragem retornadas pelo GEE.

## Process

1. **Coletar Dados**: Utilize as ferramentas do `query_pasture_biomass` para recuperar a biomassa de pastagem (matéria seca) da propriedade.
2. **Formular a Equação**: Identifique a variável desejada e monte a expressão matemática usando estritamente os pilares da Metodologia Lapig (450 kg para UA e 8,2 para demanda).
3. **Calcular com Ferramenta**: Envie a expressão matemática formulada diretamente para a sua ferramenta de calculadora.
4. **Explicar e Diagnosticar**: Apresente o resultado calculado e detalhe de forma didática os fatores utilizados no cálculo. Forneça um breve diagnóstico se a área suporta ou não o rebanho atual.

## Best Practices

- **Aplique as Fórmulas Corretas do Lapig**:
  - *UA Total do Rebanho* = Peso Total do Rebanho (kg) / 450
  - *Lotação Real (UA/ha)* = UA Total do Rebanho / Área da Pastagem (ha)
  - *Capacidade Ideal (UA Ideal Total)* = Forragem Total Disponível (t MS/ano) / 8.2
  - *Capacidade Ideal por Hectare* = Capacidade Ideal Total / Área da Pastagem (ha)
- **Justifique a Referência de UA**: Sempre deixe claro que o cálculo assume 1 UA como 450 kg de peso vivo (padrão Nelore).
- **Explique o Fator de Proteção (Demanda)**: Ao mencionar o divisor de 8,2 t MS/UA/ano, esclareça que ele representa o dobro do consumo animal (que é 2,5% do peso vivo). Explique que o Lapig adota essa folga pois 50% da biomassa é perdida pelo pisoteio, garantindo o desempenho animal e a preservação do pasto.
- **Transparência**: Mostre os números substituídos na fórmula durante a explicação (ex: "Dividimos as 10.000 toneladas de forragem por 8,2...").