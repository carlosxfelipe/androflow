# Boas Práticas para Testar Apps React Native com AndroFlow

Este guia reúne conceitos, recomendações de código e boas práticas para criar testes de interface ponta a ponta (E2E) estáveis em aplicações **React Native (Android)** usando o **AndroFlow**.

---

## 1. Como o AndroFlow interage com o React Native

O React Native renderiza componentes nativos na plataforma Android (ex.: `ReactTextView`, `ReactViewGroup`, `ReactEditText`). O AndroFlow consulta a árvore de acessibilidade nativa via `adb shell uiautomator dump`.

Portanto:

- O AndroFlow não precisa de drivers especiais, Appium ou bibliotecas injetadas no JavaScript.
- Tudo o que estiver exposto na hierarquia de acessibilidade nativa do Android pode ser localizado e validado pelo AndroFlow.

---

## 2. Preparando os Componentes React Native

### 2.1 Identificadores estáveis com `testID` (Recomendado)

No Android, o React Native mapeia a propriedade `testID` para o atributo `resource-id` da view nativa:

```tsx
// React Native
<TouchableOpacity testID="btn_entrar" onPress={handleLogin}>
  <Text>Entrar</Text>
</TouchableOpacity>
```

No AndroFlow, use o seletor `resourceId` ou `id` (a correspondência por sufixo funciona automaticamente):

```yaml
# AndroFlow YAML
- tapOn:
    resourceId: "btn_entrar"
```

> **Dica de Nomenclatura:** Adote um padrão consistente para seus `testID`s, como `tipo_descricao` (ex.: `btn_salvar`, `input_email`, `txt_saldo`, `card_perfil`).

---

### 2.2 Cuidado com _View Flattening_ (`collapsable={false}`)

O React Native aplica uma otimização no Android chamada _view flattening_: tags `<View>` sem plano de fundo, bordas ou ouvintes de toque podem ser mescladas ou descartadas da árvore nativa para economizar memória.

Se você colocar um `testID` em uma `<View>` estrutural e o AndroFlow não conseguir encontrá-la:

1. Adicione `collapsable={false}`:
   ```tsx
   <View testID="container_produtos" collapsable={false}>
     {/* itens */}
   </View>
   ```
2. Ou marque o container como elemento de acessibilidade:
   ```tsx
   <View testID="container_produtos" accessible={true}>
     {/* itens */}
   </View>
   ```

---

### 2.3 Rótulos de acessibilidade com `accessibilityLabel`

Se o seu aplicativo já implementa diretrizes de acessibilidade:

```tsx
<Pressable
  accessibilityLabel="Fechar modal de confirmação"
  accessibilityRole="button"
  onPress={onClose}
>
  <Icon name="close" />
</Pressable>
```

No Android, `accessibilityLabel` vira `content-desc`. No AndroFlow, use `contentDesc`:

```yaml
- tapOn:
    contentDesc: "Fechar modal de confirmação"
```

---

### 2.4 Textos em tela (`<Text>`)

Elementos de texto direto podem ser selecionados tanto pelo conteúdo exato quanto por substring (`contains: true`):

```tsx
<Text style={styles.title}>Bem-vindo de volta!</Text>
```

```yaml
- assertVisible: "Bem-vindo de volta!"

# Ou com correspondência parcial:
- assertVisible:
    text: "Bem-vindo"
    contains: true
```

> **Atenção:** Evite aninhamentos complexos de `<Text>` com interpolações fragmentadas se pretender buscar pelo texto completo, pois dependendo da versão do React Native eles podem ser quebrados em nós adjacentes.
>
> **Caracteres Não-Quebráveis (`&nbsp;`):** Textos gerados com entidades como `&nbsp;` contêm o caractere Unicode `\u00a0` (espaço não-quebrável). Uma busca exata por `"Welcome to Expo"` falhará porque o espaço ASCII difere de `\u00a0`. Nesses casos, prefira `testID`, use correspondência parcial (`contains: true`) ou expressão regular:
>
> ```yaml
> - assertVisible:
>     text: "Welcome to"
>     contains: true
> ```

---

### 2.5 Expo Router e Abas Nativas (`NativeTabs` / `contentDesc`)

Em aplicações Expo utilizando o **Expo Router** com abas nativas (`expo-router/native-tabs` ou `<NativeTabs.Trigger>`):

- O Android renderiza os botões da barra inferior (`BottomNavigation`) atribuindo o nome da aba ao atributo de acessibilidade nativo `content-desc`, e **não** como texto puro (`text`).
- Portanto, para alternar entre abas, utilize o seletor `contentDesc`:

