# utils.py
# Funções utilitárias do Copiador Indexador

import os
import shutil
import logging
from datetime import datetime, timedelta
from rich.table import Table

from .database import db
from .estilo import console, print_success, print_error, print_warning, print_info, print_section_header


# ============================================================
# BACKUP AUTOMÁTICO DO BANCO DE DADOS
# ============================================================

BACKUP_DIR = 'dados/backups'
DB_FILE = 'dados/copiador.db'
MAX_BACKUPS = 7  # Mantém últimos 7 backups


def criar_backup():
    """
    Cria um backup do banco de dados com data/hora.
    Mantém apenas os últimos MAX_BACKUPS backups.
    """
    if not os.path.exists(DB_FILE):
        print_warning("Banco de dados não encontrado. Nenhum backup criado.")
        return False
    
    os.makedirs(BACKUP_DIR, exist_ok=True)
    
    # Nome do backup com data/hora
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_name = f'copiador_backup_{timestamp}.db'
    backup_path = os.path.join(BACKUP_DIR, backup_name)
    
    try:
        shutil.copy2(DB_FILE, backup_path)
        print_success(f"Backup criado: {backup_name}")
        
        # Limpar backups antigos
        _limpar_backups_antigos()
        return True
    except Exception as e:
        print_error(f"Erro ao criar backup: {e}")
        return False


def _limpar_backups_antigos():
    """Remove backups antigos, mantendo apenas os últimos MAX_BACKUPS."""
    if not os.path.exists(BACKUP_DIR):
        return
    
    backups = sorted([
        f for f in os.listdir(BACKUP_DIR) 
        if f.startswith('copiador_backup_') and f.endswith('.db')
    ], reverse=True)
    
    # Remove backups além do limite
    for backup in backups[MAX_BACKUPS:]:
        try:
            os.remove(os.path.join(BACKUP_DIR, backup))
        except OSError as e:
            logging.warning(f"Não foi possível remover backup antigo {backup}: {e}")


def listar_backups():
    """Lista todos os backups disponíveis."""
    if not os.path.exists(BACKUP_DIR):
        return []
    
    backups = []
    for f in os.listdir(BACKUP_DIR):
        if f.startswith('copiador_backup_') and f.endswith('.db'):
            path = os.path.join(BACKUP_DIR, f)
            size = os.path.getsize(path) / (1024 * 1024)  # MB
            mtime = datetime.fromtimestamp(os.path.getmtime(path))
            backups.append({
                'nome': f,
                'tamanho_mb': round(size, 2),
                'data': mtime.strftime('%d/%m/%Y %H:%M')
            })
    
    return sorted(backups, key=lambda x: x['nome'], reverse=True)


def restaurar_backup(backup_name):
    """Restaura um backup específico."""
    backup_path = os.path.join(BACKUP_DIR, backup_name)
    if not os.path.exists(backup_path):
        print_error(f"Backup não encontrado: {backup_name}")
        return False
    
    try:
        # Fecha conexão atual
        db.close_connection()
        
        # Faz backup do banco atual antes de restaurar
        if os.path.exists(DB_FILE):
            shutil.copy2(DB_FILE, DB_FILE + '.pre_restore')
        
        # Restaura
        shutil.copy2(backup_path, DB_FILE)
        
        # Reinicializa conexão
        db._initialize_db()
        
        print_success(f"Backup restaurado: {backup_name}")
        return True
    except Exception as e:
        print_error(f"Erro ao restaurar backup: {e}")
        return False


# ============================================================
# GERENCIAMENTO DE FALHAS
# ============================================================

