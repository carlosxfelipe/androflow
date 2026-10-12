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

---

## 3. Escrita de Fluxos YAML no AndroFlow

### 3.1 Identificador do pacote (`appId`)

Certifique-se de que o `appId` no cabeçalho do arquivo YAML corresponda exatamente ao `applicationId` definido no arquivo `android/app/build.gradle` (ou `app.json` no Expo):

```yaml
appId: com.suaempresa.seuapp
---
- launchApp
```

---

### 3.2 Campos de texto: sempre focar antes de digitar

O comando `inputText` do AndroFlow envia eventos de texto via `adb shell input text` para o campo que já detém o foco no sistema operacional. No React Native, é **obrigatório** tocar no campo antes de chamar `inputText`:

```yaml
# 1. Toca no campo para abrir o foco / teclado
- tapOn:
    resourceId: "input_email"

# 2. Digita o texto
- inputText: "carlos@exemplo.com"
```

> **Limitação de Caracteres:** O `adb shell input text` aceita apenas caracteres da tabela ASCII básica (sem acentos nem emojis). Utilize strings simples em testes automatizados (ex.: `senha123`, `teste_qa`).

---

### 3.3 Tratando o carregamento inicial (Debug vs Release)

No modo de desenvolvimento (Debug com Metro bundler), o aplicativo pode demorar alguns segundos para baixar e compilar o bundle JavaScript durante a inicialização.

- Configure um `waitFor` com tempo suficiente para aguardar o primeiro elemento da tela inicial:

```yaml
- launchApp
- waitFor:
    resourceId: "screen_home"
    timeout: 15
```

- Em builds **Release** ou **Staging** (APKs pré-compilados com `./gradlew assembleRelease`), a inicialização é praticamente instantânea, tornando os testes mais rápidos e estáveis.

---

### 3.4 Fechando o teclado virtual

Em telas com botões inferiores (ex.: "Continuar" ou "Entrar"), o teclado virtual do Android pode sobrepor o elemento clicável. Use o comando `back` para recolher o teclado antes de tocar no botão:

```yaml
- tapOn:
    resourceId: "input_senha"
- inputText: "segredo123"
- back # Fecha o teclado virtual
- tapOn:
    resourceId: "btn_login"
```

---

## 4. Listas e Virtualização (`FlatList`, `SectionList`, `ScrollView`)

O React Native utiliza virtualização de listas para performance. Componentes que estão fora da área visível da tela **não existem no DOM/árvore XML** do Android até serem rolados para a viewport.

### Boas práticas:

1. **Dados de mock controlados:** Em cenários de teste, ordene ou limite a lista de teste para que os itens que você precisa validar estejam inicialmente visíveis na viewport.
2. **Rolagem:** Caso precise alcançar elementos abaixo da dobra, utilize coordenadas ou ajuste a exibição para caber na densidade do emulador.

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
    resourceId: "screen_login"
    timeout: 10

- tapOn:
    resourceId: "input_email"
- inputText: "carlos@teste.com"

- tapOn:
    resourceId: "input_password"
- inputText: "senhaSegura123"

- back # Fecha o teclado virtual se estiver cobrindo a tela

- tapOn:
    resourceId: "btn_submit"

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