```yaml
# Correto para Expo Router / NativeTabs:
- tapOn:
    contentDesc: "Explore"

- tapOn:
    contentDesc: "Home"
```

---

## 3. Escrita de Fluxos YAML no AndroFlow

### 3.1 Identificador do pacote (`appId`) e Expo Go vs Standalone

Certifique-se de que o `appId` no cabeçalho do arquivo YAML corresponda exatamente ao `applicationId` definido no arquivo `android/app/build.gradle` (ou `app.json` no Expo):

```yaml
appId: ${APP_ID:-host.exp.exponent}
---
```

#### Dicas importantes para projetos Expo:

1. **Configuração de package no `app.json`:**
   Projetos criados com `create-expo-app` frequentemente vêm sem a propriedade `package` explícita em `android`. Para builds de produção, EAS ou prebuild, defina em `app.json`:

   ```json
   {
     "expo": {
       "android": {
         "package": "com.suaempresa.seuapp"
       }
     }
   }
   ```

2. **Diferença entre Expo Go e Standalone APK:**
   - **No Expo Go:** O pacote nativo no Android é sempre `host.exp.exponent`. O comando nativo `monkey` acionado por `launchApp` abre o menu/launcher de projetos do Expo Go. Durante o desenvolvimento ativo com Metro, se o app já estiver em tela, inicie o fluxo diretamente com `wakeUp` e asserções sem chamar `launchApp`, ou utilize deep links com `- openLink: "exp://..."`.
   - **Em Standalone APK / Dev Client:** O comando `- launchApp` inicia diretamente a tela principal do seu aplicativo.

3. **Variáveis de ambiente dinâmicas:**
   Parametrize o fluxo para alternar entre Expo Go e Standalone APK sem precisar alterar o código YAML:
   ```yaml
   appId: ${APP_ID:-host.exp.exponent}
   ```
   E para executar contra um APK standalone:
   ```bash
   androflow test flows/meu_fluxo.yaml -e APP_ID="com.suaempresa.seuapp"
   ```

---

### 3.2 Campos de texto e digitação (`inputText`)

O AndroFlow permite preencher campos de texto de duas formas:

#### Forma recomendada (Foco automático com seletor):

Você pode passar o seletor diretamente para o `inputText`. O AndroFlow localiza o elemento, toca no centro dele para abrir o cursor/teclado e digita em seguida:

```yaml
- inputText:
    id: "input_email"
    text: "carlos@exemplo.com"
```

#### Forma simples (campo já focado):

Caso o campo já esteja focado por uma etapa anterior:

```yaml
- inputText: "carlos@exemplo.com"
```

> **Acentos e Transliteração:** O comando nativo `adb shell input text` aceita apenas caracteres ASCII. Para preencher dados com acentos (ex.: nomes e endereços brasileiros) sem quebrar o teste, use a flag `transliterate: true`:
>
> ```yaml
> - inputText:
>     id: "input_nome"
>     text: "João da Silva"
>     transliterate: true # Converte automaticamente para "Joao da Silva"
> ```

---

### 3.3 Tratando o carregamento inicial (Debug vs Release)

No modo de desenvolvimento (Debug com Metro bundler), o aplicativo pode demorar alguns segundos para baixar e compilar o bundle JavaScript durante a inicialização.

- Configure um `waitFor` com tempo suficiente para aguardar o primeiro elemento da tela inicial:

```yaml
- waitFor:
    resourceId: "screen_home"
    timeout: 15000 # ou timeout: "15s"
```

- Em builds **Release** ou **Staging** (APKs pré-compilados com `./gradlew assembleRelease`), a inicialização é praticamente instantânea, tornando os testes mais rápidos e estáveis.

---

### 3.4 Fechando o teclado virtual (`hideKeyboard`) e desobstrução de tela

Em telas com campos de texto e elementos logo abaixo (botões "Continuar", mensagens de preview dinâmico ou contadores), o teclado virtual do Android pode sobrepor o elemento ou comprimir o container (`y2 <= y1`).

Quando isso ocorre, a hierarquia XML do Android considera o elemento abaixo como não-visível (`visible=false`), fazendo com que asserções ou toques falhem mesmo que o componente esteja montado no React.

**Boas práticas:**