def listar_falhas(task_key=None, apenas_nao_resolvidas=True):
    """Lista falhas de cópia, opcionalmente filtradas por tarefa."""
    cursor = db.conn.cursor()
    
    if task_key:
        if apenas_nao_resolvidas:
            cursor.execute(
                'SELECT * FROM copy_failures WHERE task_key = ? AND resolved = 0 ORDER BY failed_at DESC',
                (task_key,)
            )
        else:
            cursor.execute(
                'SELECT * FROM copy_failures WHERE task_key = ? ORDER BY failed_at DESC',
                (task_key,)
            )
    else:
        if apenas_nao_resolvidas:
            cursor.execute('SELECT * FROM copy_failures WHERE resolved = 0 ORDER BY failed_at DESC')
        else:
            cursor.execute('SELECT * FROM copy_failures ORDER BY failed_at DESC')
    
    return [dict(row) for row in cursor.fetchall()]


def exibir_falhas():
    """Exibe tabela de falhas."""
    falhas = listar_falhas(apenas_nao_resolvidas=True)
    
    if not falhas:
        print_success("Nenhuma falha de cópia pendente! 🎉")
        return
    
    table = Table(title=f"Mídias que Falharam ({len(falhas)} pendentes)", border_style="error")
    table.add_column("ID", justify="right", style="dim")
    table.add_column("Tarefa", style="cyan")
    table.add_column("Msg ID", justify="right")
    table.add_column("Erro", style="red", max_width=40)
    table.add_column("Data", style="dim")
    
    for f in falhas[:20]:  # Mostrar apenas últimas 20
        table.add_row(
            str(f['id']),
            f['task_key'][:20] + '...' if len(f['task_key']) > 20 else f['task_key'],
            str(f['message_id']),
            f['error_message'][:40] if f['error_message'] else 'N/A',
            f['failed_at'].split('.')[0] if f['failed_at'] else 'N/A'
        )
    
    if len(falhas) > 20:
        table.add_row("...", f"+{len(falhas) - 20} mais", "...", "...", "...")
    
    console.print(table)


def marcar_todas_resolvidas():
    """Marca todas as falhas como resolvidas."""
    cursor = db.conn.cursor()
    cursor.execute('UPDATE copy_failures SET resolved = 1 WHERE resolved = 0')
    db.conn.commit()
    count = cursor.rowcount
    print_success(f"{count} falhas marcadas como resolvidas.")


def contar_falhas_pendentes():
    """Retorna quantidade de falhas não resolvidas."""
    cursor = db.conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM copy_failures WHERE resolved = 0')
    return cursor.fetchone()[0]


# ============================================================
# ESTATÍSTICAS DE USO
# ============================================================

def obter_estatisticas():
    """Obtém estatísticas gerais do sistema."""
    cursor = db.conn.cursor()
    
    stats = {}
    
    # Total de mídias catalogadas (baseado em audit_metadata para consistência)
    cursor.execute('SELECT SUM(total_media_count) FROM audit_metadata')
    result = cursor.fetchone()[0]
    stats['total_midias_catalogadas'] = result if result else 0
    
    # Total de grupos auditados
    cursor.execute('SELECT COUNT(*) FROM audit_metadata')
    stats['total_grupos_auditados'] = cursor.fetchone()[0]
    
    # Total de tarefas salvas
    cursor.execute('SELECT COUNT(*) FROM tasks')
    stats['total_tarefas'] = cursor.fetchone()[0]
    
    # Falhas pendentes
    cursor.execute('SELECT COUNT(*) FROM copy_failures WHERE resolved = 0')
    stats['falhas_pendentes'] = cursor.fetchone()[0]
    
    # Grupo com mais mídias (baseado em audit_metadata)
    cursor.execute('''
        SELECT channel_name, total_media_count 
        FROM audit_metadata 
        ORDER BY total_media_count DESC 
        LIMIT 1
    ''')
    row = cursor.fetchone()
    if row:
        stats['grupo_mais_midias'] = {'nome': row[0] or 'Desconhecido', 'quantidade': row[1]}
    else:
        stats['grupo_mais_midias'] = None
    
    # Tamanho do banco
    if os.path.exists(DB_FILE):
        stats['tamanho_banco_mb'] = round(os.path.getsize(DB_FILE) / (1024 * 1024), 2)
    else:
        stats['tamanho_banco_mb'] = 0
    
    return stats


