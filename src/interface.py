# interface.py

import sys
import inquirer
import asyncio
import os
import traceback
import json
import time
from rich.table import Table
from telethon import functions

from telethon.tl.types import ForumTopicDeleted
from telethon.errors.rpcerrorlist import FloodWaitError

# Importa as funções de estilo do novo módulo
from .estilo import (
    console, print_banner, print_section_header, print_success, 
    print_error, print_warning, print_info, countdown_timer
)
from .limiter import global_limiter

# --- FUNÇÃO DE ENVIO COM RETRY ---

async def send_message_with_retry(client, entity, copy_speed='traditional', limiter=None, **kwargs):
    """
    Envia uma mensagem ou ficheiro, tratando o erro FloodWaitError automaticamente.
    
    Args:
        client: Cliente Telegram
        entity: Destino da mensagem
        copy_speed: Velocidade de cópia ('traditional', 'fast', 'custom')
        limiter: RateLimiter customizado (opcional, usa global_limiter se não fornecido)
        **kwargs: Argumentos adicionais para send_file/send_message
    """
    # Usar limiter fornecido ou o global
    rate_limiter = limiter if limiter is not None else global_limiter
    
    # Calcular custo baseado no número de arquivos
    files = kwargs.get('file', [])
    if isinstance(files, list):
        cost = len(files) if files else 1
    else:
        cost = 1
    
    # 1. Espera permissão do Limiter (Proativo) com custo correto
    # O custo reflete o número real de mídias sendo enviadas
    await rate_limiter.wait(cost=cost)
    
    while True:
        try:
            if 'file' in kwargs:
                await client.send_file(entity, **kwargs)
            else:
                await client.send_message(entity, **kwargs)
            
            # Sucesso: avisa o limiter
            rate_limiter.report_success()
            return  # Sucesso
        except FloodWaitError as e:
            # Erro crítico de espera
            await rate_limiter.report_flood_wait(e.seconds)
        except Exception as e:
            print_error(f"Erro ao enviar mensagem: {e}. Tentando novamente em 5s...")
            if copy_speed == 'traditional':
                await asyncio.sleep(5)
            else:
                await asyncio.sleep(2) # Retentativa mais rápida se user quer velocidade

# --- Funções de Interface (Prompts e Seletores) ---

def _get_topics_cache_path(entity_id):
    """Retorna o caminho do arquivo de cache de tópicos para um grupo."""
    from . import gerenciador_dados as dados
    return os.path.join(dados.DADOS_DIR, f'cache_topicos_{entity_id}.json')

async def get_all_forum_topics(client, entity, force_refresh=False):
    """Busca todos os tópicos do fórum com suporte a cache, atualização incremental e fallback."""
    cache_path = _get_topics_cache_path(entity.id)
    
    # Classe para representar tópicos
    class TopicObj:
        def __init__(self, id, title):
            self.id = id
            self.title = title
    
    cached_topics = []
    cached_ids = set()
    cache_exists = os.path.exists(cache_path)
    
    # Tenta carregar cache
    if cache_exists and not force_refresh:
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                cached_data = json.load(f)
            
            # Verifica idade do cache
            file_time = os.path.getmtime(cache_path)
            age_hours = (time.time() - file_time) / 3600
            
            print_info(f"Cache encontrado: {len(cached_data)} tópicos (de {age_hours:.1f} horas atrás).")
            
            # Menu de opções
            q = [inquirer.List('cache_action', 
                              message="O que deseja fazer?",
                              choices=[
                                  ('📂 Usar Cache (Instantâneo)', 'use_cache'), 
                                  ('🔄 Atualizar (Buscar só novos)', 'update'),
                                  ('🌐 Busca Completa (Do zero)', 'full_refresh')
                              ])]
            ans = inquirer.prompt(q)
            action = ans['cache_action'] if ans else 'use_cache'
            
            if action == 'use_cache':
                return [TopicObj(t['id'], t['title']) for t in cached_data]
            
            elif action == 'update':
                # Carrega cache para atualização incremental
                cached_topics = [TopicObj(t['id'], t['title']) for t in cached_data]
                cached_ids = {t['id'] for t in cached_data}
                print_info(f"Carregado cache com {len(cached_topics)} tópicos. Buscando apenas novos...")
            
            # Se 'full_refresh', continua para busca completa abaixo

        except Exception as e:
            print_error(f"Erro ao ler cache de tópicos: {e}")

    print_info(f"Buscando tópicos do fórum '{entity.title}' online...")
    
    # Usa cache como base se disponível (modo incremental)
    seen_ids = cached_ids.copy() if cached_ids else set()
    all_topics = list(cached_topics) if cached_topics else []
    total_count = 0
    
    # ========== ESTRATÉGIA 1: Paginação padrão por data ==========
    print_info("Método 1: Paginação por data...")
    offset_date = None
    offset_id = 0
    offset_topic = 0
    stall_count = 0
    
    try:
        for page in range(100):  # Máximo 100 páginas
            result = await client(functions.channels.GetForumTopicsRequest(
                channel=entity,
                offset_date=offset_date,
                offset_id=offset_id,
                offset_topic=offset_topic,
                limit=100
            ))
            
            total_count = result.count
            
            if not result.topics:
                stall_count += 1
                if stall_count >= 3:
                    break
                await asyncio.sleep(0.3)
                continue
            
            new_count = 0
            for t in result.topics:
                if isinstance(t, ForumTopicDeleted):
                    continue
                if t.id not in seen_ids:
                    seen_ids.add(t.id)
                    all_topics.append(t)
                    new_count += 1
            
            if new_count == 0:
                stall_count += 1
                if stall_count >= 3:
                    break
            else:
                stall_count = 0
            
            print_info(f"Buscados {len(all_topics)} tópicos (Total: {total_count})...")
            
            if len(all_topics) >= total_count:
                break
            
            # Atualizar offsets usando o ÚLTIMO tópico
            last_topic = result.topics[-1]
            offset_date = getattr(last_topic, 'date', None)
            offset_id = getattr(last_topic, 'top_message', 0)
            offset_topic = last_topic.id
            
            await asyncio.sleep(0.2)
            
    except Exception as e:
        print_warning(f"Método 1 teve erro: {e}")
    
    # ========== ESTRATÉGIA 2: Descoberta via mensagens (fallback) ==========
    if len(all_topics) < total_count * 0.9:  # Se faltam mais de 10%
        print_info(f"Método 2: Descobrindo tópicos via TODAS as mensagens ({len(all_topics)}/{total_count})...")
        
        try:
            # Coletar todos os topic_ids únicos das mensagens
            topic_ids_to_fetch = set()
            msg_count = 0
            
            # Iterar TODAS as mensagens (sem limite)
            async for msg in client.iter_messages(entity, limit=None):
                msg_count += 1
                
                # Em fóruns, cada mensagem tem reply_to indicando o tópico
                if hasattr(msg, 'reply_to') and msg.reply_to:
                    # reply_to_top_id é o ID do tópico (primeira msg do thread)
                    topic_id = getattr(msg.reply_to, 'reply_to_top_id', None)
                    if not topic_id:
                        topic_id = getattr(msg.reply_to, 'reply_to_msg_id', None)
                    
                    if topic_id and topic_id not in seen_ids:
                        topic_ids_to_fetch.add(topic_id)
                
                if msg_count % 2000 == 0:
                    novos = len(topic_ids_to_fetch)
                    print_info(f"Analisadas {msg_count} mensagens... ({len(all_topics) + novos} tópicos potenciais)")
                
                # Se já temos IDs suficientes, podemos parar de iterar
                if len(all_topics) + len(topic_ids_to_fetch) >= total_count:
                    break
            
            print_info(f"Encontrados {len(topic_ids_to_fetch)} IDs de tópicos novos. Buscando nomes...")
            
            # Classe para representar tópicos descobertos
            class SimpleTopicObj:
                def __init__(self, id, title):
                    self.id = id
                    self.title = title
            
            # Buscar nome real de cada tópico via mensagem original
            added_count = 0
            topic_ids_list = list(topic_ids_to_fetch)
            
            for i, tid in enumerate(topic_ids_list):
                if tid in seen_ids:
                    continue
                
                topic_title = f"Tópico #{tid}"  # Fallback
                
                try:
                    # Buscar a mensagem original do tópico (ID do tópico = ID da primeira mensagem)
                    msgs = await client.get_messages(entity, ids=[tid])
                    if msgs and msgs[0]:
                        original_msg = msgs[0]
                        # MessageActionTopicCreate tem o título real do tópico
                        if hasattr(original_msg, 'action') and original_msg.action:
                            action_title = getattr(original_msg.action, 'title', None)
                            if action_title:
                                topic_title = action_title
                        # Se não tem action, mantém fallback (Tópico #ID)
                        # NÃO usar texto da mensagem pois pode ser lixo
                except Exception:
                    pass  # Usar fallback
                
                seen_ids.add(tid)
                all_topics.append(SimpleTopicObj(tid, topic_title))
                added_count += 1
                
                # Mostrar progresso a cada 50 tópicos
                if added_count % 50 == 0:
                    print_info(f"Buscando nomes... {added_count}/{len(topic_ids_list)} tópicos")
                
                # Rate limiting suave
                if added_count % 20 == 0:
                    await asyncio.sleep(0.1)
            
            if added_count > 0:
                print_info(f"Adicionados {added_count} tópicos descobertos via mensagens. Total: {len(all_topics)}")
                    
        except Exception as e:
            print_warning(f"Método 2 teve erro: {e}")
    
    # ========== ESTRATÉGIA 3: Busca por Q variados (fallback final) ==========
    if len(all_topics) < total_count * 0.9:
        print_info(f"Método 3: Busca por texto ({len(all_topics)}/{total_count})...")
        
        try:
            # Tentar buscar com diferentes queries
            queries = ['', 'a', 'e', 'i', 'o', 'u', '1', '2', '3']
            for q in queries:
                result = await client(functions.channels.GetForumTopicsRequest(
                    channel=entity,
                    q=q,
                    offset_date=None,
                    offset_id=0,
                    offset_topic=0,
                    limit=100
                ))
                
                for t in result.topics:
                    if not isinstance(t, ForumTopicDeleted) and t.id not in seen_ids:
                        seen_ids.add(t.id)
                        all_topics.append(t)
                
                await asyncio.sleep(0.2)
                
                if len(all_topics) >= total_count:
                    break
                    
        except Exception as e:
            print_warning(f"Método 3 teve erro: {e}")
    
    # Salva no Cache
    try:
        cache_data = [{'id': t.id, 'title': t.title} for t in all_topics]
        with open(cache_path, 'w', encoding='utf-8') as f:
            json.dump(cache_data, f, indent=2, ensure_ascii=False)
        print_success(f"Lista de {len(all_topics)} tópicos salva em cache.")
    except Exception as e:
        print_warning(f"Não foi possível salvar cache de tópicos: {e}")

    print_success(f"{len(all_topics)} tópicos encontrados.")
    return all_topics

