# AndroFlow

Um motor em Python de testes de interface Android dirigidos por YAML, usando `uv` e ADB. Inspirado na simplicidade e na sintaxe declarativa do [Maestro](https://maestro.mobile.dev/). Opera exclusivamente através do binário nativo `adb` do computador, sem exigir a instalação de daemons em segundo plano ou APKs auxiliares dentro do dispositivo.

> **Nota:** O AndroFlow é um projeto independente focado exclusivamente em Android via ADB, sem vínculo com o Maestro ou com a mobile.dev. A localização de elementos usa a hierarquia XML acessível do Android; telas que não expõem elementos acessíveis podem exigir seletores por coordenadas ou outra estratégia.

## Requisitos

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- Android SDK Platform Tools (`adb`)
- Um emulador iniciado pelo Android Studio, ou dispositivo Android com depuração USB autorizada

## Instalação

### Como ferramenta global via CLI (Recomendado)

Você não precisa clonar este repositório nem escrever código Python para testar seus aplicativos. O AndroFlow funciona como uma ferramenta de linha de comando global (similar ao Maestro):

```bash
uv tool install git+https://github.com/carlosxfelipe/androflow.git
```

> **Dica de PATH:** Se o comando `androflow` não for reconhecido logo após a instalação, execute `uv tool update-shell` para configurar seu terminal.

Para atualizar o AndroFlow no futuro com as últimas novidades do repositório:

```bash
uv tool upgrade androflow
```

---

### Desenvolvimento local (Contribuidores)

Para contribuir com o desenvolvimento do motor do AndroFlow ou executar os testes unitários da biblioteca:

```bash
git clone https://github.com/carlosxfelipe/androflow.git
cd androflow
uv sync
```

---

## Como usar no seu projeto (Passo a Passo)

O AndroFlow é **100% orientado a arquivos YAML declarativos via terminal**. Você **não precisa** escrever código Python nem utilizar scripts como `main.py`.

### 1. Estrutura de pastas sugerida

Na raiz do seu aplicativo (seja React Native, Flutter, Android nativo ou uma pasta dedicada a testes E2E), basta criar uma pasta para armazenar seus fluxos de teste:

```text
meu-projeto/
├── flows/
│   ├── login.yaml
│   └── busca.yaml
├── .env                  # (opcional) variáveis como senhas, URLs, etc.
└── artifacts/            # (criada automaticamente pelo AndroFlow para prints, relatórios e vídeos)
```

> **Nota:** Não é necessário criar nenhum arquivo `.py`. O AndroFlow lê diretamente os arquivos `.yaml`.

### 2. Crie seu primeiro fluxo de teste

Crie por exemplo o arquivo `flows/meu_teste.yaml`:

```yaml
appId: com.android.settings
---
- launchApp
- assertVisible: "Network & internet"
- tapOn: "Search Settings"
```

_(Se seu emulador/dispositivo estiver em português, adapte o texto para `"Rede e internet"` e `"Pesquisar nas configurações"`)._

### 3. Conecte o emulador e execute

Com o emulador ou celular conectado via depuração USB:

```bash
# 1. Confirme que o dispositivo aparece como 'device'
androflow devices

# 2. Execute o fluxo
androflow test flows/meu_teste.yaml
```

---

## Exemplos de fluxo (Inclusos neste repositório)

Caso você tenha clonado o repositório do AndroFlow para explorar os exemplos nativos:

- **Busca simples:**

  ```bash
  androflow test flows/settings_search.yaml
  ```

  _(Requer emulador em inglês `en-US`)._

- **Recursos avançados** (rolagem, gestos `swipe`, repetição `repeat`, regex, foco automático, transliteração, `eraseText` e `hideKeyboard`):

  ```bash
  androflow test flows/settings_advanced.yaml
  ```

  _(Requer emulador em português `pt-BR`)._

- **Variáveis de ambiente, relatórios e gravação de vídeo:**
  ```bash
  androflow test flows/features_showcase.yaml --report --record
  ```

Se houver mais de um dispositivo conectado, informe o serial com `--serial`:

```bash
androflow --serial emulator-5554 test flows/settings_search.yaml
```

## Documentação e Guias

- [Sintaxe AndroFlow vs. Maestro](docs/maestro_vs_androflow.md): comparativo detalhado da sintaxe, vantagens de legibilidade e motivos das decisões de design.
- [Boas Práticas para Testar Apps React Native](docs/react_native.md): guia completo sobre `testID`, _view flattening_, foco de campos, virtualização de listas e execução com Metro vs. Release.

## Comandos implementados

- `launchApp`: inicia o app via `monkey` usando `appId` (suporta `stopApp: true/false`, `clearState: true/false`, `permissions: [...]` e `wakeUp: true`).
- `stopApp`: força a parada do app via `am force-stop`.
- `tapOn`: toca em um elemento localizado por `text`, `resourceId`, `contentDesc` ou `id`; também aceita `point: [x, y]`, `point: "x, y"` ou percentual `point: "50%, 50%"`.
- `inputText`: digita texto no campo focado ou recebe um seletor para tocar e focar automaticamente (`{id: "campo", text: "..."}`). Suporta `transliterate: true` para normalizar acentos.
- `eraseText`: apaga texto do campo focado (padrão 50 caracteres; ou `- eraseText: 10`).
- `pressKey`: aciona teclas de sistema como `Enter`, `Back`, `Home`, `Tab`, `VolumeUp`, `VolumeDown`.
- `hideKeyboard`: fecha o teclado virtual se estiver aberto.
- `scroll`: realiza rolagem na tela (padrão para baixo: `DOWN`).
- `swipe`: gesto de deslize customizado por direção (`{direction: UP}`) ou coordenadas/percentuais (`{start: "50%,80%", end: "50%,20%"}`).
- `openLink`: abre URLs ou deep links via `android.intent.action.VIEW`.
- `assertVisible`: falha se o elemento não estiver presente/visível na hierarquia XML.
- `assertNotVisible`: aguarda até `timeout` (padrão em milissegundos, ex.: `5000`, ou com unidades como `"5s"`) o elemento sumir; falha se continuar visível.
- `waitFor`: aguarda um elemento até `timeout` (padrão em milissegundos, ex.: `5000`, ou com unidades como `"5s"`) de forma concisa.
- `repeat`: repete um bloco de comandos (`{times: 3, commands: [...]}`).
- `takeScreenshot`: salva uma captura de tela. Caminhos relativos são salvos em `artifacts/` (`.png` é adicionado se faltar).
- `back`: aciona o botão Voltar do Android.
- `sleep`: pausa a execução em milissegundos (`2000`, `500`) ou com unidades explícitas (`"2s"`, `"500ms"`).
- `scrollUntilVisible`: rola a tela até que o elemento fique visível (ex.: `- scrollUntilVisible: "Excluir"` ou `{id: "btn", direction: DOWN, maxScrolls: 10}`).
- `grantPermissions`: concede permissões de tempo de execução via `pm grant` (ex.: `- grantPermissions: POST_NOTIFICATIONS` ou lista `- grantPermissions: [CAMERA, ACCESS_FINE_LOCATION]`).
- `revokePermissions`: revoga permissões de tempo de execução via `pm revoke`.
- `wakeUp`: acorda a tela do dispositivo (`KEYCODE_WAKEUP`) e desbloqueia a tela (`wm dismiss-keyguard`).
- `dismissSystemDialogs`: fecha diálogos e popups do sistema Android via broadcast (`CLOSE_SYSTEM_DIALOGS`).
- `disableAnimations`: desativa animações do Android via ADB para acelerar testes e eliminar flakiness. Suporta também `disableAnimations: true` no cabeçalho YAML e flag `--disable-animations` na CLI.
- `enableAnimations`: restaura as animações do Android para a escala padrão (1.0).

### Seletores

`resourceId` pode ser o ID completo (`com.exemplo.app:id/email`) ou o sufixo (`email`). Também aceita a forma concisa `id:`.
`text` e `contentDesc` usam correspondência exata por padrão.

- Use `contains: true` para correspondência parcial.
- Use `regex: true` para correspondência por expressão regular.

```yaml
- assertVisible:
    id: "com.exemplo.app:id/welcome_title"

- tapOn:
    contentDesc: "Abrir menu"

- waitFor:
    text: "Carregando"
    timeout: 5000

- swipe:
    direction: DOWN

- pressKey: Enter

# Digitação com seletor embutido (foco automático) e transliteração de acentos:
- inputText:
    id: "search_input"
    text: "Cartão de Crédito"
    transliterate: true
```

Chaves desconhecidas no seletor (ex.: `txt:`) geram erro de validação antecipada.

### Validação e falhas

- O fluxo inteiro é validado antes de executar a primeira etapa: comandos desconhecidos, valores ausentes (`- inputText` sem texto) e seletores inválidos são reportados com o número da etapa.
- A execução para na primeira falha e o resumo mostra etapas `ok`, `falha` e `puladas`.
- Ao falhar, são salvos `artifacts/<fluxo>-falha-<etapa>.png` e `.xml` (hierarquia da tela) para depuração.

## Variáveis de Ambiente e Interpolação (${VAR})

O AndroFlow suporta interpolação dinâmica de variáveis de ambiente em qualquer campo do fluxo YAML (inclusive seletores, textos digitados, URLs e cabeçalho `appId`):

```yaml
appId: ${APP_PKG:-com.exemplo.app}
env:
  BASE_URL: https://staging.exemplo.com
---
- launchApp
- inputText:
    id: "email"
    text: "${USER_EMAIL}"
- inputText:
    id: "senha"
    text: "${USER_PASS:123456}"
- openLink: "${BASE_URL}/boas-vindas"
```

### Sintaxe de Variáveis:

- `${VAR}`: substitui pelo valor exato da variável. Se não existir, falha com erro antecipado.
- `${VAR:-padrao}` ou `${VAR:padrao}`: usa `padrao` como fallback se a variável não estiver definida.

### Hierarquia de Resolução:

1. Valores passados via CLI `--env` / `-e CHAVE=VALOR` (maior precedência).
2. Variáveis definidas no cabeçalho do YAML (`env:`).
3. Arquivo `.env` na raiz do projeto (carregado automaticamente).
4. Variáveis de ambiente do sistema operacional (`os.environ`).

Exemplo via linha de comando:

```bash
uv run androflow test flow.yaml -e USER_EMAIL="qa@empresa.com" -e USER_PASS="segredo"
```

## Estabilidade e Performance no ADB

O AndroFlow inclui otimizações nativas de ADB para eliminar _flakiness_ e acelerar a execução:

- **Desativação de animações:** O erro `could not get idle state` do Android ocorre com frequência em telas com spinners ou transições contínuas. Desativar animações acelera os testes em até 3x:
  ```bash
  uv run androflow test flow.yaml --disable-animations
  ```
  Ou diretamente no cabeçalho do fluxo:
  ```yaml
  appId: com.exemplo.app
  disableAnimations: true
  ---
  ```
- **Concessão automática de permissões:** Evite popups intrusivos concedendo permissões em tempo de execução via `pm grant`:
  ```yaml
  appId: com.exemplo.app
  permissions:
    - POST_NOTIFICATIONS
    - ACCESS_FINE_LOCATION
  ---
  - launchApp:
      clearState: true
  ```
- **Wake Up & Unlock:** Garanta que a tela do emulador/dispositivo esteja ligada e desbloqueada antes ou durante os testes:
  ```yaml
  - wakeUp
  # Ou diretamente no launchApp:
  - launchApp:
      wakeUp: true
  ```
- **Fechamento de Diálogos do Sistema:** Feche alertas e popups do sistema operacional com `- dismissSystemDialogs`.

## Observabilidade e CI/CD

O AndroFlow oferece recursos nativos de observabilidade para monitoramento e depuração visual de testes, especialmente em pipelines de integração contínua (GitHub Actions, GitLab CI):

### 1. Gravação de Vídeo (`--record` / `-r`)

Grava a tela do dispositivo Android nativamente via `adb shell screenrecord` e salva automaticamente o arquivo `.mp4` em `artifacts/`:

```bash
uv run androflow test flow.yaml --record
```

Ou ative diretamente no cabeçalho do fluxo:

```yaml
appId: com.exemplo.app
record: true
---
```

### 2. Relatórios de Teste (HTML e JUnit XML)

Gere relatórios completos com um único comando ou parâmetros específicos:

```bash
# Gera automaticamente tanto o HTML quanto o JUnit XML na pasta artifacts/:
uv run androflow test flow.yaml --report

# Ou defina caminhos customizados:
uv run androflow test flow.yaml --report-junit test-results/junit.xml --report-html artifacts/index.html
```

- **JUnit XML (`--report-junit`):** Padrão da indústria para CI/CD. No GitHub Actions ou GitLab CI, os resultados de cada etapa aparecem na aba nativa de _Checks/Tests_.
- **HTML Report Interativo (`--report-html`):** Relatório visual moderno e autocontido (sem dependências externas de rede ou CDN), contendo:
  - Resumo de métricas (status geral, total de etapas, aprovadas, falhas, puladas e duração total).
  - Linha do tempo com duração em milissegundos de cada comando executado.
  - Reprodutor de vídeo embutido (caso a execução tenha sido gravada com `--record`).
  - Galeria com capturas de tela e detalhes colapsáveis em caso de falha.

## Limitações conhecidas

- A hierarquia XML depende de o app expor componentes acessíveis no Android (jogos e Canvas desenham diretamente na tela sem nós de acessibilidade).
- O comando nativo do Android (`adb shell input text`) suporta apenas caracteres ASCII. O AndroFlow oferece `transliterate: true` (no comando ou no cabeçalho do fluxo) para converter automaticamente caracteres acentuados (ex.: `"Cartão"` para `"Cartao"`). Emojis e alfabetos não-latinos não são suportados nativamente pelo ADB sem um APK auxiliar.

## Desenvolvimento

```bash
uv run pytest
uv run ruff format
uv run ruff check
uv run androflow --help
```

## Licença

Distribuído sob a licença [GNU General Public License v3.0 (GPLv3)](LICENSE). Consulte o arquivo `LICENSE` para obter mais detalhes.
