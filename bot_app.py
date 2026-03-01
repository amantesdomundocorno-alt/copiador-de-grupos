# bot_app.py
# Ponto de entrada para o Copiador via Bot do Telegram (ideal para Servidores Cloud)
# Substitui o main.py interativo por uma interface de botões no Telegram.

import asyncio
import logging
import os
import traceback
from telethon import TelegramClient, events, Button
from src import gerenciador_dados as dados
from src.database import db
from src.gerenciador_contas import GerenciadorContas
from src.clonador_completo import ClonadorCompleto
from src.copiador_inteligente import CopiadorInteligente
from src.auditoria import AuditoriaGrupo, deletar_auditoria_salva
from src import utils

from src.logger import get_logger
logger = get_logger()

# ==================== CONFIGURAÇÕES ====================
BOT_TOKEN = "8657658251:AAH6Cw05_a-lhtmatFDbwdJyMzE-MDdrQuA"
BOT_PASSWORD = "Ar22052018@"
BOT_SESSION_NAME = "dados/remote_bot_session"

# Variáveis globais
bot_client = None
user_client = None
user_telefone = None

# ==================== ESTADO DE CONVERSAS ====================
# Armazena o estado de cada usuário para fluxos multi-etapa.
# Formato: { user_id: { 'flow': 'clonar', 'step': 'aguardando_origem', 'data': {...} } }
user_states = {}

def get_state(user_id):
    return user_states.get(user_id, {})

def set_state(user_id, flow, step, data=None):
    if data is None:
        data = user_states.get(user_id, {}).get('data', {})
    user_states[user_id] = {'flow': flow, 'step': step, 'data': data}

def clear_state(user_id):
    user_states.pop(user_id, None)

# ==================== TECLADOS ====================

def get_main_menu_keyboard():
    return [
        [Button.inline("🚀 Iniciar Nova Tarefa de Cópia", data="menu_nova_tarefa")],
        [Button.inline("🔄 Clonar Grupo Completo", data="menu_clonar")],
        [Button.inline("✨ Copiar Tópicos de Fórum", data="menu_copiar_topicos")],
        [Button.inline("📁 Organizar Grupo em Tópicos", data="menu_organizar")],
        [Button.inline("📋 Criar/Atualizar Índice", data="menu_indice")],
        [Button.inline("🗑️ Deletar Tópicos", data="menu_del_topicos")],
        [Button.inline("✨ Criar Grupos em Massa", data="menu_criar_grupos")],
        [Button.inline("🔄 Executar Tarefa Salva", data="menu_tarefas")],
        [Button.inline("📊 Gerenciar Auditorias", data="menu_auditoria")],
        [Button.inline("📈 Estatísticas do Sistema", data="menu_stats")],
        [Button.inline("⚠️ Ver Mídias que Falharam", data="menu_falhas")],
        [Button.inline("💾 Fazer Backup Manual", data="menu_backup")],
        [Button.inline("⚙️ Gerenciar Contas", data="menu_contas")]
    ]

def btn_voltar():
    return [Button.inline("🔙 Voltar ao Menu", data="menu_principal")]

async def send_menu(event, text="📋 **Menu Principal**\nO que deseja fazer?"):
    """Envia ou edita a mensagem do menu principal."""
    try:
        await event.edit(text, buttons=get_main_menu_keyboard(), parse_mode='md')
    except Exception:
        await event.respond(text, buttons=get_main_menu_keyboard(), parse_mode='md')

# ==================== UTILITÁRIOS DE GRUPOS ====================