async def selecionar_grupo(client, prompt_message, group_type):
    """Mostra uma lista de chats com filtros avançados."""
    from .estilo import get_spinner
    from .database import db
    
    # Carregar todos os chats
    with get_spinner("Carregando sua lista de grupos e canais..."):
        all_chats = []
        try:
            async for dialog in client.iter_dialogs():
                if not (dialog.is_group or dialog.is_channel):
                    continue
                
                entity = dialog.entity
                # Adicionar metadados ao entity
                entity._is_forum = hasattr(entity, 'forum') and entity.forum
                entity._is_channel = hasattr(entity, 'broadcast') and entity.broadcast
                entity._is_admin = hasattr(dialog, 'is_admin') and dialog.is_admin
                entity._is_creator = hasattr(entity, 'creator') and entity.creator
                
                # Filtro base por tipo (se especificado)
                if group_type == 'forum' and not entity._is_forum:
                    continue
                elif group_type == 'forums' and not entity._is_forum:
                    continue
                elif group_type == 'forums_admin' and (not entity._is_forum or (not entity._is_admin and not entity._is_creator)):
                    continue
                elif group_type == 'traditional' and entity._is_forum:
                    continue
                
                all_chats.append(entity)
        except Exception as e:
            print_error(f"Erro ao listar seus chats: {e}")
            return None

    if not all_chats:
        print_warning(f"Nenhum grupo do tipo '{group_type}' encontrado.")
        return None

    # IDs de grupos auditados
    audited_channel_ids = db.get_audited_channel_ids()
    
    # Menu de filtros
    filtro_perguntas = [
        inquirer.List('filtro',
                      message="🔍 Filtrar grupos por:",
                      choices=[
                          ('📋 Ver Todos', 'todos'),
                          ('📁 [FÓRUM] Apenas Fóruns', 'forum'),
                          ('💬 Apenas Grupos Tradicionais', 'tradicional'),
                          ('📢 Apenas Canais', 'canal'),
                          ('👑 Sou Dono/Admin', 'admin'),
                          ('👤 Sou Membro', 'membro'),
                          ('✅ Apenas Auditados', 'auditados'),
                          ('🔙 Cancelar', 'cancelar')
                      ],
                      carousel=True)
    ]
    
    filtro_resp = inquirer.prompt(filtro_perguntas, theme=inquirer.themes.GreenPassion())
    if not filtro_resp or filtro_resp['filtro'] == 'cancelar':
        return None
    
    filtro = filtro_resp['filtro']
    
    # Aplicar filtro selecionado
    chats_filtrados = all_chats.copy()
    
    if filtro == 'forum':
        chats_filtrados = [c for c in chats_filtrados if c._is_forum]
    elif filtro == 'tradicional':
        chats_filtrados = [c for c in chats_filtrados if not c._is_forum and not c._is_channel]
    elif filtro == 'canal':
        chats_filtrados = [c for c in chats_filtrados if c._is_channel]
    elif filtro == 'admin':
        chats_filtrados = [c for c in chats_filtrados if c._is_admin or c._is_creator]
    elif filtro == 'membro':
        chats_filtrados = [c for c in chats_filtrados if not c._is_admin and not c._is_creator]
    elif filtro == 'auditados':
        chats_filtrados = [c for c in chats_filtrados if c.id in audited_channel_ids]
    
    if not chats_filtrados:
        print_warning(f"Nenhum grupo encontrado com este filtro.")
        input("Pressione Enter para voltar...")
        return None
    
    # Formatar as opções
    choices = []
    for c in chats_filtrados:
        prefix_parts = []
        
        # Indicador de auditoria
        if c.id in audited_channel_ids:
            prefix_parts.append("✅")
        else:
            prefix_parts.append("   ")
        
        # Indicador de tipo
        if c._is_forum:
            prefix_parts.append("[FÓRUM]")
        elif c._is_channel:
            prefix_parts.append("[CANAL]")
        
        # Indicador de permissão
        if c._is_creator:
            prefix_parts.append("👑")
        elif c._is_admin:
            prefix_parts.append("⭐")
        
        prefix = " ".join(prefix_parts)
        label = f"{prefix} {c.title}"
        choices.append((label, c))
    
    # Ordenar alfabeticamente
    choices.sort(key=lambda x: x[0].lower())
    
    # Adicionar opções extras no início
    choices.insert(0, ('🔙 Voltar (mudar filtro)', 'voltar'))
    choices.insert(1, ('🔍 Buscar Grupo por Nome', 'pesquisar'))
    
    # Exibir quantidade
    print_info(f"📊 {len(choices) - 2} grupo(s) encontrado(s)")
    
    while True:
        pergunta = [inquirer.List('chat', message=prompt_message, choices=choices, carousel=True)]
        resposta = inquirer.prompt(pergunta, theme=inquirer.themes.GreenPassion())
        
        if not resposta or resposta['chat'] == 'voltar':
            # Recursão: volta ao menu de filtros
            return await selecionar_grupo(client, prompt_message, group_type)
            
        if resposta['chat'] == 'pesquisar':
            pesq_resp = inquirer.prompt([inquirer.Text('q', message="Digite parte do nome do grupo")])
            if not pesq_resp or not pesq_resp['q']:
                continue
            
            termo = pesq_resp['q'].lower().strip()
            # Fazer backup do choices original
            if not hasattr(selecionar_grupo, '_original_choices'):
                selecionar_grupo._original_choices = choices.copy()
            else:
                # Restaurar original antes de filtrar
                choices = selecionar_grupo._original_choices.copy()
            
            # Manter as opções de navegação e filtrar o resto
            opcoes_nav = choices[:2]
            opcoes_grupos = [c for c in choices[2:] if termo in c[0].lower()]
            
            if not opcoes_grupos:
                print_warning(f"Nenhum grupo encontrado contendo '{termo}'.")
                choices = selecionar_grupo._original_choices.copy()
                continue
                
            choices = opcoes_nav + opcoes_grupos
            print_info(f"✅ {len(opcoes_grupos)} grupo(s) encontrado(s) com '{termo}'")
            continue
            
        # Limpar backup se escolheu um grupo
        if hasattr(selecionar_grupo, '_original_choices'):
            delattr(selecionar_grupo, '_original_choices')
            
        return resposta['chat']


