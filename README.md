# AndroFlow

Um motor em Python de testes de interface Android dirigidos por YAML, usando `uv` e ADB. Inspirado na simplicidade e na sintaxe declarativa do [Maestro](https://maestro.mobile.dev/).

> **Nota:** O AndroFlow é um projeto independente focado exclusivamente em Android via ADB, sem vínculo com o Maestro ou com a mobile.dev. A localização de elementos usa a hierarquia XML acessível do Android; telas que não expõem elementos acessíveis podem exigir seletores por coordenadas ou outra estratégia.

## Requisitos

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- Android SDK Platform Tools (`adb`)
- Um emulador iniciado pelo Android Studio, ou dispositivo Android com depuração USB autorizada

## Instalação

```bash
uv sync
uv run androflow devices
```

Confirme que o emulador aparece como `device` (e não `offline` ou `unauthorized`).

## Exemplo de fluxo

Veja o fluxo funcional em `flows/settings_search.yaml`:

```yaml
appId: com.android.settings
---
- launchApp
- assertVisible: "Network & internet"
- tapOn: "Search Settings"
- waitFor:
    resourceId: "open_search_view_edit_text"
    timeout: 5
- inputText: "dark theme"
- assertVisible: "Standard dark theme"
- takeScreenshot: "settings-busca.png"
- tapOn: "Dark theme"
- assertVisible: "Appearance"
- back
- back
```

Execute:

```bash
uv run androflow test flows/settings_search.yaml
```

Se houver mais de um dispositivo, informe o serial:

```bash
uv run androflow --serial emulator-5554 test flows/settings_search.yaml
```

## Documentação e Guias

- [Boas Práticas para Testar Apps React Native](docs/react_native.md): guia completo sobre `testID`, *view flattening*, foco de campos, virtualização de listas e execução com Metro vs. Release.

## Comandos implementados

- `launchApp`: inicia o app via `monkey` usando `appId`.
- `tapOn`: toca em um elemento localizado por `text`, `resourceId`, `contentDesc` ou `id`; também aceita `point: [x, y]`.
- `inputText`: digita texto no campo atualmente focado.
- `assertVisible`: falha se o elemento não estiver presente/visível na hierarquia XML.
- `assertNotVisible`: aguarda até `timeout` segundos o elemento sumir; falha se continuar visível.
- `waitFor`: aguarda um elemento até `timeout` segundos.
- `takeScreenshot`: salva uma captura de tela. Caminhos relativos são salvos em `artifacts/` (`.png` é adicionado se faltar).
- `back`: aciona o botão Voltar.
- `sleep`: pausa por um número de segundos.

### Seletores

`resourceId` pode ser o ID completo (`com.exemplo.app:id/email`) ou o sufixo (`email`).
`text` e `contentDesc` usam correspondência exata por padrão. Use `contains: true` para correspondência parcial.

```yaml
- assertVisible:
    resourceId: "com.exemplo.app:id/welcome_title"

- tapOn:
    contentDesc: "Abrir menu"

- waitFor:
    text: "Carregando"
    timeout: 15
```

Chaves desconhecidas no seletor (ex.: `txt:`) geram erro.

### Validação e falhas

- O fluxo inteiro é validado antes de executar a primeira etapa: comandos desconhecidos, valores ausentes (`- inputText` sem texto) e seletores inválidos são reportados com o número da etapa.
- A execução para na primeira falha e o resumo mostra etapas `ok`, `falha` e `puladas`.
- Ao falhar, são salvos `artifacts/<fluxo>-falha-<etapa>.png` e `.xml` (hierarquia da tela) para depuração.

## Limitações conhecidas

- A hierarquia XML depende de o app expor componentes acessíveis.
- `inputText` envia texto ao campo que já estiver focado; não localiza nem foca automaticamente um campo.
- `inputText` só suporta caracteres ASCII (limitação do `adb shell input text`): acentos e emojis geram erro.
- `launchApp` usa `appId` e `monkey`; para apps com fluxos de inicialização especiais, talvez seja necessário adaptar o comando.
- Gestos, rolagem avançada, execução de subfluxos, fixtures, paralelismo, gravação/reprodução e relatórios HTML ainda não estão implementados.
- Este protótipo não usa Appium nem instala um serviço de instrumentação no app.

## Desenvolvimento

```bash
uv run pytest
uv run ruff format
uv run ruff check
uv run androflow --help
```
