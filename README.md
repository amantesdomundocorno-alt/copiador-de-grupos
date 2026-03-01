# 📦 Copiador Indexador - Telegram

> Ferramenta profissional para clonar, indexar e gerenciar mídias entre grupos/canais Telegram.

![Python](https://img.shields.io/badge/Python-3.9+-blue.svg)
![Telethon](https://img.shields.io/badge/Telethon-1.28+-green.svg)
![License](https://img.shields.io/badge/License-Private-red.svg)

---

## 🎯 O que faz?

- **Cópia de Mídias:** Copia fotos, vídeos e arquivos entre grupos/canais
- **Modo Inteligente:** Usa auditoria para copiar apenas o que falta (evita duplicatas)
- **Suporte a Fóruns:** Organiza mídias em tópicos indexados automaticamente
- **Múltiplas Contas:** Gerencia várias contas Telegram
- **Resiliência:** Continua de onde parou após quedas de internet
- **Anti-Ban:** Rate limiting inteligente para evitar FloodWait

---

## 🚀 Instalação

### 1. Clone o repositório
```bash
git clone <seu-repositorio>
cd "CONTA - Copiador Indexador"
```

### 2. Instale as dependências
```bash
pip install -r requirements.txt
```

### 3. (Opcional) Configure variáveis de ambiente
```bash
cp .env.example .env
# Edite o arquivo .env com suas credenciais
```

### 4. Execute o programa
```bash
python main.py
```

---

## 📋 Requisitos

- **Python:** 3.9 ou superior
- **Dependências:** Ver `requirements.txt`
  - telethon
  - inquirer
  - colorama
  - tqdm
  - rich
  - pyfiglet
  - hachoir
  - pillow

---

## 🖥️ Funcionalidades

### Menu Principal
```
┌────────────────────────────────────────┐
│         COPIADOR INDEXADOR             │
├────────────────────────────────────────┤
│ 1. 🆕 Nova Tarefa de Cópia             │
│ 2. 📂 Executar Tarefa Salva            │
│ 3. 📝 Copiar Tópicos                   │
│ 4. 🔍 Auditoria de Grupos              │
│ 5. 📊 Estatísticas                     │
│ 6. 💾 Backup Manual                    │
│ 7. 👤 Gerenciar Contas                 │
│ 8. ⚙️ Configurações                    │
│ 9. 🚪 Sair                             │
└────────────────────────────────────────┘
```

### Modos de Cópia

| Modo | Descrição |
|------|-----------|
| **Inteligente** | Usa auditoria para copiar apenas mídias que faltam no destino |
| **Clássico** | Cópia rápida sem verificação de duplicatas |
| **Fórum** | Organiza mídias em tópicos numerados com índice |

---

## ⚙️ Configuração

### Arquivo `config.yaml`

Edite para personalizar comportamentos:

```yaml
retry:
  max_retries: 5        # Tentativas em caso de erro
  base_delay: 2.0       # Delay entre tentativas

network:
  connection_timeout: 60
  max_reconnect_attempts: 10

copy:
  batch_size_forum: 50  # Mídias por tópico
```

### Variáveis de Ambiente (`.env`)

```env
TELEGRAM_API_ID=12345678
TELEGRAM_API_HASH=abcdef0123456789
```

---

## 📁 Estrutura do Projeto

```
CONTA - Copiador Indexador/
├── main.py                 # Ponto de entrada
├── config.yaml            # Configurações
├── requirements.txt       # Dependências
├── .env.example          # Template de ambiente
│
├── src/                   # Código fonte
│   ├── config.py         # Configuração centralizada
│   ├── logger.py         # Sistema de logging
│   ├── database.py       # Gerenciador SQLite
│   ├── copiador.py       # Copiador clássico
│   ├── copiador_inteligente.py  # Copiador com auditoria
│   ├── auditoria.py      # Sistema de auditoria
│   ├── comparador.py     # Comparação de mídias
│   ├── interface.py      # Interface CLI
│   ├── dashboard.py      # Dashboard visual
│   ├── notifications.py  # Notificações Telegram
│   ├── network_resilience.py  # Anti-queda de internet
│   └── ...
│
├── dados/                # Dados do programa
│   ├── copiador.db      # Banco de dados SQLite
│   ├── backups/         # Backups automáticos
│   ├── logs/            # Arquivos de log
│   └── settings.json    # Configurações de contas
│
└── contas/              # Sessões Telegram
    └── *.session        # Arquivos de sessão
```

---

## 🛡️ Segurança

- **Rate Limiting:** Controle automático de velocidade para evitar ban
- **Checkpoints:** Progresso salvo automaticamente
- **Backups:** Backup automático do banco de dados (últimos 7 dias)
- **Logging:** Registro de todas as operações em arquivo

---

## ❓ FAQ - Problemas Comuns

### "FloodWaitError"
O Telegram está limitando sua conta. O programa aguarda automaticamente.
- **Solução:** Use modo "traditional" para pausas mais longas

### "Session expired"
Sua sessão Telegram expirou.
- **Solução:** Faça login novamente pelo menu de contas

### "Erro ao buscar grupos"
Você pode não ter mais acesso ao grupo.
- **Solução:** Verifique se ainda está no grupo

### Internet caiu durante cópia
O programa detecta automaticamente e:
1. Salva o progresso atual
2. Aguarda reconexão
3. Continua de onde parou

---

## 🔄 Atualizações

### v2.0.0 (Atual)
- ✅ Sistema anti-queda de internet
- ✅ Dashboard de progresso em tempo real
- ✅ Notificações Telegram
- ✅ Configuração centralizada
- ✅ Logging profissional
- ✅ Retry com backoff exponencial

### v1.0.0
- Release inicial

---

## 📝 Licença

Uso privado. Todos os direitos reservados.

---

## 🆘 Suporte

Para suporte ou dúvidas, entre em contato com o desenvolvedor.