async def selecionar_grupo_com_auditoria(client, prompt_message):
    """Mostra uma lista de chats que possuem uma auditoria salva para seleção."""
    print_info("Carregando sua lista de grupos com auditorias salvas, aguarde...")
    
    auditorias = listar_auditorias_salvas()
    if not auditorias:
        print_warning("Nenhuma auditoria salva encontrada.")
        input("Pressione Enter para voltar...")
        return None

    chats = []
    try:
        # Criar um mapa de ID de grupo para a entidade do chat
        dialogs_map = {
            dialog.entity.id: dialog.entity 
            async for dialog in client.iter_dialogs() 
            if dialog.is_group or dialog.is_channel
        }

        for aud in auditorias:
            # CORRIGIDO: Usar channel_id diretamente do novo formato
            grupo_id = aud.get('channel_id')
            if grupo_id and grupo_id in dialogs_map:
                entity = dialogs_map[grupo_id]
                # Extrair data da auditoria
                data_aud = aud.get('last_audited_at', 'N/A')
                if data_aud and 'T' in str(data_aud):
                    data_aud = str(data_aud).split('T')[0]
                elif data_aud and ' ' in str(data_aud):
                    data_aud = str(data_aud).split(' ')[0]
                entity.data_auditoria = data_aud
                # NOVO: Guardar conta que fez a auditoria
                entity.account_phone = aud.get('account_phone', None)
                chats.append(entity)

    except Exception as e:
        print_error(f"Erro ao listar seus chats auditados: {e}")
        return None

    if not chats:
        print_warning("Nenhum dos seus grupos atuais possui uma auditoria salva.")
        input("Pressione Enter para voltar...")
        return None

    # Formata o nome para incluir a data e conta da auditoria
    def format_label(c):
        label = f"{c.title} (Auditado em: {c.data_auditoria}"
        if c.account_phone:
            # Mostra só os últimos 4 dígitos para privacidade
            phone_suffix = c.account_phone[-4:] if len(c.account_phone) >= 4 else c.account_phone
            label += f" | Conta: ...{phone_suffix}"
        label += ")"
        return label
    
    choices = sorted(
        [(format_label(c), c) for c in chats], 
        key=lambda x: x[0]
    )
    
    # Adicionar opções de navegação
    choices.insert(0, ('🔙 Voltar ao Menu', 'voltar'))
    choices.insert(1, ('🔍 Buscar Grupo por Nome', 'pesquisar'))
    
    while True:
        pergunta = [inquirer.List('chat', message=prompt_message, choices=choices, carousel=True)]
        resposta = inquirer.prompt(pergunta, theme=inquirer.themes.GreenPassion())
        
        if not resposta or resposta['chat'] == 'voltar':
            if hasattr(selecionar_grupo_com_auditoria, '_original_choices'):
                delattr(selecionar_grupo_com_auditoria, '_original_choices')
            return None
            
        if resposta['chat'] == 'pesquisar':
            pesq_resp = inquirer.prompt([inquirer.Text('q', message="Digite parte do nome do grupo")], theme=inquirer.themes.GreenPassion())
            if not pesq_resp or not pesq_resp['q']:
                continue
                
            termo = pesq_resp['q'].lower().strip()
            if not hasattr(selecionar_grupo_com_auditoria, '_original_choices'):
                selecionar_grupo_com_auditoria._original_choices = choices.copy()
            else:
                choices = selecionar_grupo_com_auditoria._original_choices.copy()
                
            opcoes_nav = choices[:2]
            opcoes_grupos = [c for c in choices[2:] if termo in c[0].lower()]
            
            if not opcoes_grupos:
                print_warning(f"Nenhum grupo encontrado contendo '{termo}'.")
                choices = selecionar_grupo_com_auditoria._original_choices.copy()
                continue
                
            choices = opcoes_nav + opcoes_grupos
            print_info(f"✅ {len(opcoes_grupos)} grupo(s) encontrado(s) com '{termo}'")
            continue
            
        if hasattr(selecionar_grupo_com_auditoria, '_original_choices'):
            delattr(selecionar_grupo_com_auditoria, '_original_choices')
            
        return resposta['chat']


def prompt_menu_principal(telefone_logado):
    """Mostra o menu principal com um painel Rich."""
    print_banner()
    console.print(f"👤 Conta Ativa: [bold green]{telefone_logado}[/bold green]", justify="center")
    
    perguntas = [
        inquirer.List('acao',
                      message="O que deseja fazer?",
                      choices=[
                          ('🚀 Iniciar Nova Tarefa de Cópia', 'nova_tarefa'),
                          ('🔄 CLONAR GRUPO COMPLETO (Automático)', 'clonar_completo'),
                          ('✨ Copiar Tópicos de Fórum', 'copiar_topicos'),
                          ('📁 Organizar Grupo em Tópicos', 'organizar_topicos'),
                          ('📋 Criar/Atualizar Índice', 'criar_indice'),
                          ('🗑️ Deletar Tópicos', 'deletar_topicos'),
                          ('✨ Criar Grupos em Massa', 'criar_grupos'),
                          ('🔄 Executar Tarefa Salva', 'tarefa_salva'),
                          ('📊 Gerenciar Auditorias', 'auditoria'),
                          ('📈 Estatísticas do Sistema', 'estatisticas'),
                          ('⚠️ Ver Mídias que Falharam', 'ver_falhas'),
                          ('💾 Fazer Backup Manual', 'backup'),
                          ('⚙️ Gerenciar Contas', 'contas'),
                          ('☢️  Restauração de Fábrica', 'factory_reset'),
                          ('🚪 Sair do Programa', 'sair')
                      ],
                      carousel=True),
    ]
    print_section_header("Menu Principal")
    resposta = inquirer.prompt(perguntas, theme=inquirer.themes.GreenPassion())
    return resposta['acao'] if resposta else 'sair'


def prompt_menu_auditoria():
    """Mostra o submenu de gerenciamento de auditorias."""
    print_section_header("Gerenciar Auditorias")
    perguntas = [
        inquirer.List('acao_auditoria',
                      message="Opções de Auditoria:",
                      choices=[
                          ('➕ Fazer Nova Auditoria Completa', 'nova'),
                          ('🔄 Atualizar Auditoria Existente', 'atualizar'),
                          ('👁️ Ver Detalhes de Auditoria', 'ver_detalhes'),
                          ('➖ Deletar Auditoria(s) Salva(s)', 'deletar'),
                          ('🔙 Voltar ao Menu Principal', 'voltar')
                      ],
                      carousel=True),
    ]
    resposta = inquirer.prompt(perguntas, theme=inquirer.themes.GreenPassion())
    return resposta['acao_auditoria'] if resposta else 'voltar'


