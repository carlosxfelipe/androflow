# Comparativo: Sintaxe AndroFlow vs. Maestro

O **AndroFlow** foi concebido sob inspiração direta da sintaxe declarativa do [Maestro](https://maestro.mobile.dev/). No entanto, durante o desenvolvimento, optou-se deliberadamente por **simplificar e lapidar a sintaxe**, eliminando verbosidades e decisões históricas do Maestro que tornavam os arquivos YAML mais burocráticos do que precisavam ser.

Este documento detalha as diferenças entre as duas abordagens e as motivações de design por trás da sintaxe do AndroFlow.

---

## 1. Tabela Comparativa Rápida

| Ação / Recurso             | AndroFlow (Enxuto)                                                           | Maestro (Legado)                                                                                                       | Vantagem do AndroFlow                                                         |
| :------------------------- | :--------------------------------------------------------------------------- | :--------------------------------------------------------------------------------------------------------------------- | :---------------------------------------------------------------------------- |
| **Aguardar elemento**      | `- waitFor: { id: "btn", timeout: 5 }`                                       | `- extendedWaitUntil:`<br>&nbsp;&nbsp;`visible:`<br>&nbsp;&nbsp;&nbsp;&nbsp;`id: "btn"`<br>&nbsp;&nbsp;`timeout: 5000` | Menos níveis de indentação; comando direto e autoexplicativo.                 |
| **Pausar fluxo**           | `- sleep: 2` (ou `"500ms"`)                                                  | `- sleep: 2000`                                                                                                        | Segundos são a unidade natural do pensamento humano.                          |
| **Timeout de espera**      | `timeout: 5`                                                                 | `timeout: 5000`                                                                                                        | Conciso; elimina repetições de zeros (`000`).                                 |
| **Busca parcial de texto** | `text: "Tema", contains: true`                                               | `text: ".*Tema.*"`                                                                                                     | Não exige conhecimento de regex nem escape de caracteres.                     |
| **Busca por regex**        | `text: "ID \\d+", regex: true`                                               | `text: "ID \\d+"`                                                                                                      | Intenção explícita; evita falso-positivos de regex acidental.                 |
| **Seletor de ID**          | `id:` ou `resourceId:`                                                       | Apenas `id:`                                                                                                           | Flexibilidade entre forma curta (`id`) e nome técnico Android (`resourceId`). |
| **Digitação em campo**     | `- inputText:`<br>&nbsp;&nbsp;`id: "email"`<br>&nbsp;&nbsp;`text: "a@b.com"` | `- tapOn:`<br>&nbsp;&nbsp;`id: "email"`<br>`- inputText: "a@b.com"`                                                    | Foco automático integrado; corta o número de etapas pela metade.              |
| **Toque por coordenadas**  | `point: [100, 200]` ou `"50%,50%"`                                           | `point: "50%,50%"`                                                                                                     | Aceita lista de inteiros ou strings percentuais relativas à tela.             |

---

## 2. As Diferenças em Detalhes e os "Porquês"

### 2.1 `waitFor` vs. `extendedWaitUntil`

#### No Maestro:

```yaml
- extendedWaitUntil:
    visible:
      id: "search_box"
    timeout: 5000
```

#### No AndroFlow:

```yaml
- waitFor:
    id: "search_box"
    timeout: 5
```

#### Por que o AndroFlow é melhor:

1. **Redução de indentação:** O Maestro exige **3 níveis de aninhamento** apenas para esperar que um componente apareça na tela. No AndroFlow, basta **1 nível**.
2. **Nome sem débitos históricos:** O nome `extendedWaitUntil` surgiu no Maestro porque inicialmente a ferramenta possuía apenas esperas implícitas curtas e, posteriormente, adicionou uma espera "estendida". O AndroFlow não carrega esse histórico: o comando chama-se simplesmente `waitFor`, como em qualquer biblioteca moderna de testes.
3. **Elemento ausente:** Para aguardar um elemento sumir da tela, o AndroFlow possui o comando declarativo `- assertNotVisible: { id: "loading", timeout: 10 }`, sem necessitar aninhar `notVisible:` dentro de `extendedWaitUntil:`.

---

### 2.2 Segundos Humanos vs. Milissegundos Computacionais

#### No Maestro:

```yaml
- sleep: 3000

- extendedWaitUntil:
    visible: "Confirmado"
    timeout: 15000
```

#### No AndroFlow:

```yaml
- sleep: 3

- waitFor:
    text: "Confirmado"
    timeout: 15
```

#### Por que o AndroFlow é melhor:

- Ao projetar testes de interface de usuário, humanos raciocinam em **segundos** (_"aguarde 3 segundos"_, _"timeout de 15 segundos"_).
- Ter que digitar `3000` ou `15000` em cada etapa gera poluição visual desnecessária e aumenta as chances de erros de digitação (ex.: `sleep: 300` achando que são 3 segundos, quando seriam apenas 300 milissegundos).
- **Precisão fracionada quando necessária:** Se você realmente precisar de esperas sub-segundo, o AndroFlow aceita floats (`sleep: 0.5`) ou strings explícitas com unidade (`sleep: "500ms"`).

---

### 2.3 Correspondência Parcial: `contains: true` vs. Regex

#### No Maestro:

Para verificar se um elemento contém parte de um texto no Maestro, utiliza-se expressão regular inline:

```yaml
- assertVisible: ".*Bem-vindo.*"
```

Se o texto contiver caracteres especiais de regex (como parênteses, colchetes, pontos ou cifras), é obrigatório escapá-los manualmente:

```yaml
- assertVisible: ".*Total: R\\$ 50,00 \\(com desconto\\).*"
```

#### No AndroFlow:

```yaml
- assertVisible:
    text: "Total: R$ 50,00 (com desconto)"
    contains: true
```

#### Por que o AndroFlow é melhor:

- **Legibilidade e acessibilidade:** Qualquer membro do time (seja QA, produto ou desenvolvedor) consegue ler e escrever o fluxo sem precisar ser especialista em regex.
- **Segurança contra quebras acidentais:** Strings com moedas, versões (`v1.0.0`) ou notas explicativas entre parênteses são tratadas literalmente, sem que o parser interprete caracteres como operadores de regex.
- **Regex quando você realmente quer regex:** Quando o caso de uso exigir um padrão dinâmico (ex.: código de verificação numérico), o AndroFlow oferece a flag explícita `regex: true`:
  ```yaml
  - assertVisible:
      text: "Código: \\d{6}"
      regex: true
  ```

---

### 2.4 Seletores: `id` e `resourceId`

O Maestro utiliza exclusivamente `id:` porque precisa mapear tanto o `accessibilityIdentifier` do iOS quanto o `resource-id` do Android.

No AndroFlow:

- `id: "login_button"` é aceito para brevidade e compatibilidade.
- `resourceId: "com.exemplo:id/login_button"` ou `resourceId: "login_button"` também é aceito para clareza nativa do ecossistema Android.

---

### 2.5 Digitação com Foco Automático e Transliteração

#### No Maestro:

Preencher formulários no Maestro exige sempre dois comandos para cada campo (primeiro tocar para dar foco, depois digitar às cegas):

```yaml
- tapOn:
    id: "input_nome"
- inputText: "João"
```

#### No AndroFlow:

O AndroFlow permite embutir o seletor diretamente no comando `inputText`. Ele localiza o elemento, toca no centro para abrir o cursor/teclado e digita em seguida:

```yaml
- inputText:
    id: "input_nome"
    text: "João"
    transliterate: true # Converte automaticamente acentos para "Joao"
```

#### Por que o AndroFlow é melhor:

1. **Metade das etapas em formulários:** Telas de cadastro e login eliminam comandos `tapOn` repetitivos.
2. **Elimina digitação no vazio:** O campo é focado e garantido antes do disparo do texto.
3. **Resiliência a acentos:** `transliterate: true` contorna limitações do ADB nativo sem quebrar testes em português.

---

## 3. Comandos Úteis do Maestro Incorporados ao AndroFlow

Embora tenhamos descartado as convenções burocráticas, mantivemos e implementamos no AndroFlow comandos essenciais e de alta utilidade:

| Comando        | Exemplo                                                                         | Finalidade                                                                 |
| :------------- | :------------------------------------------------------------------------------ | :------------------------------------------------------------------------- |
| `pressKey`     | `- pressKey: Enter`<br>`- pressKey: Back`                                       | Aciona teclas físicas/virtuais do sistema Android.                         |
| `eraseText`    | `- eraseText`<br>`- eraseText: 10`                                              | Apaga caracteres do campo em foco (50 por padrão ou quantidade informada). |
| `hideKeyboard` | `- hideKeyboard`                                                                | Fecha o teclado virtual do Android de forma limpa.                         |
| `scroll`       | `- scroll`                                                                      | Realiza rolagem vertical para baixo na tela.                               |
| `swipe`        | `- swipe: { direction: UP }`<br>`- swipe: { start: "50%,80%", end: "50%,20%" }` | Executa gestos de deslize direcionais ou entre coordenadas.                |
| `openLink`     | `- openLink: "https://meuapp.com/promo"`                                        | Abre URLs ou deep links diretamente no dispositivo.                        |
| `stopApp`      | `- stopApp`                                                                     | Encerra a execução do app informado ou do cabeçalho.                       |
| `clearState`   | `- launchApp: { clearState: true }`                                             | Limpa o cache e os dados do app (`pm clear`) antes de iniciar.             |
| `repeat`       | `- repeat: { times: 3, commands: [...] }`                                       | Repete um conjunto de passos sem duplicação de YAML.                       |

---

## 4. Comparação Lado a Lado de um Fluxo Real

Veja o mesmo cenário de busca em configurações escrito nas duas abordagens:

### No Maestro (Burocrático):

```yaml
appId: com.android.settings
---
- launchApp
- extendedWaitUntil:
    visible:
      id: "search_bar"
    timeout: 5000
- tapOn:
    id: "search_bar"
- inputText: "display"
- extendedWaitUntil:
    visible:
      text: ".*Display size.*"
    timeout: 5000
- tapOn:
    text: ".*Display size.*"
- sleep: 2000
```

### No AndroFlow (Enxuto e Elegante):

```yaml
appId: com.android.settings
---
- launchApp
- waitFor:
    id: "search_bar"
    timeout: 5
- inputText:
    id: "search_bar"
    text: "display"
- waitFor:
    text: "Display size"
    contains: true
    timeout: 5
- tapOn: "Display size"
- sleep: 2
```

---

## 5. Resumo da Filosofia do AndroFlow

1. **Simplicidade sobre burocracia:** YAML deve ser fácil de ler por humanos, sem aninhamentos desnecessários.
2. **Sem mágicas silenciosas:** O tempo é em segundos. Se precisar de frações, informe expressamente (`0.5` ou `"500ms"`).
3. **Foco e performance:** Focado exclusivamente em Android via ADB, sem intermediários pesados, mantendo execução rápida e direta.