async def listar_grupos_botoes(event, prompt, callback_prefix, group_type='any', page=0):
    """Lista os grupos do userbot como botões inline paginados."""
    global user_client
    
    all_chats = []
    async for dialog in user_client.iter_dialogs():
        if not (dialog.is_group or dialog.is_channel):
            continue
        entity = dialog.entity
        is_forum = hasattr(entity, 'forum') and entity.forum
        is_channel = hasattr(entity, 'broadcast') and entity.broadcast
        
        if group_type == 'forum' and not is_forum:
            continue
        elif group_type == 'traditional' and is_forum:
            continue
            
        all_chats.append(entity)
    
    # Paginar (8 por página)
    PAGE_SIZE = 8
    total_pages = max(1, (len(all_chats) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = min(page, total_pages - 1)
    
    start = page * PAGE_SIZE
    end = start + PAGE_SIZE
    page_chats = all_chats[start:end]
    
    buttons = []
    for chat in page_chats:
        prefix = "📁" if hasattr(chat, 'forum') and chat.forum else "💬"
        label = f"{prefix} {chat.title[:35]}"
        buttons.append([Button.inline(label, data=f"{callback_prefix}_{chat.id}")])
    
    # Navegação
    nav_row = []
    if page > 0:
        nav_row.append(Button.inline("⬅️ Anterior", data=f"{callback_prefix}_page_{page-1}"))
    nav_row.append(Button.inline(f"📄 {page+1}/{total_pages}", data="noop"))
    if page < total_pages - 1:
        nav_row.append(Button.inline("➡️ Próxima", data=f"{callback_prefix}_page_{page+1}"))
    buttons.append(nav_row)
    
    buttons.append([Button.inline("🔍 Buscar por Nome", data=f"{callback_prefix}_search")])
    buttons.append([Button.inline("🔙 Cancelar", data="menu_principal")])
    
    await event.edit(f"📊 {len(all_chats)} grupo(s)\n\n{prompt}", buttons=buttons, parse_mode='md')

async def buscar_grupo_por_texto(user_id, termo, callback_prefix):
    """Filtra grupos pelo nome e retorna botões."""
    global user_client
    
    all_chats = []
    async for dialog in user_client.iter_dialogs():
        if not (dialog.is_group or dialog.is_channel):
            continue
        if termo.lower() in dialog.entity.title.lower():
            all_chats.append(dialog.entity)
    
    buttons = []
    for chat in all_chats[:15]:  # Máximo 15 resultados
        prefix = "📁" if hasattr(chat, 'forum') and chat.forum else "💬"
        label = f"{prefix} {chat.title[:35]}"
        buttons.append([Button.inline(label, data=f"{callback_prefix}_{chat.id}")])
    
    buttons.append([Button.inline("🔙 Cancelar", data="menu_principal")])
    return buttons, len(all_chats)

# ==================== HANDLER: /start ====================

async def handle_start(event):
    user = event.sender
    if db.is_user_authenticated(user.id):
        await event.respond(
            f"Olá, **{user.first_name}**! 👋\nBem-vindo ao Painel de Controle Remoto.\n\nO que deseja fazer?",
            buttons=get_main_menu_keyboard(), parse_mode='md'
        )
    else:
        await event.respond(
            "🔒 **Acesso Restrito.**\nDigite a senha de acesso para utilizar este bot.",
            parse_mode='md'
        )

# ==================== HANDLER: Mensagens de Texto ====================

async def handle_message(event):
    user_id = event.sender_id
    text = event.raw_text.strip()
    
    if text.startswith('/'):
        return

    # --- Autenticação ---
    if not db.is_user_authenticated(user_id):
        if text == BOT_PASSWORD:
            user = await event.get_sender()
            db.authenticate_user(user_id, user.username, user.first_name)
            try:
                await event.delete()
            except:
                pass
            await event.respond(
                "✅ **Acesso concedido!** Bem-vindo ao sistema.",
                buttons=get_main_menu_keyboard(), parse_mode='md'
            )
        else:
            await event.respond("❌ Senha incorreta.")
        return

    # --- Estados de Conversação ---
    state = get_state(user_id)
    flow = state.get('flow')
    step = state.get('step')
    data = state.get('data', {})

    # Busca de grupo por nome
    if step == 'buscando_grupo':
        callback_prefix = data.get('callback_prefix', 'selorigem')
        buttons, count = await buscar_grupo_por_texto(user_id, text, callback_prefix)
        if count == 0:
            await event.respond(f"Nenhum grupo encontrado com '{text}'. Tente outro nome.")
        else:
            await event.respond(f"🔍 {count} resultado(s) para '{text}':", buttons=buttons)
        return

    # Clonar: aguardando nome do grupo
    if flow == 'clonar' and step == 'aguardando_nome_grupo':
        data['nome_grupo'] = text
        set_state(user_id, 'clonar', 'aguardando_legendas', data)
        await event.respond(
            f"Nome definido: **{text}**\n\nCopiar legendas das mídias?",
            buttons=[
                [Button.inline("✅ Sim", data="clonar_legendas_sim")],
                [Button.inline("❌ Não", data="clonar_legendas_nao")]
            ], parse_mode='md'
        )
        return

    # Clonar: aguardando lote_size
    if flow == 'clonar' and step == 'aguardando_lote':
        if not text.isdigit() or int(text) < 1:
            await event.respond("Por favor, envie um número válido (ex: 10)")
            return
        data['lote_size'] = int(text)
        set_state(user_id, 'clonar', 'aguardando_pausa', data)
        await event.respond("⏱️ Quantos segundos de pausa entre lotes? (recomendado: 3-15)")
        return

    # Clonar: aguardando pausa
    if flow == 'clonar' and step == 'aguardando_pausa':
        if not text.isdigit():
            await event.respond("Por favor, envie um número (ex: 5)")
            return
        data['pausa'] = int(text)
        set_state(user_id, 'clonar', 'confirmacao', data)
        
        destino_nome = data.get('destino_nome', data.get('nome_grupo', 'Novo Grupo'))
        resumo = (
            f"📋 **Resumo da Clonagem:**\n"
            f"▫️ Origem: {data.get('origem_nome', '?')}\n"
            f"▫️ Destino: {destino_nome}\n"
            f"▫️ Legendas: {'Sim' if data.get('legendas') else 'Não'}\n"
            f"▫️ Lote: {data['lote_size']} mídias\n"
            f"▫️ Pausa: {data['pausa']}s\n"
            f"▫️ Auditoria: {'Sim' if data.get('auditar') else 'Não'}\n\n"
            f"Confirma?"
        )
        await event.respond(resumo, buttons=[
            [Button.inline("✅ Confirmar e Iniciar", data="clonar_confirmar")],
            [Button.inline("❌ Cancelar", data="menu_principal")]
        ], parse_mode='md')
        return

    # Criar Grupos em Massa: aguardando nomes
    if flow == 'criar_grupos' and step == 'aguardando_nomes':
        nomes = [n.strip() for n in text.split('\n') if n.strip()]
        if not nomes:
            await event.respond("Envie ao menos um nome de grupo.")
            return
        data['nomes'] = nomes
        set_state(user_id, 'criar_grupos', 'confirmacao', data)
        await event.respond(
            f"Criar **{len(nomes)}** grupo(s)?\n\n" + "\n".join(f"• {n}" for n in nomes),
            buttons=[
                [Button.inline("✅ Criar Todos", data="criar_grupos_confirmar")],
                [Button.inline("❌ Cancelar", data="menu_principal")]
            ], parse_mode='md'
        )
        return

# ==================== HANDLER: CALLBACKS ====================

async def handle_callback(event):
    global user_client
    user_id = event.sender_id
    
    if not db.is_user_authenticated(user_id):
        await event.answer("🔒 Acesso negado.", alert=True)
        return
    
    data_str = event.data.decode('utf-8')
    state = get_state(user_id)
    
    # ======================== MENU PRINCIPAL ========================
    if data_str == "menu_principal":
        clear_state(user_id)
        await send_menu(event)
        return
    
    if data_str == "noop":
        await event.answer()
        return

    # ======================== BACKUP ========================
    if data_str == "menu_backup":
        try:
            utils.criar_backup()
            await event.edit("✅ **Backup realizado com sucesso!**", buttons=[btn_voltar()], parse_mode='md')
        except Exception as e:
            await event.edit(f"❌ Erro no backup: {e}", buttons=[btn_voltar()])
        return

    # ======================== ESTATÍSTICAS ========================
    if data_str == "menu_stats":
        try:
            # Coletar dados
            tarefas = dados.load_tasks()
            total_tarefas = len(tarefas)
            ativas = len(dados.get_active_tasks())
            auditorias = db.get_all_audit_metadata()
            total_auditorias = len(auditorias)
            
            total_midias = 0
            for aud in auditorias:
                total_midias += aud.get('total_media_count', 0)
            
            texto = (
                f"📈 **Estatísticas do Sistema**\n\n"
                f"📋 Tarefas salvas: **{total_tarefas}**\n"
                f"▶️ Tarefas ativas: **{ativas}**\n"
                f"📊 Auditorias: **{total_auditorias}**\n"
                f"🖼️ Mídias catalogadas: **{total_midias:,}**\n"
                f"👤 Conta ativa: `{user_telefone}`"
            )
            await event.edit(texto, buttons=[btn_voltar()], parse_mode='md')
        except Exception as e:
            await event.edit(f"❌ Erro: {e}", buttons=[btn_voltar()])
        return

    # ======================== VER FALHAS ========================
    if data_str == "menu_falhas":
        try:
            tarefas = dados.load_tasks()
            total_falhas = 0
            texto_falhas = "⚠️ **Mídias que Falharam:**\n\n"
            
            for key, cfg in tarefas.items():
                falhas = db.get_copy_failures(key)
                if falhas:
                    total_falhas += len(falhas)
                    texto_falhas += f"📋 `{cfg.get('nome_origem', key)}`: **{len(falhas)}** falha(s)\n"
            
            if total_falhas == 0:
                texto_falhas = "✅ **Nenhuma falha registrada!**\nTodas as cópias foram bem-sucedidas."
            else:
                texto_falhas += f"\n**Total: {total_falhas} falha(s)**"
            
            buttons = []
            if total_falhas > 0:
                buttons.append([Button.inline("🗑️ Marcar Todas como Resolvidas", data="falhas_resolver")])
            buttons.append(btn_voltar())
            
            await event.edit(texto_falhas, buttons=buttons, parse_mode='md')
        except Exception as e:
            await event.edit(f"❌ Erro: {e}", buttons=[btn_voltar()])
        return

    if data_str == "falhas_resolver":
        try:
            utils.marcar_todas_resolvidas()
            await event.edit("✅ Todas as falhas foram marcadas como resolvidas!", buttons=[btn_voltar()])
        except Exception as e:
            await event.edit(f"❌ Erro: {e}", buttons=[btn_voltar()])
        return

    # ======================== GERENCIAR CONTAS ========================
    if data_str == "menu_contas":
        settings = dados.load_settings()
        contas_texto = "⚙️ **Gerenciar Contas**\n\n"
        
        contas = []
        for key, val in settings.items():
            if isinstance(val, dict) and 'telefone' in val:
                contas.append(val['telefone'])
        
        if contas:
            contas_texto += "**Contas cadastradas:**\n"
            for c in contas:
                ativa = " ✅ (ativa)" if c == user_telefone else ""
                contas_texto += f"• `{c}`{ativa}\n"
        else:
            contas_texto += "Nenhuma conta cadastrada.\n"
        
        contas_texto += "\n⚠️ Para adicionar/remover contas, use o terminal (`main.py`) por questões de segurança (precisa digitar código SMS)."
        await event.edit(contas_texto, buttons=[btn_voltar()], parse_mode='md')
        return

    # ======================== AUDITORIA ========================
    if data_str == "menu_auditoria":
        await event.edit(
            "📊 **Gerenciar Auditorias**\nEscolha uma opção:",
            buttons=[
                [Button.inline("➕ Nova Auditoria Completa", data="aud_nova")],
                [Button.inline("🔄 Atualizar Existente", data="aud_atualizar")],
                [Button.inline("👁️ Ver Detalhes", data="aud_detalhes")],
                [Button.inline("➖ Deletar Auditoria", data="aud_deletar")],
                [btn_voltar()]
            ], parse_mode='md'
        )
        return

    if data_str == "aud_nova":
        set_state(user_id, 'auditoria', 'selecionando_grupo', {'acao': 'nova'})
        await listar_grupos_botoes(event, "**Selecione o grupo para AUDITAR:**", "selaud")
        return

    if data_str == "aud_detalhes" or data_str == "aud_atualizar" or data_str == "aud_deletar":
        auditorias = db.get_all_audit_metadata()
        if not auditorias:
            await event.edit("Nenhuma auditoria salva.", buttons=[btn_voltar()])
            return
        
        acao = data_str.split('_')[1]
        set_state(user_id, 'auditoria', 'selecionando_auditoria', {'acao': acao})
        
        buttons = []
        for aud in auditorias[:15]:
            nome = aud.get('channel_name', 'Desconhecido')[:30]
            count = aud.get('total_media_count', 0)
            buttons.append([Button.inline(f"📊 {nome} ({count:,} mídias)", data=f"selaudid_{aud['channel_id']}")])
        buttons.append([btn_voltar()])
        
        acoes = {'detalhes': 'VER DETALHES', 'atualizar': 'ATUALIZAR', 'deletar': 'DELETAR'}
        await event.edit(f"📊 Selecione a auditoria para **{acoes.get(acao, acao)}**:", buttons=buttons, parse_mode='md')
        return

    if data_str.startswith("selaudid_"):
        channel_id = int(data_str.split('_')[1])
        state_data = state.get('data', {})
        acao = state_data.get('acao', 'detalhes')
        
        if acao == 'detalhes':
            meta = db.get_audit_metadata(channel_id)
            stats = db.get_media_stats_by_type(channel_id)
            if meta:
                texto = (
                    f"📊 **Auditoria: {meta['channel_name']}**\n\n"
                    f"🖼️ Total de mídias: **{stats['total']:,}**\n"
                    f"💾 Tamanho: **{stats['tamanho_total_mb']} MB**\n"
                    f"📅 Última auditoria: {meta['last_audited_at']}\n\n"
                )
                if stats['por_tipo']:
                    texto += "**Por tipo:**\n"
                    for tipo, count in stats['por_tipo'].items():
                        texto += f"  • {tipo}: {count:,}\n"
                await event.edit(texto, buttons=[btn_voltar()], parse_mode='md')
            else:
                await event.edit("Auditoria não encontrada.", buttons=[btn_voltar()])
            clear_state(user_id)
            return

        elif acao == 'deletar':
            await event.edit(
                f"⚠️ Tem certeza que deseja deletar esta auditoria?",
                buttons=[
                    [Button.inline("✅ Sim, Deletar", data=f"aud_confirma_del_{channel_id}")],
                    [Button.inline("❌ Cancelar", data="menu_auditoria")]
                ]
            )
            clear_state(user_id)
            return

        elif acao == 'atualizar':
            try:
                grupo = await user_client.get_entity(channel_id)
                await event.edit(f"🔄 Atualizando auditoria de **{grupo.title}**...\nIsso pode demorar.", parse_mode='md')
                auditor = AuditoriaGrupo(user_client, grupo, grupo.title, user_telefone)
                await auditor.auditar_reverso_incremental()
                await event.respond("✅ Auditoria atualizada!", buttons=[btn_voltar()])
            except Exception as e:
                await event.respond(f"❌ Erro: {e}", buttons=[btn_voltar()])
            clear_state(user_id)
            return

    if data_str.startswith("aud_confirma_del_"):
        channel_id = int(data_str.split('_')[3])
        deletar_auditoria_salva(channel_id)
        await event.edit("✅ Auditoria deletada!", buttons=[btn_voltar()])
        return

    if data_str.startswith("selaud_"):
        rest = data_str[7:]
        if rest.startswith("page_"):
            page = int(rest.split('_')[1])
            await listar_grupos_botoes(event, "**Selecione o grupo para AUDITAR:**", "selaud", page=page)
            return
        if rest == "search":
            state_data = state.get('data', {})
            state_data['callback_prefix'] = 'selaud'
            set_state(user_id, state.get('flow', 'auditoria'), 'buscando_grupo', state_data)
            await event.edit("🔍 Digite o nome do grupo para buscar:")
            return
        # Selecionou um grupo
        channel_id = int(rest)
        try:
            grupo = await user_client.get_entity(channel_id)
            await event.edit(f"🔄 Iniciando auditoria completa de **{grupo.title}**...\nIsso pode demorar.", parse_mode='md')
            auditor = AuditoriaGrupo(user_client, grupo, grupo.title, user_telefone)
            await auditor.auditar_completo(force_refresh=True)
            await event.respond("✅ Auditoria concluída!", buttons=[btn_voltar()])
        except Exception as e:
            await event.respond(f"❌ Erro: {e}", buttons=[btn_voltar()])
        clear_state(user_id)
        return

    # ======================== EXECUTAR TAREFA SALVA ========================
    if data_str == "menu_tarefas":
        tarefas = dados.load_tasks()
        if not tarefas:
            await event.edit("📋 Nenhuma tarefa salva encontrada.", buttons=[btn_voltar()])
            return
        
        buttons = []
        from datetime import datetime
        for key, cfg in tarefas.items():
            tipo = "🔄" if cfg.get('tipo') == 'clonagem' else "📋"
            label = f"{tipo} {cfg['nome_origem'][:15]} → {cfg['nome_destino'][:15]}"
            buttons.append([Button.inline(label, data=f"exec_tarefa_{key[:30]}")])
        
        buttons.append([Button.inline("🗑️ Deletar Tarefa", data="del_tarefa_menu")])
        buttons.append([btn_voltar()])
        
        await event.edit("📋 **Tarefas Salvas:**\nSelecione para executar:", buttons=buttons, parse_mode='md')
        return

    if data_str.startswith("exec_tarefa_"):
        task_key_partial = data_str[12:]
        tarefas = dados.load_tasks()
        # Encontrar a task_key completa
        task_key = None
        task_config = None
        for k, cfg in tarefas.items():
            if k.startswith(task_key_partial) or k[:30] == task_key_partial:
                task_key = k
                task_config = cfg
                break
        
        if not task_config:
            await event.edit("❌ Tarefa não encontrada!", buttons=[btn_voltar()])
            return
        
        await event.edit(
            f"▶️ Executar tarefa?\n\n"
            f"📋 {task_config['nome_origem']} → {task_config['nome_destino']}\n"
            f"Tipo: {task_config.get('tipo', 'copia')}",
            buttons=[
                [Button.inline("✅ Executar Agora", data=f"run_tarefa_{task_key[:30]}")],
                [Button.inline("🔙 Voltar", data="menu_tarefas")]
            ]
        )
        return

    if data_str.startswith("run_tarefa_"):
        task_key_partial = data_str[11:]
        tarefas = dados.load_tasks()
        task_key = None
        task_config = None
        for k, cfg in tarefas.items():
            if k.startswith(task_key_partial) or k[:30] == task_key_partial:
                task_key = k
                task_config = cfg
                break
        
        if not task_config:
            await event.edit("❌ Tarefa não encontrada!", buttons=[btn_voltar()])
            return
        
        await event.edit(f"🔄 Executando tarefa...\n{task_config['nome_origem']} → {task_config['nome_destino']}")
        
        try:
            if task_config.get('tipo') == 'clonagem':
                grupo_origem = await user_client.get_entity(task_config['id_origem'])
                grupo_destino = None
                if task_config.get('id_destino'):
                    grupo_destino = await user_client.get_entity(task_config['id_destino'])
                
                clonador = ClonadorCompleto(
                    user_client, grupo_origem,
                    task_config.get('copiar_legendas', True),
                    destino_existente=grupo_destino,
                    auditar_destino=task_config.get('auditar_destino', False)
                )
                clonador.lote_size = task_config.get('lote_size', 10)
                clonador.pausa_segundos = task_config.get('pausa_segundos', 15)
                clonador.album_mode = task_config.get('album_mode', 'copy_origin')
                clonador.album_size = task_config.get('album_size', 10)
                if task_config.get('nome_grupo_customizado'):
                    clonador.nome_grupo_customizado = task_config['nome_grupo_customizado']
                clonador.task_key = task_key
                
                dados.set_task_active(task_key, True)
                try:
                    await clonador.run()
                finally:
                    dados.set_task_active(task_key, False)
                
                await event.respond("✅ Tarefa de clonagem concluída!", buttons=[btn_voltar()])
            else:
                dados.set_task_active(task_key, True)
                try:
                    copiador = CopiadorInteligente(user_client, task_config, task_key, None, user_telefone)
                    await copiador.run()
                finally:
                    dados.set_task_active(task_key, False)
                await event.respond("✅ Tarefa de cópia concluída!", buttons=[btn_voltar()])
        except Exception as e:
            logger.error(f"Erro ao executar tarefa: {traceback.format_exc()}")
            await event.respond(f"❌ Erro na execução: {e}", buttons=[btn_voltar()])
        return

    if data_str == "del_tarefa_menu":
        tarefas = dados.load_tasks()
        buttons = []
        for key, cfg in tarefas.items():
            label = f"🗑️ {cfg['nome_origem'][:15]} → {cfg['nome_destino'][:15]}"
            buttons.append([Button.inline(label, data=f"del_tarefa_{key[:30]}")])
        buttons.append([Button.inline("🔙 Voltar", data="menu_tarefas")])
        await event.edit("🗑️ Selecione a tarefa para **deletar**:", buttons=buttons, parse_mode='md')
        return

    if data_str.startswith("del_tarefa_"):
        task_key_partial = data_str[11:]
        tarefas = dados.load_tasks()
        for k in tarefas:
            if k.startswith(task_key_partial) or k[:30] == task_key_partial:
                dados.delete_task(k)
                await event.edit(f"✅ Tarefa deletada!", buttons=[btn_voltar()])
                return
        await event.edit("❌ Tarefa não encontrada.", buttons=[btn_voltar()])
        return

    # ======================== CLONAR GRUPO COMPLETO ========================
    if data_str == "menu_clonar":
        set_state(user_id, 'clonar', 'aguardando_lote', {'step': 'config'})
        await event.edit(
            "🔄 **Clonar Grupo Completo**\n\n"
            "Quantas mídias copiar por lote? (envie o número)\n"
            "Recomendado: 10",
            parse_mode='md'
        )
        return

    # Clonar: selecionar origem
    if data_str.startswith("selorigem_"):
        rest = data_str[10:]
        if rest.startswith("page_"):
            page = int(rest.split('_')[1])
            await listar_grupos_botoes(event, "**1️⃣ Selecione o grupo de ORIGEM:**", "selorigem", page=page)
            return
        if rest == "search":
            state_data = state.get('data', {})
            state_data['callback_prefix'] = 'selorigem'
            set_state(user_id, 'clonar', 'buscando_grupo', state_data)
            await event.edit("🔍 Digite o nome do grupo de ORIGEM:")
            return
        # Selecionou grupo
        group_id = int(rest)
        try:
            grupo = await user_client.get_entity(group_id)
            state_data = state.get('data', {})
            state_data['origem_id'] = group_id
            state_data['origem_nome'] = grupo.title
            set_state(user_id, 'clonar', 'aguardando_destino_tipo', state_data)
            await event.edit(
                f"✅ Origem: **{grupo.title}**\n\nOnde copiar as mídias?",
                buttons=[
                    [Button.inline("🆕 Criar Novo Grupo", data="clonar_dest_novo")],
                    [Button.inline("📁 Grupo Existente", data="clonar_dest_existente")]
                ], parse_mode='md'
            )
        except Exception as e:
            await event.edit(f"❌ Erro ao selecionar grupo: {e}", buttons=[btn_voltar()])
        return

    if data_str == "clonar_dest_novo":
        set_state(user_id, 'clonar', 'aguardando_nome_grupo', state.get('data', {}))
        await event.edit("📝 Digite o nome para o novo grupo:")
        return

    if data_str == "clonar_dest_existente":
        set_state(user_id, 'clonar', 'selecionando_destino', state.get('data', {}))
        await listar_grupos_botoes(event, "**2️⃣ Selecione o grupo de DESTINO:**", "seldestino")
        return

    if data_str.startswith("seldestino_"):
        rest = data_str[11:]
        if rest.startswith("page_"):
            page = int(rest.split('_')[1])
            await listar_grupos_botoes(event, "**2️⃣ Selecione o grupo de DESTINO:**", "seldestino", page=page)
            return
        if rest == "search":
            state_data = state.get('data', {})
            state_data['callback_prefix'] = 'seldestino'
            set_state(user_id, 'clonar', 'buscando_grupo', state_data)
            await event.edit("🔍 Digite o nome do grupo de DESTINO:")
            return
        group_id = int(rest)
        try:
            grupo = await user_client.get_entity(group_id)
            state_data = state.get('data', {})
            state_data['destino_id'] = group_id
            state_data['destino_nome'] = grupo.title
            set_state(user_id, 'clonar', 'aguardando_legendas', state_data)
            await event.edit(
                f"✅ Destino: **{grupo.title}**\n\nCopiar legendas das mídias?",
                buttons=[
                    [Button.inline("✅ Sim", data="clonar_legendas_sim")],
                    [Button.inline("❌ Não", data="clonar_legendas_nao")]
                ], parse_mode='md'
            )
        except Exception as e:
            await event.edit(f"❌ Erro: {e}", buttons=[btn_voltar()])
        return

    if data_str in ("clonar_legendas_sim", "clonar_legendas_nao"):
        state_data = state.get('data', {})
        state_data['legendas'] = (data_str == "clonar_legendas_sim")
        set_state(user_id, 'clonar', 'aguardando_album', state_data)
        await event.edit(
            "📸 Como agrupar as mídias?",
            buttons=[
                [Button.inline("📸 Manter álbuns originais", data="clonar_album_original")],
                [Button.inline("🎨 Álbuns personalizados", data="clonar_album_custom")]
            ]
        )
        return

    if data_str in ("clonar_album_original", "clonar_album_custom"):
        state_data = state.get('data', {})
        state_data['album_mode'] = 'copy_origin' if data_str == "clonar_album_original" else 'manual'
        set_state(user_id, 'clonar', 'aguardando_auditoria', state_data)
        await event.edit(
            "🔍 Auditar destino? (verifica duplicatas, mais lento)",
            buttons=[
                [Button.inline("✅ Sim, Auditar", data="clonar_aud_sim")],
                [Button.inline("❌ Não", data="clonar_aud_nao")]
            ]
        )
        return

    if data_str in ("clonar_aud_sim", "clonar_aud_nao"):
        state_data = state.get('data', {})
        state_data['auditar'] = (data_str == "clonar_aud_sim")
        set_state(user_id, 'clonar', 'confirmacao', state_data)
        
        destino_nome = state_data.get('destino_nome', state_data.get('nome_grupo', 'Novo Grupo'))
        resumo = (
            f"📋 **Resumo da Clonagem:**\n"
            f"▫️ Origem: {state_data.get('origem_nome', '?')}\n"
            f"▫️ Destino: {destino_nome}\n"
            f"▫️ Legendas: {'Sim' if state_data.get('legendas') else 'Não'}\n"
            f"▫️ Lote: {state_data.get('lote_size', 10)} mídias\n"
            f"▫️ Pausa: {state_data.get('pausa', 15)}s\n"
            f"▫️ Auditoria: {'Sim' if state_data.get('auditar') else 'Não'}\n\n"
            f"Confirma?"
        )
        await event.edit(resumo, buttons=[
            [Button.inline("✅ Confirmar e Iniciar", data="clonar_confirmar")],
            [Button.inline("❌ Cancelar", data="menu_principal")]
        ], parse_mode='md')
        return

    if data_str == "clonar_confirmar":
        state_data = state.get('data', {})
        clear_state(user_id)
        
        try:
            grupo_origem = await user_client.get_entity(state_data['origem_id'])
            grupo_destino = None
            
            if state_data.get('destino_id'):
                grupo_destino = await user_client.get_entity(state_data['destino_id'])
            
            await event.edit("🔄 **Iniciando clonagem...**\nVocê receberá atualizações de progresso.", parse_mode='md')
            
            clonador = ClonadorCompleto(
                user_client, grupo_origem,
                state_data.get('legendas', True),
                destino_existente=grupo_destino,
                auditar_destino=state_data.get('auditar', False)
            )
            clonador.lote_size = state_data.get('lote_size', 10)
            clonador.pausa_segundos = state_data.get('pausa', 15)
            clonador.album_mode = state_data.get('album_mode', 'copy_origin')
            clonador.album_size = state_data.get('album_size', 10)
            
            if state_data.get('nome_grupo'):
                clonador.nome_grupo_customizado = state_data['nome_grupo']
            
            task_key = f"clonagem_{state_data['origem_id']}_{state_data.get('destino_id', 'novo')}"
            clonador.task_key = task_key
            
            # Salvar tarefa automaticamente
            task_config = {
                'tipo': 'clonagem',
                'id_origem': state_data['origem_id'],
                'nome_origem': state_data.get('origem_nome', ''),
                'id_destino': state_data.get('destino_id'),
                'nome_destino': state_data.get('destino_nome', state_data.get('nome_grupo', '')),
                'copiar_legendas': state_data.get('legendas', True),
                'auditar_destino': state_data.get('auditar', False),
                'nome_grupo_customizado': state_data.get('nome_grupo'),
                'modo': 'Clonagem Completa',
                'lote_size': state_data.get('lote_size', 10),
                'pausa_segundos': state_data.get('pausa', 15),
                'album_mode': state_data.get('album_mode', 'copy_origin'),
                'album_size': state_data.get('album_size', 10)
            }
            dados.save_task(task_key, task_config)
            dados.set_task_active(task_key, True)
            
            try:
                await clonador.run()
            finally:
                dados.set_task_active(task_key, False)
            
            await event.respond("✅ **Clonagem concluída com sucesso!**", buttons=[btn_voltar()], parse_mode='md')
        except Exception as e:
            logger.error(f"Erro na clonagem: {traceback.format_exc()}")
            await event.respond(f"❌ Erro na clonagem: {e}", buttons=[btn_voltar()])
        return

    # Após configurar lote, próximo passo: selecionar origem
    if data_str == "clonar_proximo_origem":
        await listar_grupos_botoes(event, "**1️⃣ Selecione o grupo de ORIGEM:**", "selorigem")
        return

    # ======================== NOVA TAREFA (Cópia Inteligente) ========================
    if data_str == "menu_nova_tarefa":
        set_state(user_id, 'nova_tarefa', 'tipo_grupo', {})
        await event.edit(
            "🚀 **Nova Tarefa de Cópia**\n\nO grupo de origem é um Fórum ou Tradicional?",
            buttons=[
                [Button.inline("📁 Fórum", data="nt_tipo_forum")],
                [Button.inline("💬 Tradicional", data="nt_tipo_trad")],
                [btn_voltar()]
            ], parse_mode='md'
        )
        return

    if data_str in ("nt_tipo_forum", "nt_tipo_trad"):
        state_data = state.get('data', {})
        state_data['group_type'] = 'forum' if data_str == "nt_tipo_forum" else 'traditional'
        set_state(user_id, 'nova_tarefa', 'selecionando_origem', state_data)
        gtype = state_data['group_type']
        await listar_grupos_botoes(event, "**Selecione o grupo de ORIGEM:**", "ntorigem", group_type=gtype)
        return

    if data_str.startswith("ntorigem_"):
        rest = data_str[9:]
        if rest.startswith("page_"):
            page = int(rest.split('_')[1])
            gtype = state.get('data', {}).get('group_type', 'any')
            await listar_grupos_botoes(event, "**Selecione o grupo de ORIGEM:**", "ntorigem", group_type=gtype, page=page)
            return
        if rest == "search":
            state_data = state.get('data', {})
            state_data['callback_prefix'] = 'ntorigem'
            set_state(user_id, 'nova_tarefa', 'buscando_grupo', state_data)
            await event.edit("🔍 Digite o nome do grupo de ORIGEM:")
            return
        group_id = int(rest)
        grupo = await user_client.get_entity(group_id)
        state_data = state.get('data', {})
        state_data['origem_id'] = group_id
        state_data['origem_nome'] = grupo.title
        set_state(user_id, 'nova_tarefa', 'selecionando_destino', state_data)
        await listar_grupos_botoes(event, f"✅ Origem: **{grupo.title}**\n\n**Selecione o grupo de DESTINO:**", "ntdestino")
        return

    if data_str.startswith("ntdestino_"):
        rest = data_str[10:]
        if rest.startswith("page_"):
            page = int(rest.split('_')[1])
            await listar_grupos_botoes(event, "**Selecione o grupo de DESTINO:**", "ntdestino", page=page)
            return
        if rest == "search":
            state_data = state.get('data', {})
            state_data['callback_prefix'] = 'ntdestino'
            set_state(user_id, 'nova_tarefa', 'buscando_grupo', state_data)
            await event.edit("🔍 Digite o nome do grupo de DESTINO:")
            return
        group_id = int(rest)
        grupo = await user_client.get_entity(group_id)
        state_data = state.get('data', {})
        state_data['destino_id'] = group_id
        state_data['destino_nome'] = grupo.title
        
        task_config = {
            'tipo': 'copia',
            'id_origem': state_data['origem_id'],
            'nome_origem': state_data['origem_nome'],
            'id_destino': group_id,
            'nome_destino': grupo.title,
            'modo': 'Cópia Selecionada',
            'salvar_tarefa': True
        }
        task_key = f"{state_data['origem_id']}_{group_id}"
        dados.save_task(task_key, task_config)
        
        clear_state(user_id)
        
        await event.edit(
            f"✅ **Tarefa configurada e salva!**\n\n"
            f"📋 {state_data['origem_nome']} → {grupo.title}\n\n"
            f"Use **Executar Tarefa Salva** para iniciar.",
            buttons=[
                [Button.inline("▶️ Executar Agora", data=f"run_tarefa_{task_key[:30]}")],
                [btn_voltar()]
            ], parse_mode='md'
        )
        return

    # ======================== COPIAR TÓPICOS / ORGANIZAR / ÍNDICE / DELETAR ========================
    # (Funcionalidades de fórum que dependem de seleção de grupo)
    
    if data_str in ("menu_copiar_topicos", "menu_organizar", "menu_indice", "menu_del_topicos"):
        acoes = {
            "menu_copiar_topicos": ("Copiar Tópicos de Fórum", "topicos_copiar"),
            "menu_organizar": ("Organizar Grupo em Tópicos", "topicos_organizar"),
            "menu_indice": ("Criar/Atualizar Índice", "topicos_indice"),
            "menu_del_topicos": ("Deletar Tópicos", "topicos_deletar")
        }
        titulo, flow_name = acoes[data_str]
        set_state(user_id, flow_name, 'selecionando_grupo', {})
        await listar_grupos_botoes(event, f"**{titulo}**\nSelecione o grupo de FÓRUM:", f"self_{flow_name}", group_type='forum')
        return

    # Seleção de grupo para funções de fórum
    for prefix in ("self_topicos_copiar_", "self_topicos_organizar_", "self_topicos_indice_", "self_topicos_deletar_"):
        if data_str.startswith(prefix):
            rest = data_str[len(prefix):]
            flow_name = prefix.replace("self_", "").rstrip("_")
            
            if rest.startswith("page_"):
                page = int(rest.split('_')[1])
                await listar_grupos_botoes(event, "Selecione o grupo:", f"self_{flow_name}", group_type='forum', page=page)
                return
            if rest == "search":
                state_data = state.get('data', {})
                state_data['callback_prefix'] = f"self_{flow_name}"
                set_state(user_id, flow_name, 'buscando_grupo', state_data)
                await event.edit("🔍 Digite o nome do grupo:")
                return
            
            group_id = int(rest)
            await event.edit(
                f"⚠️ Esta função de fórum (**{flow_name}**) envolve interações complexas de tópicos.\n\n"
                f"Por segurança, execute pelo terminal local usando `main.py`.\n"
                f"Grupo selecionado ID: `{group_id}`",
                buttons=[btn_voltar()], parse_mode='md'
            )
            clear_state(user_id)
            return

    # ======================== CRIAR GRUPOS EM MASSA ========================
    if data_str == "menu_criar_grupos":
        set_state(user_id, 'criar_grupos', 'aguardando_nomes', {})
        await event.edit(
            "✨ **Criar Grupos em Massa**\n\n"
            "Envie os nomes dos grupos, um por linha.\n\n"
            "Exemplo:\n`Grupo VIP 1\nGrupo VIP 2\nGrupo Premium`",
            parse_mode='md'
        )
        return

    if data_str == "criar_grupos_confirmar":
        state_data = state.get('data', {})
        nomes = state_data.get('nomes', [])
        clear_state(user_id)
        
        await event.edit(f"⏳ Criando {len(nomes)} grupo(s)...")
        
        criados = 0
        erros = 0
        for nome in nomes:
            try:
                from telethon.tl.functions.channels import CreateChannelRequest
                result = await user_client(CreateChannelRequest(
                    title=nome,
                    about=f"Grupo criado via Bot Remoto",
                    megagroup=True
                ))
                criados += 1
                await asyncio.sleep(2)  # Pausa para evitar flood
            except Exception as e:
                erros += 1
                logger.error(f"Erro ao criar grupo '{nome}': {e}")
        
        await event.respond(
            f"✅ **Concluído!**\n• Criados: {criados}\n• Erros: {erros}",
            buttons=[btn_voltar()], parse_mode='md'
        )
        return

    # ======================== FALLBACK ========================
    await event.answer("⚙️ Em desenvolvimento!", alert=True)

# ==================== INICIALIZAÇÃO ====================

async def start_clients():
    global bot_client, user_client, user_telefone
    
    dados.criar_pastas_necessarias()
    
    # 1. Iniciar Conta Userbot
    contas_manager = GerenciadorContas()
    user_client, telefone = await contas_manager.login_automatico()
    
    if not user_client or not hasattr(user_client, 'is_connected'):
        logger.error("Nenhuma conta Userbot configurada! Execute main.py localmente para fazer login primeiro.")
        return
    
    user_telefone = telefone
    logger.info(f"✅ Userbot conectado: {telefone}")
    
    # 2. Iniciar Bot
    settings = dados.load_settings()
    # Procurar api_id e api_hash nas settings
    api_id = None
    api_hash = None
    for key, val in settings.items():
        if isinstance(val, dict) and 'api_id' in val:
            api_id = val['api_id']
            api_hash = val['api_hash']
            break
    
    if not api_id:
        logger.error("API ID/HASH não encontrado no settings!")
        return
    
    bot_client = TelegramClient(BOT_SESSION_NAME, int(api_id), api_hash)
    await bot_client.start(bot_token=BOT_TOKEN)
    
    # Registrar handlers
    bot_client.add_event_handler(handle_start, events.NewMessage(pattern='/start'))
    bot_client.add_event_handler(handle_message, events.NewMessage())
    bot_client.add_event_handler(handle_callback, events.CallbackQuery())
    
    logger.info("🚀 Bot de controle online! Mande /start no Telegram.")
    
    # Rodar ambos
    await asyncio.gather(
        bot_client.run_until_disconnected(),
        user_client.run_until_disconnected()
    )

if __name__ == "__main__":
    try:
        asyncio.run(start_clients())
    except KeyboardInterrupt:
        logger.info("Serviço encerrado.")