async def prompt_ver_detalhes_auditoria(client):
    """Mostra os detalhes de uma auditoria existente usando tabelas Rich com estatísticas completas."""
    from .database import db
    
    print_section_header("Ver Detalhes de Auditoria")
    
    grupo = await selecionar_grupo_com_auditoria(client, "Selecione a auditoria para ver os detalhes")
    if not grupo:
        return

    # Buscar metadados e estatísticas
    audit_meta = db.get_audit_metadata(grupo.id)
    stats = db.get_media_stats_by_type(grupo.id)
    
    if not audit_meta:
        print_error(f"Não foi possível carregar a auditoria para '{grupo.title}'.")
        return

    # === TABELA PRINCIPAL ===
    table = Table(title=f"📊 Auditoria: [bold]{audit_meta['channel_name']}[/bold]", border_style="accent")
    table.add_column("Propriedade", justify="right", style="cyan", no_wrap=True)
    table.add_column("Valor", style="green")

    data_auditoria = audit_meta.get('last_audited_at', 'N/A')
    if data_auditoria and '.' in str(data_auditoria):
        data_auditoria = str(data_auditoria).split('.')[0]
        
    table.add_row("📁 Total de Mídias", f"[bold]{stats['total']:,}[/bold]")
    table.add_row("💾 Tamanho Total", f"{stats['tamanho_total_mb']} MB")
    table.add_row("📅 Última Auditoria", data_auditoria)
    table.add_row("🔢 Último Msg ID", str(audit_meta.get('last_message_id', 'N/A')))

    console.print(table)
    
    # === TABELA POR TIPO ===
    if stats['por_tipo']:
        tipo_table = Table(title="📷 Mídias por Tipo", border_style="info")
        tipo_table.add_column("Tipo", justify="center", style="cyan")
        tipo_table.add_column("Quantidade", justify="center", style="green")
        tipo_table.add_column("Percentual", justify="center", style="yellow")
        
        tipo_icons = {
            'photo': '📷 Fotos',
            'video': '🎥 Vídeos', 
            'audio': '🎵 Áudios',
            'voice': '🎤 Áudios de Voz',
            'video_note': '📹 Vídeo-Notas',
            'sticker': '😀 Stickers',
            'gif': '🎬 GIFs',
            'document': '📄 Documentos',
            'unknown': '❓ Outros'
        }
        
        total = stats['total'] if stats['total'] > 0 else 1
        for tipo, count in sorted(stats['por_tipo'].items(), key=lambda x: x[1], reverse=True):
            nome_tipo = tipo_icons.get(tipo, f"❓ {tipo}")
            percentual = (count / total) * 100
            tipo_table.add_row(nome_tipo, f"{count:,}", f"{percentual:.1f}%")
        
        console.print(tipo_table)
    
    # === TABELA POR HORA (resumida) ===
    if stats['por_hora']:
        hora_table = Table(title="⏰ Atividade por Hora do Dia", border_style="info")
        hora_table.add_column("Horário", justify="center", style="cyan")
        hora_table.add_column("Mídias", justify="center", style="green")
        
        # Pegar apenas as 5 horas mais ativas
        horas_ordenadas = sorted(stats['por_hora'].items(), key=lambda x: x[1], reverse=True)[:5]
        for hora, count in horas_ordenadas:
            hora_table.add_row(hora, f"{count:,}")
        
        console.print(hora_table)
    
    # === ÚLTIMAS DATAS ===
    if stats['por_data']:
        data_table = Table(title="📅 Últimas Datas com Mídias", border_style="info", show_lines=False)
        data_table.add_column("Data", justify="center", style="cyan")
        data_table.add_column("Mídias", justify="center", style="green")

        for data, contagem in list(stats['por_data'].items())[:10]:  # Últimas 10 datas
            data_table.add_row(data, str(contagem))
        
        console.print(data_table)


def prompt_menu_contas():
    """Mostra o submenu de gerenciamento de contas."""
    print_section_header("Gerenciar Contas")
    perguntas = [
        inquirer.List('acao',
                      message="Opções de Conta:",
                      choices=[
                          ('➕ Adicionar Nova Conta', 'adicionar'),
                          ('➖ Remover Conta Existente', 'remover'),
                          ('🔄 Trocar de Conta (Relogar)', 'trocar'),
                          ('🔙 Voltar ao Menu Principal', 'voltar')
                      ],
                      carousel=True),
    ]
    resposta = inquirer.prompt(perguntas, theme=inquirer.themes.GreenPassion())
    return resposta['acao'] if resposta else 'voltar'

def prompt_selecionar_tarefa(tasks):
    """Mostra a lista de tarefas salvas para seleção."""
    print_section_header("Executar Tarefa Salva")
    if not tasks:
        print_warning("Nenhuma tarefa salva encontrada.")
        input("Pressione Enter para voltar...")
        return None
    
    choices = []
    for key, config in tasks.items():
        label = f"'{config['nome_origem']}' -> '{config['nome_destino']}' ({config['modo']})"
        choices.append((label, key))
    
    choices.append('--------------------')
    choices.append(("❌ Deletar Tarefa", "deletar"))
    choices.append(("🔙 Voltar", "voltar"))
    
    perguntas = [
        inquirer.List('task_key', message="Selecione a tarefa para executar ou ação", choices=choices, carousel=True)
    ]
    resposta = inquirer.prompt(perguntas)
    
    if not resposta or resposta['task_key'] == 'voltar':
        return None

    if resposta['task_key'] == 'deletar':
        print_section_header("Deletar Tarefa")
        
        delete_choices = []
        for key, config in tasks.items():
            label = f"'{config['nome_origem']}' -> '{config['nome_destino']}'"
            delete_choices.append((label, key))
        delete_choices.append(("🔙 Voltar", "voltar"))

        delete_pergunta = [
            inquirer.List('task_to_delete', message="Selecione a tarefa para deletar", choices=delete_choices, carousel=True)
        ]
        delete_resposta = inquirer.prompt(delete_pergunta)

        if not delete_resposta or delete_resposta['task_to_delete'] == 'voltar':
            return None
        
        return f"delete_{delete_resposta['task_to_delete']}"

    return resposta['task_key']

