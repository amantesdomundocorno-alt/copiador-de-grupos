# ⚙️ Configuração de Pausas na Clonagem Completa

## 📋 Descrição

A funcionalidade de **Clonagem Completa** agora permite que você configure dinamicamente:

1. **Quantidade de mídias** a serem copiadas antes de pausar
2. **Tempo de pausa** em segundos entre cada lote

## 🎯 Como Usar

Ao selecionar a opção **"🔄 CLONAR GRUPO COMPLETO"** no menu principal, você será solicitado a configurar:

### 1️⃣ Quantas mídias copiar antes de pausar?
- **Padrão**: 10 mídias
- **Mínimo**: 1 mídia
- Digite o número desejado (ex: 5, 10, 20, 50)

### 2️⃣ Quantos segundos pausar entre lotes?
- **Padrão**: 15 segundos
- **Mínimo**: 0 segundos (sem pausa)
- Digite o número desejado (ex: 10, 15, 30, 60)

## 📊 Exemplos de Configuração

### Configuração Rápida (Arriscada)
```
Mídias por lote: 20
Pausa: 5 segundos
```
**Uso**: Ideal para contas com bom histórico e grupos pequenos

### Configuração Padrão (Recomendada)
```
Mídias por lote: 10
Pausa: 15 segundos
```
**Uso**: Balanceamento entre velocidade e segurança

### Configuração Segura (Grupos Grandes)
```
Mídias por lote: 5
Pausa: 30 segundos
```
**Uso**: Ideal para grupos com 100k+ mídias ou contas sensíveis

### Configuração Ultra-Segura
```
Mídias por lote: 3
Pausa: 60 segundos
```
**Uso**: Máxima proteção contra flood/ban do Telegram

## 💾 Salvamento de Configuração

- As configurações são **salvas automaticamente** junto com a tarefa
- Ao retomar uma tarefa salva, as mesmas configurações serão aplicadas
- Você pode criar diferentes tarefas com diferentes configurações

## ⚡ Dicas de Uso

1. **Contas Novas**: Use configurações mais conservadoras (menos mídias, mais pausa)
2. **Contas Antigas**: Pode usar configurações mais agressivas
3. **Horário de Pico**: Aumente as pausas durante horários de alta atividade
4. **Grupos Gigantes (500k+ mídias)**: Prefira lotes menores com pausas maiores

## 🎨 Screenshots do Fluxo

```
╭────────────────────────────────────────╮
│      🚀 CLONAR GRUPO COMPLETO          │
╰────────────────────────────────────────╯

ℹ️ Esta função irá:
ℹ️   1. Copiar APENAS fotos e vídeos
ℹ️   2. Pausar entre lotes (configurável)
ℹ️   3. Salvar progresso para retomada

[?] Quantas mídias copiar antes de pausar?: 10
[?] Quantos segundos pausar entre lotes?: 15

✅ Configurado: Pausar 15s a cada 10 mídias
```

## 🔧 Implementação Técnica

Os parâmetros são armazenados em:
- **task_config['lote_size']**: Quantidade de mídias por lote
- **task_config['pausa_segundos']**: Tempo de pausa entre lotes

E aplicados em:
- `ClonadorCompleto.lote_size`
- `ClonadorCompleto.pausa_segundos`

## 📝 Notas Importantes

- ⚠️ Pausas menores aumentam o risco de FloodWait do Telegram
- ⚠️ Lotes maiores são mais rápidos, mas menos seguros
- ✅ O sistema **SEMPRE salva o progresso**, então você pode parar/retomar a qualquer momento
- ✅ Mídias que falharem são registradas em `dados/midias_puladas.txt`

---

**Última atualização**: 2025-12-25
**Versão**: 2.0.0
