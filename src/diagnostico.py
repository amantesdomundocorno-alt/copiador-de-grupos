# diagnostico.py
# Script para diagnosticar o grupo origem e ver quantas mídias realmente existem

import asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession

# COLE AQUI SUAS CREDENCIAIS (mesmo do settings.json)
API_ID = 23375960
API_HASH = "ab6d08a0109a6d1b654f614dcff23196"
PHONE = "+5521995122361"

# ID do grupo ORIGEM
GRUPO_ORIGEM_ID = 1598512044

# Último ID processado
ULTIMO_ID_COPIADO = 70930

async def diagnosticar_grupo():
    """Diagnóstico completo do grupo origem."""
    
    # Conecta usando a sessão salva
    session_path = f"contas/{''.join(c for c in PHONE if c.isalnum())}"
    client = TelegramClient(session_path, API_ID, API_HASH)
    
    await client.connect()
    
    if not await client.is_user_authorized():
        print("❌ Sessão expirada. Execute o programa principal primeiro.")
        return
    
    print("✅ Conectado com sucesso!\n")
    
    # Busca o grupo origem
    origem = await client.get_entity(GRUPO_ORIGEM_ID)
    print(f"📊 GRUPO ORIGEM: {origem.title}")
    print(f"🆔 ID: {origem.id}")
    print("="*60)
    
    # === ESTATÍSTICAS GERAIS ===
    print("\n📈 ESTATÍSTICAS GERAIS:")
    print("-"*60)
    
    # Conta total de mensagens
    print("⏳ Contando mensagens totais...")
    total_msgs = 0
    async for _ in client.iter_messages(origem, limit=None):
        total_msgs += 1
    print(f"   Total de mensagens: {total_msgs:,}")
    
    # Conta total de mídias
    print("⏳ Contando mídias totais...")
    total_midias = 0
    async for msg in client.iter_messages(origem, limit=None):
        if msg.media:
            total_midias += 1
    print(f"   Total de mídias: {total_midias:,}")
    
    # Percentual
    percentual = (total_midias / total_msgs * 100) if total_msgs > 0 else 0
    print(f"   Percentual de mídias: {percentual:.2f}%")
    
    # === ANÁLISE DO PROGRESSO ===
    print(f"\n🔍 ANÁLISE DO PROGRESSO (após ID {ULTIMO_ID_COPIADO}):")
    print("-"*60)
    
    # Conta mensagens APÓS o último ID processado
    print("⏳ Contando mensagens após o último ID processado...")
    msgs_apos = 0
    midias_apos = 0
    primeiro_id = None
    ultimo_id = None
    
    async for msg in client.iter_messages(origem, min_id=ULTIMO_ID_COPIADO, reverse=True, limit=None):
        msgs_apos += 1
        if msg.media:
            midias_apos += 1
            if primeiro_id is None:
                primeiro_id = msg.id
            ultimo_id = msg.id
    
    print(f"   Mensagens após ID {ULTIMO_ID_COPIADO}: {msgs_apos:,}")
    print(f"   Mídias após ID {ULTIMO_ID_COPIADO}: {midias_apos:,}")
    
    if midias_apos > 0:
        print(f"   Primeira mídia encontrada: ID {primeiro_id}")
        print(f"   Última mídia encontrada: ID {ultimo_id}")
    else:
        print("   ⚠️  NENHUMA MÍDIA ENCONTRADA após este ID!")
    
    # === ANÁLISE DE GAPS ===
    print(f"\n🕳️  ANÁLISE DE GAPS (Primeiras 20 mídias após ID {ULTIMO_ID_COPIADO}):")
    print("-"*60)
    
    ultimas_midias = []
    async for msg in client.iter_messages(origem, min_id=ULTIMO_ID_COPIADO, reverse=True, limit=None):
        if msg.media:
            ultimas_midias.append(msg.id)
            if len(ultimas_midias) >= 20:
                break
    
    if ultimas_midias:
        print(f"   IDs das próximas 20 mídias: {ultimas_midias}")
        
        # Calcula gaps
        for i in range(len(ultimas_midias) - 1):
            gap = ultimas_midias[i+1] - ultimas_midias[i]
            if gap > 100:
                print(f"   ⚠️  GAP GRANDE: {gap} mensagens entre ID {ultimas_midias[i]} e {ultimas_midias[i+1]}")
    else:
        print("   ⚠️  Nenhuma mídia encontrada para análise de gaps")
    
    # === RESUMO ===
    print("\n" + "="*60)
    print("📋 RESUMO:")
    print("="*60)
    print(f"✅ Mídias já copiadas: 28,391")
    print(f"📊 Total de mídias no grupo: {total_midias:,}")
    print(f"🔄 Mídias restantes: {max(0, total_midias - 28391):,}")
    
    if midias_apos == 0:
        print("\n⚠️  CONCLUSÃO: Você JÁ copiou TODAS as mídias disponíveis!")
        print("   O grupo pode ter 60.000 mensagens, mas apenas ~28.000 eram mídias.")
    else:
        print(f"\n✅ CONCLUSÃO: Ainda existem {midias_apos:,} mídias para copiar!")
        print("   O programa deveria continuar. Há um bug na lógica de iteração.")
    
    await client.disconnect()

if __name__ == "__main__":
    print("🔬 DIAGNÓSTICO DO GRUPO ORIGEM")
    print("="*60)
    print("⏳ Iniciando análise... (pode demorar alguns minutos)\n")
    
    try:
        asyncio.run(diagnosticar_grupo())
    except KeyboardInterrupt:
        print("\n\n⚠️  Diagnóstico interrompido pelo usuário.")
    except Exception as e:
        print(f"\n\n❌ Erro durante o diagnóstico: {e}")
        import traceback
        traceback.print_exc()