async def prompt_nova_tarefa(client):
    """Assistente (wizard) para configurar uma nova tarefa de cópia."""
    os.system('cls' if os.name == 'nt' else 'clear')
    print_section_header("Configurar Nova Tarefa de Cópia")
    
    config = {}

    try:
        group_type_question = [
            inquirer.List(
                'group_type',
                message="Você quer copiar de um grupo Fórum ou Tradicional?",
                choices=[
                    ('Fórum', 'forum'),
                    ('Tradicional', 'traditional')
                ],
            ),
        ]
        group_type_answer = inquirer.prompt(group_type_question)
        group_type = group_type_answer['group_type']

        origem = await selecionar_grupo(client, "1. Selecione o grupo de ORIGEM", group_type)
        if not origem: return None
        config['id_origem'] = origem.id
        config['nome_origem'] = origem.title

        destino = await selecionar_grupo(client, "2. Selecione o grupo de DESTINO", 'any')
        if not destino: return None
        config['id_destino'] = destino.id
        config['nome_destino'] = destino.title
        
        if origem.id == destino.id:
            print_error("O grupo de origem e destino não podem ser o mesmo.")
            return None

        is_forum = False
        if hasattr(destino, 'forum') and destino.forum:
            print_success(f"Detectado que '{destino.title}' é um Fórum!")
            is_forum = True
        else:
            is_forum = inquirer.prompt([inquirer.Confirm('is_forum', message=f"O destino '{destino.title}' é um Fórum (com Tópicos)?", default=False)]).get('is_forum')

        if is_forum:
            config['modo'] = "Fórum (Indexado)"
            
            topicos_destino = await get_all_forum_topics(client, destino)
            topicos_destino.append({"id": 0, "title": "➕ CRIAR NOVO TÓPICO DE ÍNDICE"})
            
            choices = [
                (t['title'], t['id']) if isinstance(t, dict) else (t.title, t.id)
                for t in topicos_destino 
                if isinstance(t, dict) or t.id != 1 
            ]
            
            perg_indice = [inquirer.List('topico_id', message="4a. Em qual tópico o Índice será publicado/atualizado?", choices=choices, carousel=True)]
            resp_indice = inquirer.prompt(perg_indice)
            
            if not resp_indice: 
                raise KeyboardInterrupt
                
            if resp_indice['topico_id'] == 0:
                nome_topico_indice = inquirer.text(message="Digite o nome do novo Tópico de Índice:", default="ÍNDICE DE MÍDIAS")
                try:
                    updates = await client(functions.channels.CreateForumTopicRequest(
                        channel=destino,
                        title=nome_topico_indice,
                        random_id=int.from_bytes(os.urandom(8), 'big', signed=True)
                    ))
                    config['id_topico_indice'] = updates.updates[0].id
                    print_success(f"Tópico '{nome_topico_indice}' criado com sucesso.")
                except Exception as e:
                    print_error(f"Não foi possível criar o tópico: {e}")
                    return None
            else:
                config['id_topico_indice'] = resp_indice['topico_id']

            lote_str = inquirer.text(message="4b. Quantas mídias por Tópico-Lote?", default="250", validate=lambda _, x: x.isdigit() and int(x) > 0)
            config['lote_size'] = int(lote_str)
        
        else:
            config['modo'] = "Tradicional (Simples)"
            config['id_topico_indice'] = None
            config['lote_size'] = 10 

        # --- NOVO: Pergunta sobre Automação Total ---
        automacao_resp = inquirer.prompt([
            inquirer.Confirm('automacao', 
                            message="🤖 Ativar MODO AUTOMÁTICO? (Pula perguntas de auditoria/datas e faz tudo sozinho)", 
                            default=False)
        ])
        config['automacao_total'] = automacao_resp['automacao'] if automacao_resp else False

        perg_modo_copia = [inquirer.List('modo_copia', message="5a. Modo de Cópia:", choices=[
            ('Copiar TUDO (Com Persistência e Atualização)', 'tudo'),
            ('Copiar Quantidade Específica (Snapshot)', 'qtd')
        ])]
        resp_modo_copia = inquirer.prompt(perg_modo_copia)
        if not resp_modo_copia: raise KeyboardInterrupt
        config['modo_copia'] = resp_modo_copia['modo_copia']

        if config['modo_copia'] == 'tudo':
            perg_ordem = [inquirer.List('ordem', message="5b. Ordem:", choices=[
                ('Crescente (Mais antigas primeiro)', 'crescente'),
                ('Decrescente (Mais novas primeiro)', 'decrescente')
            ])]
            resp_ordem = inquirer.prompt(perg_ordem)
            if not resp_ordem: raise KeyboardInterrupt
            config['ordem'] = resp_ordem['ordem']
            config['quantidade'] = None
        else:
            qtd_str = inquirer.text(message="5b. Quantas mídias deseja copiar?", default="1000", validate=lambda _, x: x.isdigit() and int(x) > 0)
            config['quantidade'] = int(qtd_str)
            
            perg_ordem = [inquirer.List('ordem', message="5c. Ordem:", choices=[
                ('Crescente (Mais antigas primeiro)', 'crescente'),
                ('Decrescente (Mais novas primeiro)', 'decrescente')
            ])]
            resp_ordem = inquirer.prompt(perg_ordem)
            if not resp_ordem: raise KeyboardInterrupt
            config['ordem'] = resp_ordem['ordem']

        copy_speed_question = [
            inquirer.List(
                'copy_speed',
                message="Escolha a velocidade da cópia:",
                choices=[
                    ('Tradicional (com pausa)', 'traditional'),
                    ('Ultra Rápida (sem pausa)', 'fast'),
                    ('Personalizado (pausar a cada X mídias)', 'custom')
                ],
            ),
        ]
        copy_speed_answer = inquirer.prompt(copy_speed_question)
        config['copy_speed'] = copy_speed_answer['copy_speed']

        if config['copy_speed'] == 'custom':
            media_per_pause_str = inquirer.text(
                message="Pausar a cada quantas mídias enviadas?",
                default="100",
                validate=lambda _, x: x.isdigit() and int(x) > 0
            )
            config['media_per_pause'] = int(media_per_pause_str)

            pause_duration_str = inquirer.text(
                message="Duração da pausa em segundos?",
                default="60",
                validate=lambda _, x: x.isdigit() and int(x) > 0
            )
            config['pause_duration'] = int(pause_duration_str)

        if inquirer.prompt([inquirer.Confirm('salvar', message="Deseja salvar esta configuração como uma Tarefa Rápida?", default=True)]).get('salvar'):
            config['salvar_tarefa'] = True
        else:
            config['salvar_tarefa'] = False

        print_success("Configuração da tarefa concluída!")
        return config

    except (KeyboardInterrupt, TypeError) as e:
        if isinstance(e, TypeError):
            print_error(f"Erro de tipo inesperado: {e}")
            traceback.print_exc()
            
        print_warning("\nConfiguração da tarefa cancelada.")
        return None
    except Exception as e:
        print_error(f"Erro inesperado durante a configuração: {e}")
        return None

async def prompt_file_filter():
    """Pede ao usuário para escolher um filtro de arquivo."""
    questions = [
        inquirer.List(
            'file_type',
            message="Qual tipo de arquivo você quer copiar?",
            choices=[
                ('Fotos', 'photo'),
                ('Vídeos', 'video'),
                ('Legendas', 'subtitle'),
                ('Hiperlinks', 'hyperlink'),
                ('Copiar tudo', 'all')
            ],
        ),
    ]
    answers = inquirer.prompt(questions)
    return answers['file_type']

from .auditoria import listar_auditorias_salvas, deletar_auditoria_salva, AuditoriaGrupo

