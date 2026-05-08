# Capítulo 8: Metodologias Agronômicas e Cálculos Técnicos

Este capítulo detalha as bases científicas, parâmetros e fórmulas matemáticas utilizadas pela inteligência artificial do sistema Pasto Legal para a geração de diagnósticos agronômicos. Todas as análises seguem os padrões estabelecidos pela Metodologia Lapig.

## 8.1. Cálculo de Unidade Animal (UA) e Capacidade de Suporte

A inteligência artificial do Pasto Legal realiza cálculos automáticos de lotação real e estima a capacidade de suporte ideal da pastagem cruzando os dados de biomassa (matéria seca) obtidos via satélite com os parâmetros de consumo animal.

### 8.1.1. O Padrão de Unidade Animal (UA)
Para padronizar os cálculos de rebanho, a Metodologia Lapig adota uma referência fixa de peso. No sistema, **1 Unidade Animal (UA) equivale estritamente a 450 kg de peso vivo**, utilizando o padrão da raça Nelore.

A conversão do rebanho físico para UA é feita através da seguinte equação:

$$UA_{Total} = \frac{\text{Peso Total do Rebanho (kg)}}{450}$$

### 8.1.2. Cálculo da Lotação Real
Para entender a pressão atual que o rebanho exerce sobre o pasto, o sistema calcula a Lotação Real dividindo a quantidade total de Unidades Animais pela área útil da pastagem:

$$\text{Lotação Real (UA/ha)} = \frac{UA_{Total}}{\text{Área da Pastagem (ha)}}$$

### 8.1.3. Capacidade de Suporte Ideal e o Fator de Proteção
O cálculo da capacidade de suporte ideal — ou seja, quantas cabeças o pasto realmente aguenta sem degradar — é o principal indicador de manejo gerado pelo sistema. Para isso, utiliza-se a métrica de forragem total disponível (obtida pelo Google Earth Engine em toneladas de Matéria Seca por ano).

A fórmula aplicada é:

$$\text{Capacidade Ideal Total (UA)} = \frac{\text{Forragem Total Disponível (t MS/ano)}}{8,2}$$

**O Fator de Demanda (Divisor 8,2):**
A metodologia do Lapig não utiliza todo o pasto disponível no cálculo para o consumo. O divisor de **8,2 t MS/UA/ano** atua como um fator de proteção essencial. 

Um animal consome em média 2,5% do seu peso vivo diariamente. O valor de 8,2 representa o **dobro** desse consumo animal estimado. Essa margem de folga é adotada porque **assume-se que 50% da biomassa é invariavelmente perdida devido ao pisoteio do gado**. Ao garantir que metade da matéria seca permaneça intocada, o sistema assegura tanto o desempenho nutricional adequado do animal quanto a preservação e rebrota sustentável do pasto.

Para encontrar a meta de manejo por hectare, aplica-se:

$$\text{Capacidade Ideal (UA/ha)} = \frac{\text{Capacidade Ideal Total (UA)}}{\text{Área da Pastagem (ha)}}$$