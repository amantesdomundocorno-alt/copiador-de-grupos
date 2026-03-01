"""
Utilidades de Gerenciamento de Grupos
- Desfixar todas as mensagens
- Limpar tópicos vazios
"""

import asyncio
from telethon import functions
from telethon.errors import FloodWaitError
from telethon.tl.types import Message

from src.interface import get_all_forum_topics
from src.estilo import (
    print_success, print_error, print_warning, print_info,
    print_section_header
)


async def desfixar_tudo(client, grupo):
    """
    Desfixa todas as mensagens fixadas de um grupo.
    
    Args:
        client: Cliente Telethon
        grupo: Entidade do grupo
    
    Returns:
        int: Quantidade de mensagens desfixadas
    """
    print_section_header("📌 Desfixar Todas as Mensagens")
    
    print_info(f"🔍 Verificando mensagens fixadas em '{grupo.title}'...")
    
    try:
        # Buscar mensagens fixadas usando o filtro correto
        from telethon.tl.types import InputMessagesFilterPinned
        
        mensagens_fixadas = []
        async for msg in client.iter_messages(grupo, filter=InputMessagesFilterPinned()):
            if msg:
                mensagens_fixadas.append(msg)
        
        if not mensagens_fixadas:
            print_success("✅ Nenhuma mensagem fixada encontrada!")
            return 0
        
        print_info(f"📊 Encontradas {len(mensagens_fixadas)} mensagem(ns) fixada(s)")
        
        # Mostrar mensagens
        print_info("\n📋 Mensagens fixadas:")
        for i, msg in enumerate(mensagens_fixadas, 1):
            texto_preview = msg.text[:50] if msg.text else "[Mídia]"
            print_info(f"   {i}. ID {msg.id}: {texto_preview}...")
        
        # Confirmar
        import inquirer
        confirmar = inquirer.prompt([
            inquirer.Confirm('confirmar',
                           message=f"Deseja desfixar todas as {len(mensagens_fixadas)} mensagens?",
                           default=True)
        ])
        
        if not confirmar or not confirmar['confirmar']:
            print_warning("Operação cancelada")
            return 0
        
        # Desfixar todas
        print_info("\n📌 Desfixando mensagens...")
        
        desfixadas = 0
        erros = 0
        
        for i, msg in enumerate(mensagens_fixadas, 1):
            try:
                await client.unpin_message(grupo, msg.id)
                print_success(f"   ✅ [{i}/{len(mensagens_fixadas)}] Mensagem {msg.id} desfixada")
                desfixadas += 1
                await asyncio.sleep(0.5)  # Evitar FloodWait
                
            except FloodWaitError as e:
                print_warning(f"   ⏳ FloodWait: aguardando {e.seconds}s...")
                await asyncio.sleep(e.seconds + 2)
                # Tentar novamente
                try:
                    await client.unpin_message(grupo, msg.id)
                    print_success(f"   ✅ [{i}/{len(mensagens_fixadas)}] Mensagem {msg.id} desfixada")
                    desfixadas += 1
                except Exception as e2:
                    print_error(f"   ❌ Erro ao desfixar {msg.id}: {e2}")
                    erros += 1
                    
            except Exception as e:
                print_error(f"   ❌ Erro ao desfixar {msg.id}: {e}")
                erros += 1
        
        print_success(f"\n✅ Processo concluído!")
        print_info(f"   📊 {desfixadas} desfixadas | {erros} erros")
        
        return desfixadas
        
    except Exception as e:
        print_error(f"Erro ao desfixar mensagens: {e}")
        return 0


async def limpar_topicos_vazios(client, forum):
    """
    Encontra e deleta tópicos vazios de um fórum.
    
    Um tópico é considerado vazio se:
    - Não tem mensagens (além da mensagem de criação)
    - Ou tem apenas a mensagem de criação do tópico
    
    Args:
        client: Cliente Telethon
        forum: Entidade do fórum
    
    Returns:
        int: Quantidade de tópicos deletados
    """
    print_section_header("🗑️ Limpar Tópicos Vazios")
    
    print_info(f"🔍 Analisando tópicos em '{forum.title}'...")
    
    try:
        # Buscar todos os tópicos
        topicos = await get_all_forum_topics(client, forum, force_refresh=True)
        
        if not topicos:
            print_warning("Nenhum tópico encontrado")
            return 0
        
        print_info(f"📊 Encontrados {len(topicos)} tópicos. Verificando conteúdo...")
        
        # Verificar quais estão vazios
        topicos_vazios = []
        
        for i, topico in enumerate(topicos, 1):
            # Ignorar tópico General (ID 1)
            if topico.id == 1:
                continue
            
            try:
                # Contar mensagens no tópico
                count = 0
                async for msg in client.iter_messages(forum, reply_to=topico.id, limit=5):
                    count += 1
                    # Se tiver pelo menos 1 mensagem (além da de criação), não é vazio
                    if count > 0:
                        break
                
                if count == 0:
                    topicos_vazios.append(topico)
                    print_info(f"   [{i}/{len(topicos)}] ❌ {topico.title} - VAZIO")
                else:
                    print(f"   [{i}/{len(topicos)}] ✅ {topico.title} - {count} msgs", end='\r')
                
            except Exception as e:
                print_warning(f"\n   ⚠️ Erro ao verificar {topico.title}: {e}")
        
        print()  # Nova linha após o loop
        
        if not topicos_vazios:
            print_success("\n✅ Nenhum tópico vazio encontrado!")
            return 0
        
        print_warning(f"\n📊 Encontrados {len(topicos_vazios)} tópico(s) vazio(s):")
        for t in topicos_vazios:
            print_info(f"   • {t.title} (ID: {t.id})")
        
        # Confirmar deleção
        import inquirer
        confirmar = inquirer.prompt([
            inquirer.Confirm('confirmar',
                           message=f"Deseja deletar todos os {len(topicos_vazios)} tópicos vazios?",
                           default=False)  # Padrão é NÃO (mais seguro)
        ])
        
        if not confirmar or not confirmar['confirmar']:
            print_warning("Operação cancelada")
            return 0
        
        # Deletar tópicos
        print_info("\n🗑️ Deletando tópicos vazios...")
        
        deletados = 0
        erros = 0
        
        for i, topico in enumerate(topicos_vazios, 1):
            try:
                await client(functions.channels.DeleteTopicHistoryRequest(
                    channel=forum,
                    top_msg_id=topico.id
                ))
                print_success(f"   ✅ [{i}/{len(topicos_vazios)}] {topico.title} deletado")
                deletados += 1
                await asyncio.sleep(0.5)  # Evitar FloodWait
                
            except FloodWaitError as e:
                print_warning(f"   ⏳ FloodWait: aguardando {e.seconds}s...")
                await asyncio.sleep(e.seconds + 2)
                # Tentar novamente
                try:
                    await client(functions.channels.DeleteTopicHistoryRequest(
                        channel=forum,
                        top_msg_id=topico.id
                    ))
                    print_success(f"   ✅ [{i}/{len(topicos_vazios)}] {topico.title} deletado")
                    deletados += 1
                except Exception as e2:
                    print_error(f"   ❌ Erro ao deletar {topico.title}: {e2}")
                    erros += 1
                    
            except Exception as e:
                print_error(f"   ❌ Erro ao deletar {topico.title}: {e}")
                erros += 1
        
        print_success(f"\n✅ Processo concluído!")
        print_info(f"   📊 {deletados} deletados | {erros} erros")
        
        return deletados
        
    except Exception as e:
        print_error(f"Erro ao limpar tópicos vazios: {e}")
        import traceback
        traceback.print_exc()
        return 0