async def prompt_copiar_topicos(client):
    """Assistente para a nova funcionalidade de copiar tópicos de fórum (Máquina de Estados)."""
    os.system('cls' if os.name == 'nt' else 'clear')
    print_section_header("COPIAR TÓPICOS DE FÓRUM")
    
    config = {}
    step = 1
    
    # Variáveis de estado para persistir escolhas ao voltar
    origem = None
    topicos_origem = None
    destino = None
    topicos_destino = None

    while True:
        try:
            # --- PASSO 1: ORIGEM ---
            if step == 1:
                print_info("ETAPA 1: SELECIONE O GRUPO DE ORIGEM")
                origem = await selecionar_grupo(client, "Selecione o grupo de FÓRUM de onde deseja copiar os tópicos", 'forum')
                if not origem: return None # Cancelou no início
                config['id_origem'] = origem.id
                config['nome_origem'] = origem.title
                step = 2

            # --- PASSO 2: TÓPICOS ---
            elif step == 2:
                print_info("ETAPA 2: SELECIONE OS TÓPICOS PARA COPIAR")
                # Só busca se ainda não tiver buscado ou se mudou a origem
                if not topicos_origem: 
                    topicos_origem = await get_all_forum_topics(client, origem)
                
                if not topicos_origem:
                    print_warning(f"Nenhum tópico encontrado em '{origem.title}'.")
                    step = 1 # Volta para origem
                    continue

                # Ordenar alfabeticamente
                topicos_origem.sort(key=lambda t: t.title.lower())

                choices_topicos = []
                
                while True:
                    modo_selecao = inquirer.prompt([
                        inquirer.List('modo', 
                                     message="Como deseja selecionar os tópicos?",
                                     choices=[
                                         ('📜 Listar Todos (Ordem Alfabética)', 'all'),
                                         ('🔍 Buscar/Filtrar por Nome', 'search'),
                                         ('🔄 Buscar Tópicos Novamente (Atualizar)', 'refresh'),
                                         ('🔙 Voltar para Seleção de Grupo', 'back')
                                     ])
                    ])
                    
                    if not modo_selecao: return None # Cancelou forçado
                    if modo_selecao['modo'] == 'back':
                        step = 1
                        break # Sai do loop de seleção
                    
                    if modo_selecao['modo'] == 'refresh':
                        # Força busca completa (mostra menu de opções de cache)
                        topicos_origem = await get_all_forum_topics(client, origem, force_refresh=True)
                        topicos_origem.sort(key=lambda t: t.title.lower())
                        print_success(f"Lista atualizada: {len(topicos_origem)} tópicos encontrados!")
                        continue  # Volta ao menu

                    if modo_selecao['modo'] == 'search':
                        busca = inquirer.text(message="Digite o nome (ou parte dele) para buscar")
                        if not busca: continue
                        
                        filtrados = [t for t in topicos_origem if busca.lower() in t.title.lower()]
                        if not filtrados:
                            print_warning(f"Nenhum tópico encontrado contendo '{busca}'.")
                            continue
                        
                        choices_topicos = [(f"{i+1}. {t.title}", t.id) for i, t in enumerate(filtrados)]
                        break # Vai para checkboxes
                    else:
                        choices_topicos = [(f"{i+1}. {t.title}", t.id) for i, t in enumerate(topicos_origem)]
                        break # Vai para checkboxes

                if step == 1: continue # Executa a volta

                perguntas_topicos = [
                    inquirer.Checkbox('topicos_selecionados',
                                      message=f"Selecione os tópicos ({len(choices_topicos)} listados) - Use Espaço para marcar",
                                      choices=[('>> SELECIONAR TODOS DA LISTA ABAIXO <<', 'all_visible')] + choices_topicos,
                                      carousel=True),
                ]
                respostas_topicos = inquirer.prompt(perguntas_topicos)
                
                if not respostas_topicos: return None 
                if not respostas_topicos['topicos_selecionados']:
                    print_warning("Nenhum tópico selecionado.")
                    if inquirer.prompt([inquirer.Confirm('retry', message="Tentar selecionar novamente?", default=True)])['retry']:
                        continue # Fica no passo 2
                    else:
                        return None

                selected_ids = []
                if 'all_visible' in respostas_topicos['topicos_selecionados']:
                    selected_ids = [tid for label, tid in choices_topicos]
                else:
                    selected_ids = respostas_topicos['topicos_selecionados']

                config['topicos_selecionados'] = selected_ids
                config['nomes_topicos_selecionados'] = {t.id: t.title for t in topicos_origem if t.id in selected_ids}
                print_success(f"{len(selected_ids)} tópicos selecionados.")
                step = 3

            # --- PASSO 3: DESTINO ---
            elif step == 3:
                print_info("ETAPA 3: SELECIONE O GRUPO DE DESTINO")
                # Adiciona opção manual de voltar
                q_voltar = [inquirer.List('acao', message="Selecione o destino", choices=[('Selecionar Grupo...', 'go'), ('🔙 Voltar', 'back')])] # type: ignore
                ans = inquirer.prompt(q_voltar)
                if not ans or ans['acao'] == 'back':
                    step = 2
                    continue

                destino = await selecionar_grupo(client, "Selecione o grupo de FÓRUM para onde os tópicos serão copiados", 'forum')
                if not destino: 
                    step = 2 # Se cancelar a seleção de grupo, volta
                    continue
                    
                if origem.id == destino.id:
                    print_error("O grupo de origem e destino não podem ser o mesmo.")
                    continue

                config['id_destino'] = destino.id
                config['nome_destino'] = destino.title
                step = 4

            # --- PASSO 4: ÍNDICE ---
            elif step == 4:
                print_info("ETAPA 4: SELECIONE O TÓPICO DE ÍNDICE")
                # Cache de tópicos destino para não buscar toda hora se voltar
                if not topicos_destino or config['id_destino'] != destino.id: # type: ignore
                    topicos_destino = await get_all_forum_topics(client, destino)
                
                # Cria lista para menu, incluindo opção de Criar Novo
                lista_menu = [t for t in topicos_destino] # Cópia rasa
                lista_menu.append({"id": 0, "title": "➕ CRIAR NOVO TÓPICO DE ÍNDICE"})
                
                choices_indice = [
                    (t.title if hasattr(t, 'title') else t['title'], t.id if hasattr(t, 'id') else t['id'])
                    for t in lista_menu if (hasattr(t, 'id') and t.id != 1) or (isinstance(t, dict) and t['id'] != 1)
                ]
                choices_indice.append(('🔙 Voltar', 'back'))
                
                perg_indice = [inquirer.List('topico_id', message="Em qual tópico o Índice será publicado/atualizado?", choices=choices_indice, carousel=True)]
                resp_indice = inquirer.prompt(perg_indice)
                
                if not resp_indice or resp_indice['topico_id'] == 'back':
                    step = 3
                    continue

                if resp_indice['topico_id'] == 0:
                    nome_topico_indice = inquirer.text(message="Digite o nome do novo Tópico de Índice:", default="ÍNDICE GERAL")
                    try:
                        updates = await client(functions.channels.CreateForumTopicRequest(
                            channel=destino, # type: ignore
                            title=nome_topico_indice,
                            random_id=int.from_bytes(os.urandom(8), 'big', signed=True)
                        ))
                        config['id_topico_indice'] = updates.updates[0].id
                        print_success(f"Tópico '{nome_topico_indice}' criado com sucesso.")
                    except Exception as e:
                        print_error(f"Não foi possível criar o tópico: {e}")
                        continue # Tenta de novo
                else:
                    config['id_topico_indice'] = resp_indice['topico_id']
                
                step = 5

            # --- PASSO 5: CONFIGURAÇÕES ---
            elif step == 5:
                print_info("ETAPA 5: CONFIGURAÇÕES ADICIONAIS")
                
                perg_case = [inquirer.List('force_uppercase', 
                                          message="Como deve ser a formatação do nome dos NOVOS tópicos?", 
                                          choices=[
                                              ('Manter original (ex: "Meu Tópico")', False),
                                              ('FORÇAR MAIÚSCULO (ex: "MEU TÓPICO")', True),
                                              ('🔙 Voltar', 'back')
                                          ])]
                resp_case = inquirer.prompt(perg_case)
                if not resp_case or resp_case['force_uppercase'] == 'back': 
                    step = 4
                    continue
                config['force_uppercase'] = resp_case['force_uppercase']

                perg_colisao = [inquirer.List('modo_colisao', 
                                             message="Se um tópico correspondente já existir no destino?", 
                                             choices=[
                                                 ('❓ Perguntar para cada tópico (Manual)', 'ask'),
                                                 ('🔄 Atualizar o existente automaticamente (Recomendado)', 'update'),
                                                 ('🆕 Criar um novo duplicado (Ignorar existente)', 'new')
                                             ])]
                resp_colisao = inquirer.prompt(perg_colisao)
                if not resp_colisao: return None
                config['modo_colisao'] = resp_colisao['modo_colisao']

                if config['modo_colisao'] != 'new':
                    perg_audit = [inquirer.List('modo_auditoria', 
                                                 message="Sobre as Auditorias (Cache) ao atualizar tópicos:", 
                                                 choices=[
                                                     ('⚡ Usar cache existente sempre que possível (Rápido)', 'cache'),
                                                     ('🔄 Forçar nova auditoria sempre (Mais seguro/lento)', 'force'),
                                                     ('❓ Perguntar para cada tópico', 'ask')
                                                 ])]
                    resp_audit = inquirer.prompt(perg_audit)
                    if not resp_audit: return None
                    config['modo_auditoria'] = resp_audit['modo_auditoria']
                else:
                    config['modo_auditoria'] = 'cache'

                num_str = inquirer.text(message="A partir de qual número o índice deve começar?", default="1")
                config['numero_indice_inicio'] = int(num_str) if num_str.isdigit() else 1

                perg_ordem = [inquirer.List('ordem', message="Ordem de cópia das mídias:", choices=[
                    ('CRESCENTE (Mais antigas primeiro)', 'crescente'),
                    ('DECRESCENTE (Mais novas primeiro)', 'decrescente')
                ])]
                resp_ordem = inquirer.prompt(perg_ordem)
                config['ordem'] = resp_ordem['ordem']

                pausa_str = inquirer.text(message="Pausar a cada quantas mídias enviadas? (0 para não pausar)", default="100")
                config['pausa_a_cada'] = int(pausa_str) if pausa_str.isdigit() else 0
                if config['pausa_a_cada'] > 0:
                    tempo_pausa_str = inquirer.text(message="Duração da pausa em segundos?", default="60")
                    config['tempo_pausa_segundos'] = int(tempo_pausa_str) if tempo_pausa_str.isdigit() else 60

                print_success("CONFIGURAÇÃO CONCLUÍDA!")
                return config

        except (KeyboardInterrupt, TypeError) as e:
            if isinstance(e, TypeError):
                print_error(f"Erro de tipo inesperado: {e}")
                import traceback
                traceback.print_exc()
            print_warning("\nConfiguração da tarefa cancelada.")
            return None
        except Exception as e:
            print_error(f"Erro inesperado durante a configuração: {e}")
            return None

def prompt_deletar_auditoria():
    """Mostra a lista de auditorias salvas para deleção múltipla."""
    print_section_header("Deletar Auditoria(s) Salva(s)")
    
    auditorias = listar_auditorias_salvas()
    
    if not auditorias:
        print_warning("Nenhuma auditoria salva encontrada.")
        input("Pressione Enter para voltar...")
        return None
        
    choices = []
    for aud in sorted(auditorias, key=lambda x: x['nome_grupo']):
        data = aud['data_auditoria'].split('T')[0]
        label = f"'{aud['nome_grupo']}' ({aud['total_midias']} mídias, em {data})"
        choices.append((label, aud['filename']))
    
    pergunta = [
        inquirer.Checkbox('auditorias_a_deletar', 
                      message="Selecione as auditorias para DELETAR (use a barra de espaço). Pressione Enter sem selecionar nada para voltar.", 
                      choices=choices)
    ]
    resposta = inquirer.prompt(pergunta)
    
    if not resposta or not resposta['auditorias_a_deletar']:
        return None
        
    return resposta['auditorias_a_deletar']

