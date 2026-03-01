# 📱 Guia Completo dos Aplicativos Telegram

> **Autor**: Compilado da documentação oficial do Telegram  
> **Última atualização**: Fevereiro 2026  
> **Objetivo**: Referência completa sobre todos os aplicativos e código fonte do Telegram

---

## 📑 Índice

1. [Visão Geral](#visão-geral)
2. [Apps Mobile Oficiais](#apps-mobile-oficiais)
3. [Apps Desktop Oficiais](#apps-desktop-oficiais)
4. [Apps Web Oficiais](#apps-web-oficiais)
5. [TDLib - Telegram Database Library](#tdlib---telegram-database-library)
6. [Apps Não Oficiais](#apps-não-oficiais)
7. [Código Fonte (Open Source)](#código-fonte-open-source)
8. [Bug Bounty Program](#bug-bounty-program)
9. [Links de Download](#links-de-download)

---

## 🌐 Visão Geral

Os aplicativos do Telegram são **open source** e suportam **builds reproduzíveis**. Isso significa que qualquer pessoa pode:

- ✅ Verificar que o app baixado foi compilado com o mesmo código publicado
- ✅ Auditar a implementação de criptografia end-to-end
- ✅ Criar seus próprios clientes personalizados
- ✅ Contribuir com melhorias

---

## 📱 Apps Mobile Oficiais

### Telegram para Android

| Informação | Detalhe |
|------------|---------|
| **Download** | [Google Play](https://telegram.org/dl/android) |
| **APK Direto** | [telegram.org/dl/android/apk](https://telegram.org/dl/android/apk) |
| **Código Fonte** | [github.com/DrKLO/Telegram](https://github.com/DrKLO/Telegram) |
| **Licença** | GNU GPL v. 2 ou posterior |
| **Linguagem** | Java/Kotlin |

#### Recursos do Android
- Notificações push nativas
- Temas personalizáveis
- Suporte a múltiplas contas
- Chats secretos com timer
- Chamadas de voz e vídeo
- Mini Apps
- Telegram Premium

---

### Telegram para iOS (iPhone/iPad)

| Informação | Detalhe |
|------------|---------|
| **Download** | [App Store](https://telegram.org/dl/ios) |
| **Código Fonte** | [github.com/TelegramMessenger/Telegram-iOS](https://github.com/TelegramMessenger/Telegram-iOS) |
| **Licença** | GNU GPL v. 2 ou posterior |
| **Linguagem** | Swift/Objective-C |

#### Recursos do iOS
- Integração com Siri
- Widgets para tela inicial
- Suporte a iPad multitarefa
- Notificações interativas
- Continuidade com macOS
- Face ID / Touch ID

---

### Telegram X para Android

| Informação | Detalhe |
|------------|---------|
| **Download** | [Google Play](https://play.google.com/store/apps/details?id=org.thunderdog.challegram) |
| **Código Fonte** | [github.com/TGX-Android/Telegram-X](https://github.com/TGX-Android/Telegram-X) |
| **Licença** | GPL v. 3.0 |
| **Base** | TDLib |

#### Características do Telegram X
- Cliente alternativo experimental
- Interface mais fluida
- Baseado em TDLib
- Animações melhoradas
- Consumo de bateria otimizado

---

## 💻 Apps Desktop Oficiais

### Telegram Desktop (Windows/Mac/Linux)

| Informação | Detalhe |
|------------|---------|
| **Download** | [desktop.telegram.org](https://desktop.telegram.org/) |
| **Código Fonte** | [github.com/telegramdesktop/tdesktop](https://github.com/telegramdesktop/tdesktop) |
| **Licença** | GNU GPL v. 3 |
| **Framework** | Qt |
| **Linguagem** | C++ |

#### Sistemas Suportados
- Windows 7 ou superior
- macOS 10.12 ou superior
- Linux (Ubuntu, Fedora, etc.)

#### Recursos do Desktop
- Sincronização completa com mobile
- Atalhos de teclado
- Múltiplas janelas de chat
- Pastas de chat
- Temas e personalização
- Proxy SOCKS5/MTProto

---

### Telegram para macOS (Nativo)

| Informação | Detalhe |
|------------|---------|
| **Download** | [macos.telegram.org](https://macos.telegram.org) |
| **Código Fonte** | [github.com/overtake/TelegramSwift](https://github.com/overtake/TelegramSwift) |
| **Licença** | GNU GPL v. 2 |
| **Linguagem** | Swift |

#### Diferenças do macOS Nativo
- Otimizado para Apple Silicon (M1/M2/M3)
- Integração profunda com macOS
- Spotlight Search
- Menu bar widget
- Share extensions
- Handoff com iOS

---

## 🌐 Apps Web Oficiais

### Telegram WebK

| Informação | Detalhe |
|------------|---------|
| **Acesso** | [web.telegram.org/k](https://web.telegram.org/k) |
| **Código Fonte** | [github.com/morethanwords/tweb](https://github.com/morethanwords/tweb) |
| **Licença** | GNU GPL v. 3 |
| **Linguagem** | TypeScript |

#### Características
- Interface moderna
- Suporte a stickers animados
- Chamadas de voz
- Temas escuro/claro
- PWA (Progressive Web App)

---

### Telegram WebA

| Informação | Detalhe |
|------------|---------|
| **Acesso** | [web.telegram.org/a](https://web.telegram.org/a) |
| **Código Fonte** | [github.com/Ajaxy/telegram-tt](https://github.com/Ajaxy/telegram-tt) |
| **Licença** | GNU GPL v. 3 |
| **Linguagem** | TypeScript/React |

#### Características
- Performance otimizada
- Suporte mobile responsivo
- Animações fluidas
- Threads e tópicos

---

### Telegram React (Legacy)

| Informação | Detalhe |
|------------|---------|
| **Código Fonte** | [github.com/evgeny-nadymov/telegram-react](https://github.com/evgeny-nadymov/telegram-react) |
| **Licença** | GNU GPL v. 3 |
| **Framework** | React.js |

---

### Webogram (Legacy)

| Informação | Detalhe |
|------------|---------|
| **Código Fonte** | [github.com/zhukov/webogram](https://github.com/zhukov/webogram) |
| **Licença** | GNU GPL v. 3 |
| **Framework** | AngularJS |

> ⚠️ Este é o cliente web legado, substituído por WebK e WebA.

---

## 📚 TDLib - Telegram Database Library

### O que é?

**TDLib** é uma biblioteca multiplataforma para criar clientes Telegram personalizados. É a base oficial recomendada para desenvolver novos apps.

| Informação | Detalhe |
|------------|---------|
| **Código Fonte** | [github.com/tdlib/td](https://github.com/tdlib/td) |
| **Documentação** | [core.telegram.org/tdlib](https://core.telegram.org/tdlib) |
| **Licença** | Boost 1.0 |
| **Linguagem** | C++ |

### Características

- ✅ Gerencia toda comunicação com API do Telegram
- ✅ Criptografia automática
- ✅ Armazenamento local de dados
- ✅ Sincronização de mensagens
- ✅ Suporte a todas as funcionalidades do Telegram
- ✅ Multiplataforma (Android, iOS, Windows, macOS, Linux, Web)

### Linguagens Suportadas

| Linguagem | Binding |
|-----------|---------|
| C/C++ | Nativo |
| Java | JNI |
| Swift | Wrapper |
| Python | pytdlib, python-telegram |
| Go | tdlib-go |
| Node.js | tdl, tdlib-native |
| Rust | rust-tdlib |
| PHP | MadelineProto |
| .NET | TDLib.NET |

### Instalação

```bash
# Clone o repositório
git clone --recursive https://github.com/tdlib/td.git
cd td

# Criar diretório de build
mkdir build && cd build

# Configurar com CMake
cmake -DCMAKE_BUILD_TYPE=Release ..

# Compilar
cmake --build . --target install
```

### Exemplo Básico (Python)

```python
from telegram.client import Telegram

tg = Telegram(
    api_id='seu_api_id',
    api_hash='seu_api_hash',
    phone='+5511999999999',
    database_encryption_key='sua_chave_secreta'
)

tg.login()

# Enviar mensagem
result = tg.send_message(
    chat_id=123456789,
    text='Olá do TDLib!'
)
```

---

## 🔧 Apps Não Oficiais

### Unigram (Windows)

| Informação | Detalhe |
|------------|---------|
| **Download** | Microsoft Store |
| **Código Fonte** | [github.com/UnigramDev/Unigram](https://github.com/UnigramDev/Unigram) |
| **Licença** | GNU GPL v. 3 ou posterior |
| **Base** | TDLib |
| **Framework** | UWP (.NET) |

#### Recursos
- Otimizado para Windows 10/11
- Interface Fluent Design
- Windows Hello
- Notificações nativas
- Timeline integration

---

### Telegram CLI (Linux)

| Informação | Detalhe |
|------------|---------|
| **Código Fonte** | [github.com/vysheng/tg](https://github.com/vysheng/tg) |
| **Licença** | GNU GPL v. 2 |
| **Linguagem** | C |

#### Uso
```bash
# Instalar dependências
sudo apt install libreadline-dev libconfig-dev libssl-dev lua5.2 liblua5.2-dev libevent-dev libjansson-dev libpython-dev make

# Compilar
./configure
make

# Executar
bin/telegram-cli -k tg-server.pub
```

#### Comandos Básicos
```
msg <peer> <text>       # Enviar mensagem
contact_list            # Listar contatos
dialog_list             # Listar conversas
send_photo <peer> <file> # Enviar foto
```

---

### MadelineProto (PHP)

| Informação | Detalhe |
|------------|---------|
| **Código Fonte** | [github.com/danog/MadelineProto](https://github.com/danog/MadelineProto) |
| **Licença** | GNU AGPL v. 3 |
| **Linguagem** | PHP |
| **Protocolo** | MTProto |

#### Instalação
```bash
composer require danog/madelineproto
```

#### Exemplo Básico
```php
<?php
use danog\MadelineProto\API;

$MadelineProto = new API('session.madeline');
$MadelineProto->start();

// Enviar mensagem
$MadelineProto->messages->sendMessage([
    'peer' => '@username',
    'message' => 'Olá!'
]);

// Obter dialogs
$dialogs = $MadelineProto->getDialogs();
```

#### Recursos
- ✅ Cliente MTProto completo em PHP
- ✅ Suporte a userbot e bot
- ✅ Download/upload de arquivos grandes
- ✅ Chamadas de voz
- ✅ Secret chats
- ✅ Proxy

---

## 💻 Código Fonte (Open Source)

### Repositórios Oficiais

| Aplicativo | GitHub | Licença |
|------------|--------|---------|
| TDLib | [tdlib/td](https://github.com/tdlib/td) | Boost 1.0 |
| Android | [DrKLO/Telegram](https://github.com/DrKLO/Telegram) | GPL v2+ |
| iOS | [TelegramMessenger/Telegram-iOS](https://github.com/TelegramMessenger/Telegram-iOS) | GPL v2+ |
| macOS | [overtake/TelegramSwift](https://github.com/overtake/TelegramSwift) | GPL v2 |
| Desktop | [telegramdesktop/tdesktop](https://github.com/telegramdesktop/tdesktop) | GPL v3 |
| WebK | [morethanwords/tweb](https://github.com/morethanwords/tweb) | GPL v3 |
| WebA | [Ajaxy/telegram-tt](https://github.com/Ajaxy/telegram-tt) | GPL v3 |
| Telegram X | [TGX-Android/Telegram-X](https://github.com/TGX-Android/Telegram-X) | GPL v3 |
| Windows Phone | [evgeny-nadymov/telegram-wp](https://github.com/evgeny-nadymov/telegram-wp) | GPL v2+ |

### Builds Reproduzíveis

O Telegram suporta **reproducible builds**, permitindo verificar que:

1. O app na Play Store/App Store é exatamente o mesmo código do GitHub
2. Não há código malicioso adicionado
3. A criptografia é implementada corretamente

**Documentação**: [core.telegram.org/reproducible-builds](https://core.telegram.org/reproducible-builds)

---

## 🐛 Bug Bounty Program

O Telegram oferece recompensas para pesquisadores de segurança que encontrarem vulnerabilidades.

### Escopo

- Aplicativos oficiais
- Código fonte publicado
- Protocolo MTProto
- Implementação de criptografia

### Recompensas

| Severidade | Recompensa |
|------------|------------|
| Crítica | $100.000+ |
| Alta | $5.000 - $50.000 |
| Média | $500 - $5.000 |
| Baixa | $100 - $500 |

### Como Participar

1. Encontre uma vulnerabilidade
2. Não divulgue publicamente
3. Reporte via [core.telegram.org/bug-bounty](https://core.telegram.org/bug-bounty)
4. Aguarde análise e resposta
5. Receba recompensa se válido

---

## 📥 Links de Download

### Mobile

| Plataforma | Link Direto |
|------------|-------------|
| Android (Play Store) | [telegram.org/dl/android](https://telegram.org/dl/android) |
| Android (APK) | [telegram.org/dl/android/apk](https://telegram.org/dl/android/apk) |
| iOS | [telegram.org/dl/ios](https://telegram.org/dl/ios) |

### Desktop

| Plataforma | Link Direto |
|------------|-------------|
| Windows/Mac/Linux | [desktop.telegram.org](https://desktop.telegram.org/) |
| macOS Nativo | [macos.telegram.org](https://macos.telegram.org) |

### Web

| Versão | Link Direto |
|--------|-------------|
| WebK | [web.telegram.org/k](https://web.telegram.org/k) |
| WebA | [web.telegram.org/a](https://web.telegram.org/a) |

### CLI

| Plataforma | Link |
|------------|------|
| Linux CLI | [telegram.org/dl/cli](https://telegram.org/dl/cli) |

---

## 🛠️ Criando Seu Próprio Cliente

### Opção 1: Usando TDLib (Recomendado)

```python
# Exemplo com Python usando TDLib
from ctypes import *

# Carregar TDLib
tdjson = cdll.LoadLibrary("libtdjson.so")

# Criar cliente
client_id = tdjson.td_create_client_id()

# Enviar request
request = '{"@type":"getMe"}'
tdjson.td_send(client_id, request.encode('utf-8'))

# Receber resposta
result = tdjson.td_receive(1.0)
print(result.decode('utf-8'))
```

### Opção 2: Usando MTProto Diretamente

```python
# Exemplo com Telethon
from telethon import TelegramClient

api_id = 12345
api_hash = "seu_api_hash"

client = TelegramClient('session', api_id, api_hash)

async def main():
    await client.start()
    me = await client.get_me()
    print(f"Conectado como {me.username}")

client.loop.run_until_complete(main())
```

### Opção 3: Fork de Cliente Existente

1. Faça fork do repositório desejado
2. Clone localmente
3. Faça suas modificações
4. Compile seguindo instruções do README
5. Publique respeitando a licença GPL

---

## 📋 Comparação de Clientes

| Cliente | Plataforma | Base | Linguagem | Recursos |
|---------|------------|------|-----------|----------|
| Oficial Android | Android | MTProto | Java/Kotlin | ⭐⭐⭐⭐⭐ |
| Oficial iOS | iOS | MTProto | Swift | ⭐⭐⭐⭐⭐ |
| Desktop | Win/Mac/Linux | MTProto | C++/Qt | ⭐⭐⭐⭐⭐ |
| macOS Nativo | macOS | MTProto | Swift | ⭐⭐⭐⭐⭐ |
| WebK | Web | MTProto | TypeScript | ⭐⭐⭐⭐ |
| WebA | Web | MTProto | React | ⭐⭐⭐⭐ |
| Telegram X | Android | TDLib | Java | ⭐⭐⭐⭐ |
| Unigram | Windows | TDLib | C#/.NET | ⭐⭐⭐⭐ |
| MadelineProto | PHP | MTProto | PHP | ⭐⭐⭐⭐ |
| Telethon | Python | MTProto | Python | ⭐⭐⭐⭐ |
| Pyrogram | Python | MTProto | Python | ⭐⭐⭐⭐ |

---

## 🔒 Segurança

### Criptografia

- **MTProto 2.0**: Protocolo proprietário do Telegram
- **End-to-End**: Chats secretos usam E2E
- **Verificação**: Código fonte auditável

### Autenticação

- **2FA**: Senha adicional
- **Session Management**: Controle de sessões ativas
- **Login Codes**: Códigos via SMS/Telegram

### Privacidade

- **Passcode Lock**: Bloqueio por senha/biometria
- **Auto-Delete**: Mensagens autodestrutivas
- **Secret Chats**: Criptografia E2E sem servidor

---

> 📌 **Este guia é uma referência rápida. Sempre consulte a [documentação oficial](https://telegram.org/apps) para informações mais detalhadas e atualizadas.**
