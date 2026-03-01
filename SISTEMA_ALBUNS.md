# 🎨 Sistema de Álbuns e Progresso em Tempo Real

## 🎉 Novas Funcionalidades Implementadas

### 1. 📸 Modo de Álbum: "Copiar Origem"
O sistema agora **detecta e preserva álbuns originais** do Telegram!

**Como funciona:**
- Detecta álbuns usando `grouped_id` do Telegram
- Copia álbuns exatamente como estão na origem
- Se origem tem álbum de 5 fotos → Destino terá álbum de 5 fotos
- Se origem tem álbum de 2 vídeos → Destino terá álbum de 2 vídeos
- Mantém a legenda original (apenas na primeira mídia do álbum)

**Vantagens:**
✅ Cópia exata da estrutura original
✅ Preserva organização dos álbuns
✅ Legendas mantidas corretamente

### 2. 🎨 Modo de Álbum: "Manual"
Permite criar álbuns personalizados com tamanho configurável (1-10 mídias)

**Como funciona:**
- Você escolhe quantas mídias por álbum (1 a 10)
- O sistema agrupa automaticamente as mídias
- Exemplo: Se escolher 5, todas as mídias serão enviadas em grupos de 5

**Vantagens:**
✅ Controle total sobre o tamanho dos álbuns
✅ Organização customizada
✅ Reduz número de mensagens enviadas

### 3. 📊 Barra de Progresso em Tempo Real

**Antes:**
```
CONTRIBUIÇÃO MEMBROS:   0%|                    | 0/84 [00:29<?, ? mídia/s]
```
❌ Travava, não atualizava em tempo real

**Depois:**
```
CONTRIBUIÇÃO MEMBROS:  45%|████████▏         | 38/84 [02:15<02:45, 3.5 mídia/s]
```
✅ Atualiza instantaneamente após cada mídia/álbum copiado
✅ Mostra tempo estimado
✅ Mostra velocidade de cópia

## 🚀 Como Usar

### Opção 1: Copiar Exatamente da Origem (Recomendado)

```
[?] Como deseja agrupar as mídias?:
 ❯ 📸 Copiar exatamente como está na origem (mantém álbuns originais)
   🎨 Criar álbuns personalizados (escolher tamanho)
```

**Resultado:** 
- Se a origem tem 100 mídias sendo:
  - 50 mídias individuais
  - 30 mídias em álbuns de 5
  - 20 mídias em álbuns de 2

O destino terá **exatamente a mesma estrutura**!

### Opção 2: Álbuns Personalizados

```
[?] Como deseja agrupar as mídias?:
   📸 Copiar exatamente como está na origem (mantém álbuns originais)
 ❯ 🎨 Criar álbuns personalizados (escolher tamanho)

[?] Quantas mídias por álbum? (1-10): 7
✅ Álbuns de 7 mídias
```

**Resultado:**
- Todas as mídias serão agrupadas em álbuns de 7
- Última mídia pode ter menos se sobrar resto

## 📋 Fluxo Completo de Clonagem

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

[?] Copiar LEGENDAS das mídias?: Yes

[?] Como deseja agrupar as mídias?:
 ❯ 📸 Copiar exatamente como está na origem
   🎨 Criar álbuns personalizados

✅ Mantendo estrutura de álbuns original

[?] Auditar destino? (verifica duplicatas, mais lento): No

⚠️ Será criado novo grupo: 'Meu Grupo Clone'

[?] Confirma?: Yes
[?] Salvar como Tarefa Rápida?: Yes

✅ Tarefa salva!

╭────────────────────────────────────────╮
│         🚀 CLONANDO GRUPO COM TÓPICOS  │
╰────────────────────────────────────────╯

   CONTRIBUIÇÃO MEMBROS:  45%|████▏| 38/84 [02:15<02:45, 3.5 mídia/s]
```

## 🎯 Exemplos Práticos

### Exemplo 1: Grupo de Fotos de Viagem
**Origem:**
- Álbum 1: 10 fotos da praia
- Álbum 2: 5 fotos do hotel
- 3 fotos individuais
- Álbum 3: 8 fotos do restaurante

**Modo: Copiar Origem**
✅ Destino terá EXATAMENTE os mesmos álbuns

**Modo: Manual (tamanho 6)**
- Álbum 1: 6 mídias
- Álbum 2: 6 mídias
- Álbum 3: 6 mídias
- Álbum 4: 6 mídias
- Álbum 5: 2 mídias (resto)

### Exemplo 2: Canal de Vídeos
**Origem:** 100 vídeos individuais

**Modo: Copiar Origem**
✅ 100 vídeos individuais

**Modo: Manual (tamanho 10)**
✅ 10 álbuns de 10 vídeos cada

## ⚙️ Configurações Salvas

Todas as configurações são salvas na tarefa:
```json
{
  "lote_size": 10,
  "pausa_segundos": 15,
  "album_mode": "copy_origin",
  "album_size": 10,
  "copiar_legendas": true
}
```

Ao retomar a tarefa, as mesmas configurações serão usadas automaticamente!

## 🔧 Detalhes Técnicos

### Detecção de Álbuns
```python
# O Telegram agrupa mídias usando grouped_id
if hasattr(msg, 'grouped_id') and msg.grouped_id:
    # Esta mensagem faz parte de um álbum
    albuns_por_grupo[msg.grouped_id].append(msg)
```

### Envio de Álbuns
```python
# Enviar múltiplas mídias como álbum
files = [m.media for m in album_msgs]
caption = album_msgs[0].text  # Legenda na primeira

await client.send_file(
    destino,
    file=files,  # Lista de mídias
    caption=caption,
    reply_to=reply_to
)
```

### Atualização de Progresso
```python
# A barra atualiza IMEDIATAMENTE após cada envio
if pbar:
    pbar.update(len(album_msgs))  # Atualiza com quantas mídias foram enviadas
```

## 📊 Performance

**Antes (mídia por mídia):**
- 100 mídias = 100 requisições
- Tempo: ~10 minutos
- Barra: Travada

**Depois (modo álbum):**
- 100 mídias em álbuns de 10 = 10 requisições
- Tempo: ~2 minutos ⚡
- Barra: Tempo real 📊

## 🛡️ Tratamento de Erros

- ✅ Se um álbum falhar, todas as mídias daquele álbum são registradas
- ✅ FloodWait é tratado automaticamente
- ✅ Progresso é salvo após cada envio bem-sucedido
- ✅ Pode retomar de onde parou

## 💡 Dicas

1. **Para grupos organizados**: Use "Copiar Origem" para manter a estrutura original
2. **Para compactar**: Use "Álbuns Personalizados" com tamanho 10
3. **Para máxima compatibilidade**: Use mídia individual (tamanho 1)
4. **Legendas longas**: O Telegram só mostra legenda na primeira mídia do álbum

---

**Última atualização**: 2025-12-25  
**Versão**: 3.0.0 🎉