def prompt_selecionar_datas_para_copia(grupo_id):
    """
    Mostra um prompt para selecionar datas e, opcionalmente, filtrar por horário.
    Retorna um dicionário: {'YYYY-MM-DD': 'all' | ['09', '10', ...]}
    """
    from . import gerenciador_dados as dados
    print_section_header("Filtro de Cópia por Data e Horário")
    
    auditoria = dados.load_audit(grupo_id)
    midias_por_data = auditoria.get('midias_por_data')
    
    if not midias_por_data:
        print_warning("Nenhum resumo de mídias por data encontrado na auditoria.")
        print_info("O programa irá copiar todas as mídias. Pressione Enter para continuar.")
        input()
        return {'all': 'all'} # Retorno especial para 'tudo'
        
    # Ordena as datas da mais nova para a mais antiga
    datas_ordenadas = sorted(midias_por_data.keys(), reverse=True)
    
    choices = [
        (f"{data} ({midias_por_data[data]} mídias)", data) 
        for data in datas_ordenadas
    ]
    
    pergunta_datas = [
        inquirer.Checkbox('datas_selecionadas',
                          message="Selecione as datas que deseja copiar (use Espaço para marcar). Deixe em branco para copiar TUDO.",
                          choices=choices),
    ]
    
    resposta_datas = inquirer.prompt(pergunta_datas)
    
    filtros_finais = {} # Estrutura: {data: 'all' ou [horas]}
    
    if not resposta_datas or not resposta_datas['datas_selecionadas']:
        if inquirer.prompt([inquirer.Confirm('confirm_all', message="Nenhuma data selecionada. Deseja copiar mídias de TODAS as datas?", default=True)]).get('confirm_all', True):
            return {'all': 'all'}
        else:
            return {} # Cancelado/Vazio
    
    # Se selecionou datas, pergunta se quer filtrar horários
    datas_selecionadas = resposta_datas['datas_selecionadas']
    
    refinar_horarios = False
    if len(datas_selecionadas) > 0:
        refinar_horarios = inquirer.prompt([
            inquirer.Confirm('refinar', 
                             message=f"Deseja filtrar horários específicos para as {len(datas_selecionadas)} datas selecionadas?", 
                             default=False)
        ]).get('refinar', False)

    # Processa cada data
    if not refinar_horarios:
        for data in datas_selecionadas:
            filtros_finais[data] = 'all'
    else:
        # Carrega todas as mídias para análise de horário
        # (Isso já está em memória via load_audit, mas precisamos iterar)
        all_midias = auditoria.get('midias_catalogadas', {}).values()
        
        for data in datas_selecionadas:
            print_info(f"\nAnalisando horários para: {data}...")
            
            # Agrupa mídias desta data por hora
            horas_encontradas = {} # {'14': 10, '15': 5}
            for m in all_midias:
                if m.get('data') and m['data'].startswith(data):
                    hora = m['data'].split('T')[1][:2] # Pega HH de YYYY-MM-DDTHH:MM:SS
                    horas_encontradas[hora] = horas_encontradas.get(hora, 0) + 1
            
            if not horas_encontradas:
                print_warning(f"Nenhuma mídia encontrada para {data} durante análise de horas (estranho).")
                filtros_finais[data] = 'all'
                continue

            # Cria menu de seleção de horas
            choices_horas = sorted([
                (f"{h}h - {h}h59 ({count} mídias)", h)
                for h, count in horas_encontradas.items()
            ])
            
            q_horas = [
                inquirer.Checkbox('horas_sel',
                                  message=f"Selecione os horários para {data}:",
                                  choices=choices_horas)
            ]
            resp_horas = inquirer.prompt(q_horas)
            
            if resp_horas and resp_horas['horas_sel']:
                filtros_finais[data] = resp_horas['horas_sel']
                print_success(f"Filtrado: {len(resp_horas['horas_sel'])} faixas de horário selecionadas para {data}.")
            else:
                print_warning(f"Nenhum horário selecionado para {data}. Copiando dia inteiro.")
                filtros_finais[data] = 'all'

    return filtros_finais


async def prompt_organizar_topicos(client, telefone):
    """Prompt para configurar a organização de grupo em tópicos."""
    from src.organizador_topicos import OrganizadorTopicos, criar_forum_novo
    
    print_section_header("Organizar Grupo em Tópicos")
    
    # 1. Selecionar origem (grupo tradicional auditado)
    print_info("\n📥 PASSO 1: Selecione o grupo de ORIGEM (grupo tradicional)")
    origem = await selecionar_grupo_com_auditoria(client, "Selecione o grupo auditado para organizar")
    
    if not origem:
        # Se não tem auditoria, perguntar se quer fazer
        print_warning("Nenhuma auditoria encontrada. Selecione um grupo para auditar primeiro.")
        origem = await selecionar_grupo(client, "Selecione o grupo para auditar", 'groups')
        if not origem:
            return None
    
    # 2. Selecionar destino (fórum existente ou criar novo)
    print_info("\n📤 PASSO 2: Selecione o DESTINO (grupo fórum)")
    
    destino_choice = inquirer.prompt([
        inquirer.List('destino',
                      message="Onde deseja organizar as mídias?",
                      choices=[
                          ('📁 Usar fórum existente', 'existente'),
                          ('➕ Criar novo fórum', 'criar')
                      ])
    ])
    
    if not destino_choice:
        return None
    
    if destino_choice['destino'] == 'criar':
        # Criar novo fórum
        nome_forum = inquirer.prompt([
            inquirer.Text('nome', message="Nome do novo fórum:", default=f"📁 {origem.title} Organizado")
        ])
        
        if not nome_forum:
            return None
        
        destino = await criar_forum_novo(client, nome_forum['nome'])
        if not destino:
            print_error("Falha ao criar fórum")
            return None
    else:
        # Selecionar fórum existente
        destino = await selecionar_grupo(client, "Selecione o grupo FÓRUM de destino", 'forums')
        if not destino:
            return None
    
    # 3. Configurações
    print_info("\n⚙️ PASSO 3: Configurações")
    
    config_prompts = [
        inquirer.Text('midias_por_topico', 
                     message="Quantas mídias por tópico?", 
                     default="1000",
                     validate=lambda _, x: x.isdigit()),
        inquirer.Text('numero_inicio', 
                     message="Número inicial do índice?", 
                     default="1",
                     validate=lambda _, x: x.isdigit()),
        inquirer.Text('pausar_segundos', 
                     message="Pausar quantos segundos?", 
                     default="5",
                     validate=lambda _, x: x.isdigit()),
        inquirer.Text('pausar_a_cada', 
                     message="Pausar a cada quantas mídias?", 
                     default="100",
                     validate=lambda _, x: x.isdigit()),
    ]
    
    config_resp = inquirer.prompt(config_prompts)
    if not config_resp:
        return None
    
    # 4. Tipos de arquivo
    tipos_choices = [
        ('📷 Fotos', 'photo'),
        ('🎥 Vídeos', 'video'),
        ('📄 Documentos', 'document'),
        ('🎵 Áudios', 'audio'),
        ('🎬 GIFs', 'gif'),
    ]
    
    tipos_resp = inquirer.prompt([
        inquirer.Checkbox('tipos',
                         message="Quais tipos de arquivo copiar?",
                         choices=tipos_choices,
                         default=['photo', 'video', 'document', 'audio', 'gif'])
    ])
    
    if not tipos_resp or not tipos_resp['tipos']:
        print_warning("Nenhum tipo selecionado. Usando todos.")
        tipos = ['photo', 'video', 'document', 'audio', 'gif']
    else:
        tipos = tipos_resp['tipos']
    
    # 5. Confirmar
    print_info("\n📋 RESUMO DA CONFIGURAÇÃO:")
    print_info(f"   📥 Origem: {origem.title}")
    print_info(f"   📤 Destino: {destino.title}")
    print_info(f"   📁 Mídias por tópico: {config_resp['midias_por_topico']}")
    print_info(f"   🔢 Início do índice: {config_resp['numero_inicio']}")
    print_info(f"   ⏸️ Pausar {config_resp['pausar_segundos']}s a cada {config_resp['pausar_a_cada']} mídias")
    print_info(f"   📎 Tipos: {', '.join(tipos)}")
    
    confirmar = inquirer.prompt([
        inquirer.Confirm('confirmar', message="Iniciar organização?", default=True)
    ])
    
    if not confirmar or not confirmar['confirmar']:
        print_info("Operação cancelada.")
        return None
    
    # Montar configuração
    task_config = {
        'id_origem': origem.id,
        'nome_origem': origem.title,
        'id_destino': destino.id,
        'nome_destino': destino.title,
        'midias_por_topico': int(config_resp['midias_por_topico']),
        'numero_inicio_indice': int(config_resp['numero_inicio']),
        'pausar_segundos': int(config_resp['pausar_segundos']),
        'pausar_a_cada': int(config_resp['pausar_a_cada']),
        'tipos_arquivo': tipos
    }
    
    # Executar
    organizador = OrganizadorTopicos(client, task_config, telefone)
    await organizador.executar()
    
    return True