1. Sempre execute `- hideKeyboard` logo após digitar dados em um formulário antes de tentar validar textos ou tocar em botões inferiores.
2. Certifique-se de envolver formulários dentro de um `<ScrollView>` para garantir rolagem suave e evitar que o teclado corte a visualização dos campos.

```yaml
- tapOn:
    id: "input_nome"
- inputText:
    text: "Carlos Felipe"
    transliterate: true
- hideKeyboard
- sleep: "300ms"
- assertVisible: "Digitado: Carlos Felipe"
- tapOn:
    id: "btn_salvar"
```

---

## 4. Listas e Virtualização (`FlatList`, `SectionList`, `ScrollView`)

O React Native utiliza virtualização de listas para performance. Componentes que estão fora da área visível da tela **não existem no DOM/árvore XML** do Android até serem rolados para a viewport.

### Boas práticas:

1. **Dados de mock controlados:** Em cenários de teste, ordene ou limite a lista de teste para que os itens que você precisa validar estejam inicialmente visíveis na viewport.
2. **Rolagem:** Caso precise alcançar elementos abaixo da dobra, utilize os comandos nativos `- scroll` (rolagem padrão para baixo) ou `- swipe: { direction: UP }` para navegar na lista.

---

## 5. Animações Contínuas e `idle state`

O comando `uiautomator dump` do ADB aguarda uma janela de inatividade (_idle state_) para capturar a árvore de elementos.

- Se o app tiver loaders em loop infinito (como `ActivityIndicator` nativo, animações infinitas de `react-native-reanimated` ou Lottie rodando sem parar), o dump pode sofrer timeout com o erro `could not get idle state`.
- **Recomendação:** Em ambiente de testes, garanta que loaders tenham condições de término ou desative animações infinitas via variável de ambiente / flag de teste (`__DEV__` ou `IS_TESTING`).

---

## 6. Exemplo Completo

### Código no React Native (`LoginScreen.tsx`):

```tsx
import React, { useState } from "react";
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  StyleSheet,
} from "react-native";

export function LoginScreen() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  return (
    <View testID="screen_login" collapsable={false} style={styles.container}>
      <Text style={styles.title}>Acessar Conta</Text>

      <TextInput
        testID="input_email"
        placeholder="E-mail"
        value={email}
        onChangeText={setEmail}
        style={styles.input}
      />

      <TextInput
        testID="input_password"
        placeholder="Senha"
        secureTextEntry
        value={password}
        onChangeText={setPassword}
        style={styles.input}
      />

      <TouchableOpacity
        testID="btn_submit"
        accessibilityLabel="Entrar no aplicativo"
        style={styles.button}
        onPress={() => console.log("Login")}
      >
        <Text style={styles.buttonText}>Entrar</Text>
      </TouchableOpacity>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, padding: 24, justifyContent: "center" },
  title: { fontSize: 24, fontWeight: "bold", marginBottom: 20 },
  input: {
    borderWidth: 1,
    borderColor: "#ccc",
    padding: 12,
    borderRadius: 8,
    marginBottom: 12,
  },
  button: {
    backgroundColor: "#0066cc",
    padding: 16,
    borderRadius: 8,
    alignItems: "center",
  },
  buttonText: { color: "#fff", fontWeight: "bold" },
});
```

### Fluxo no AndroFlow (`flows/login_react_native.yaml`):

```yaml
appId: com.meuapp
---
- launchApp
- waitFor:
    id: "screen_login"
    timeout: 10000 # ou timeout: "10s"

# Foco automático e digitação em um único comando:
- inputText:
    id: "input_email"
    text: "carlos@teste.com"

- inputText:
    id: "input_password"
    text: "senhaSegura123"

- hideKeyboard

- tapOn:
    id: "btn_submit"

- takeScreenshot: "apos-login.png"
```

---

## 7. Diagnóstico e Depuração

Quando um elemento não for encontrado pelo AndroFlow durante o teste:

1. **Inspecione os artefatos de falha:** O AndroFlow salva automaticamente em `artifacts/`:
   - `artifacts/<fluxo>-falha-<etapa>.png`: captura exata da tela no momento do erro.
   - `artifacts/<fluxo>-falha-<etapa>.xml`: cópia integral da árvore XML retornada pelo Android.
2. Abra o arquivo `.xml` gerado e busque pelo seu identificador ou texto para verificar:
   - Se o `resource-id` foi exposto como esperado.
   - Se a view sofreu colapso (_view flattening_).
   - Se o texto está em maiúsculas/minúsculas diferentes (ex.: `text-transform: uppercase` do CSS).