def exibir_estatisticas():
    """Exibe dashboard de estatísticas."""
    print_section_header("Estatísticas do Sistema")
    
    stats = obter_estatisticas()
    
    table = Table(border_style="info", show_header=False)
    table.add_column("Métrica", style="cyan")
    table.add_column("Valor", style="green")
    
    table.add_row("📊 Total de Mídias Catalogadas", f"{stats['total_midias_catalogadas']:,}")
    table.add_row("📁 Grupos Auditados", str(stats['total_grupos_auditados']))
    table.add_row("📋 Tarefas Salvas", str(stats['total_tarefas']))
    table.add_row("⚠️ Falhas Pendentes", str(stats['falhas_pendentes']))
    table.add_row("💾 Tamanho do Banco", f"{stats['tamanho_banco_mb']} MB")
    
    if stats['grupo_mais_midias']:
        table.add_row(
            "🏆 Grupo com Mais Mídias", 
            f"{stats['grupo_mais_midias']['nome']} ({stats['grupo_mais_midias']['quantidade']:,})"
        )
    
    console.print(table)
    
    # Listar backups
    backups = listar_backups()
    if backups:
        print_info(f"\n💾 {len(backups)} backup(s) disponível(is). Último: {backups[0]['data']}")


# ============================================================
# MODO SIMULAÇÃO (DRY-RUN)
# ============================================================

async def simular_copia(client, config, auditoria_origem, auditoria_destino, comparador):
    """
    Executa uma simulação da cópia sem realmente copiar nada.
    Mostra o que seria copiado.
    """
    print_section_header("MODO SIMULAÇÃO (Dry-Run)")
    print_warning("⚠️ Nenhuma mídia será copiada. Este é apenas um preview.")
    
    ids_pendentes = comparador.midias_pendentes
    
    if not ids_pendentes:
        print_success("Nada a copiar! Todas as mídias já estão no destino.")
        return
    
    # Estatísticas da simulação
    print_info(f"\n📊 Resumo da Simulação:")
    print_info(f"   • Mídias pendentes: {len(ids_pendentes):,}")
    print_info(f"   • Origem: {config.get('nome_origem', 'N/A')}")
    print_info(f"   • Destino: {config.get('nome_destino', 'N/A')}")
    
    # Estimar tempo
    if config.get('copy_speed') == 'fast':
        tempo_por_midia = 0.5  # segundos
    else:
        tempo_por_midia = 5  # segundos (com pausas)
    
    tempo_estimado = len(ids_pendentes) * tempo_por_midia
    horas = int(tempo_estimado // 3600)
    minutos = int((tempo_estimado % 3600) // 60)
    
    print_info(f"   • Tempo estimado: {horas}h {minutos}min")
    
    # Amostra das primeiras mídias
    print_info(f"\n📌 Amostra das primeiras 10 mídias a serem copiadas:")
    
    amostra = ids_pendentes[:10]
    for i, msg_id in enumerate(amostra, 1):
        try:
            msg = await client.get_messages(config['id_origem'], ids=msg_id)
            if msg:
                tipo = "📷 Foto" if msg.photo else "🎥 Vídeo" if msg.video else "📄 Arquivo"
                data = msg.date.strftime('%d/%m/%Y') if msg.date else 'N/A'
                print(f"   {i}. ID {msg_id} - {tipo} - {data}")
        except:
            print(f"   {i}. ID {msg_id} - (não foi possível obter detalhes)")
    
    if len(ids_pendentes) > 10:
        print(f"   ... e mais {len(ids_pendentes) - 10} mídias")
    
    print_success("\n✅ Simulação concluída. Nenhuma mídia foi copiada.")