async def prompt_criar_indice(client):
    """Prompt para criar/atualizar índice de tópicos de um fórum."""
    from src.organizador_topicos import criar_indice_topicos
    from src.criador_indice_melhorado import criar_indice_melhorado
    
    print_section_header("Criar/Atualizar Índice de Tópicos")
    
    # Escolher versão
    versao_resp = inquirer.prompt([
        inquirer.List('versao',
                     message="Qual versão do criador de índice usar?",
                     choices=[
                         ('🎨 Avançada (+ opções, estatísticas, filtros)', 'melhorada'),
                         ('⚡ Rápida (padrão, simples)', 'simples'),
                         ('🔙 Cancelar', 'cancelar')
                     ])
    ])
    
    if not versao_resp or versao_resp['versao'] == 'cancelar':
        return None
    
    versao = versao_resp['versao']
    
    # 1. Selecionar fórum
    print_info("\n📁 Selecione o grupo FÓRUM para criar o índice:")
    forum = await selecionar_grupo(client, "Selecione o grupo fórum", 'forums')
    
    if not forum:
        return None
    
    # 2. Buscar tópicos para selecionar onde criar o índice
    print_info("\n📋 Buscando tópicos do fórum...")
    topicos = await get_all_forum_topics(client, forum)
    
    if not topicos:
        print_warning("Nenhum tópico encontrado. Criando tópico de índice...")
        topico_id = None
    else:
        # Opções: criar novo ou usar existente
        choices = [('➕ Criar novo tópico "📋 ÍNDICE"', 'criar')]
        choices += [(f"📌 {t.title}", t.id) for t in topicos]
        
        resp = inquirer.prompt([
            inquirer.List('topico',
                         message="Onde criar o índice?",
                         choices=choices)
        ])
        
        if not resp:
            return None
        
        if resp['topico'] == 'criar':
            # Criar tópico de índice
            from telethon import functions
            from datetime import datetime
            
            try:
                updates = await client(functions.channels.CreateForumTopicRequest(
                    channel=forum,
                    title="📋 ÍNDICE",
                    random_id=int(datetime.now().timestamp() * 1000)
                ))
                
                topico_id = None
                for update in updates.updates:
                    if hasattr(update, 'id'):
                        topico_id = update.id
                        break
                
                print_success(f"✅ Tópico de índice criado (ID: {topico_id})")
            except Exception as e:
                print_error(f"Erro ao criar tópico: {e}")
                return None
        else:
            topico_id = resp['topico']
    
    # 3. Criar índice (versão escolhida)
    if versao == 'melhorada':
        await criar_indice_melhorado(client, forum, topico_id)
    else:
        await criar_indice_topicos(client, forum, topico_id)
    
    return True


async def prompt_deletar_topicos(client):
    """Prompt para deletar tópicos de um fórum."""
    from src.organizador_topicos import deletar_topicos
    
    print_section_header("Deletar Tópicos")
    
    # 1. Selecionar fórum (apenas onde é admin/dono)
    print_info("\n📁 Selecione o grupo FÓRUM (apenas onde você é admin/dono):")
    forum = await selecionar_grupo(client, "Selecione o grupo fórum", 'forums_admin')
    
    if not forum:
        return None
    
    # 2. Buscar tópicos
    print_info("\n📋 Buscando tópicos do fórum...")
    topicos = await get_all_forum_topics(client, forum)
    
    if not topicos:
        print_warning("Nenhum tópico encontrado.")
        return None
    
    # Filtrar tópico General (ID 1)
    topicos_filtrados = [t for t in topicos if t.id != 1]
    
    if not topicos_filtrados:
        print_warning("Nenhum tópico disponível para deletar (apenas General).")
        return None
    
    # 3. Selecionar tópicos para deletar (checkbox)
    choices = [(f"📌 {t.title}", t.id) for t in topicos_filtrados]
    
    resp = inquirer.prompt([
        inquirer.Checkbox('topicos',
                         message="Selecione os tópicos para DELETAR (use espaço para marcar):",
                         choices=choices)
    ])
    
    if not resp or not resp['topicos']:
        print_info("Nenhum tópico selecionado.")
        return None
    
    # 4. Confirmar
    print_warning(f"\n⚠️ ATENÇÃO: Você vai deletar {len(resp['topicos'])} tópico(s)!")
    
    confirmar = inquirer.prompt([
        inquirer.Confirm('confirmar', 
                        message="Tem certeza que deseja deletar esses tópicos? Esta ação é IRREVERSÍVEL!", 
                        default=False)
    ])
    
    if not confirmar or not confirmar['confirmar']:
        print_info("Operação cancelada.")
        return None
    
    # 5. Deletar
    print_info(f"\n🗑️ Deletando {len(resp['topicos'])} tópico(s)...")
    await deletar_topicos(client, forum, resp['topicos'])
    
    return True


async def prompt_criar_grupos_massa(client):
    """
    Prompt para criar múltiplos grupos (Tradicional ou Fórum) de uma vez.
    """
    from src.criador_grupos import CriadorGrupos
    
    print_section_header("✨ CRIAR GRUPOS EM MASSA")
    print_info("Esta ferramenta cria grupos com numeração sequencial.")
    print_info("Configurações aplicadas automaticamente:")
    print_info(" - Privado (Supergrupo)")
    print_info(" - Histórico Visível para novos membros")
    print_info(" - Proibido salvar conteúdo (NoForwards)")
    print_info(" - Membros sem permissão de falar/enviar mídia")
    
    # 1. Tipo de Grupo
    tipo_resp = inquirer.prompt([
        inquirer.List('tipo', message="Qual tipo de grupo criar?",
                     choices=[
                         ('💬 Fórum (Com Tópicos)', 'forum'),
                         ('👥 Tradicional (Simples)', 'tradicional')
                     ])
    ])
    if not tipo_resp: return
    tipo = tipo_resp['tipo']

    # 2. Nome Base
    nome_resp = inquirer.prompt([
        inquirer.Text('nome', message="Nome base dos grupos (ex: 'Meu Canal VIP')")
    ])
    if not nome_resp or not nome_resp['nome']:
        print_warning("Nome inválido.")
        return
    nome_base = nome_resp['nome']

    # 3. Quantidade
    qtd_resp = inquirer.prompt([
        inquirer.Text('qtd', message="Quantos grupos deseja criar? (ex: 5)", 
                     validate=lambda _, x: x.isdigit() and int(x) > 0)
    ])
    if not qtd_resp: return
    quantidade = int(qtd_resp['qtd'])

    # Confirmação
    print_info(f"\nResumo:")
    print_info(f"Tipo: {tipo.upper()}")
    print_info(f"Nome Base: {nome_base}")
    print_info(f"Quantidade: {quantidade}")
    print_info(f"Exemplo: '1 - {nome_base}', '2 - {nome_base}'...")
    
    
    confirmar = inquirer.prompt([
        inquirer.Confirm('confirmar', message="Confirmar criação?", default=True)
    ])
    
    if not confirmar or not confirmar['confirmar']:
        print_info("Operação cancelada.")
        return

    criador = CriadorGrupos(client)
    await criador.criar_grupos_em_massa(nome_base, quantidade, tipo)
    
    input("\nPressione Enter para continuar...")
