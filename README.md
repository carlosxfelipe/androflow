# AndroFlow

Um motor em Python de testes de interface Android dirigidos por YAML, usando `uv` e ADB. Inspirado na simplicidade e na sintaxe declarativa do [Maestro](https://maestro.mobile.dev/). Opera exclusivamente através do binário nativo `adb` do computador, sem exigir a instalação de daemons em segundo plano ou APKs auxiliares dentro do dispositivo.

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
    timeout: 5000
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

Para ver recursos avançados (rolagem, gestos `swipe`, repetição `repeat`, busca por `regex: true`, foco automático, transliteração de acentos, `eraseText` e `hideKeyboard`), execute o segundo fluxo:

```bash
uv run androflow test flows/settings_advanced.yaml
```

> **Atenção ao idioma do dispositivo:** Como os fluxos de demonstração interagem com o app nativo de Configurações do Android, atente-se ao idioma configurado no aparelho:
>
> - `flows/settings_search.yaml`: requer o emulador/dispositivo em **inglês** (`en-US`).
> - `flows/settings_advanced.yaml`: requer o emulador/dispositivo em **português do Brasil** (`pt-BR`).

Se houver mais de um dispositivo, informe o serial:

```bash
uv run androflow --serial emulator-5554 test flows/settings_search.yaml
```

## Documentação e Guias

- [Sintaxe AndroFlow vs. Maestro](docs/maestro_vs_androflow.md): comparativo detalhado da sintaxe, vantagens de legibilidade e motivos das decisões de design.
- [Boas Práticas para Testar Apps React Native](docs/react_native.md): guia completo sobre `testID`, _view flattening_, foco de campos, virtualização de listas e execução com Metro vs. Release.

## Comandos implementados

- `launchApp`: inicia o app via `monkey` usando `appId` (suporta `stopApp: true/false` e `clearState: true/false`).
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
