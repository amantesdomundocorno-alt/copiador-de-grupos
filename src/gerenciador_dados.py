# gerenciador_dados.py

import json
import os
import shutil
from .database import db

# --- Constantes de Pastas ---
# Mantemos as pastas para compatibilidade de outros arquivos que possam usá-las,
# mas o foco agora é o DB.
CONTAS_DIR = 'contas'
DADOS_DIR = 'dados'
AUDITORIA_DIR = os.path.join(DADOS_DIR, 'auditorias')
SETTINGS_FILE = os.path.join(DADOS_DIR, 'settings.json')

def criar_pastas_necessarias():
    """Garante que as pastas de dados e contas existam."""
    os.makedirs(CONTAS_DIR, exist_ok=True)
    os.makedirs(DADOS_DIR, exist_ok=True)
    os.makedirs(AUDITORIA_DIR, exist_ok=True)

# --- Settings (Ainda usa JSON simples pois é config local do app) ---
def load_settings():
    if not os.path.exists(SETTINGS_FILE):
        return {}
    try:
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return {}

def save_settings(data):
    with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)

# --- Funções de Tarefas (Migrado para DB) ---

def load_tasks():
    """Carrega todas as tarefas salvas do DB."""
    return db.get_all_tasks()

def save_task(task_key, task_config):
    """Salva ou atualiza uma tarefa específica no DB."""
    db.save_task(task_key, task_config)

def delete_task(task_key):
    """Deleta uma tarefa específica do DB."""
    db.delete_task(task_key)

# --- Funções de Progresso (Migrado para DB) ---



def save_progress(task_key, progress_data):
    """Salva o progresso de uma tarefa específica."""
    # Mapeia os nomes antigos para o esquema do DB se necessário
    mapped_data = {
        'last_id': progress_data.get('ultimo_id_copiado', 0),
        'total_copied': progress_data.get('total_midias_copiadas', 0),
        'id_msg_indice': progress_data.get('id_msg_indice'),
        'pending_index': progress_data.get('indice_pendentes', 0),
        'pending_list': progress_data.get('ids_pendentes', []) # Usado no inteligente
    }
    db.save_progress(task_key, mapped_data)

def get_task_progress(task_key):
    """Obtém o progresso de uma tarefa específica."""
    row = db.get_progress(task_key)
    if not row:
        return {}
    
    # Mapeia de volta para o formato esperado pelo código antigo
    return {
        'ultimo_id_copiado': row['last_id'],
        'total_midias_copiadas': row['total_copied'],
        'id_msg_indice': row['id_msg_indice'],
        'indice_pendentes': row['pending_index'],
        'ids_pendentes': row['pending_list']
    }

def set_task_active(task_key, is_active):
    """Define se uma tarefa está ativa (running) ou parada."""
    status = 'running' if is_active else 'stopped'
    db.set_task_status(task_key, status)

def get_active_tasks():
    """Retorna lista de tarefas que estavam rodando."""
    return db.get_active_tasks()

# --- Funções de Auditoria (Migrado para DB) ---

def load_audit(grupo_id):
    """
    Carrega a auditoria do DB e converte para o formato de dicionário
    esperado pelo código legado (AuditoriaGrupo e Comparador).
    """
    midias = db.get_all_media(grupo_id)
    
    # Buscar metadados da auditoria
    audit_meta = db.get_audit_metadata(grupo_id)
    
    # Reconstrói a estrutura antiga: dict[msg_id] = {info...}
    audit_dict = {
        'grupo_id': grupo_id,
        'nome_grupo': audit_meta['channel_name'] if audit_meta else 'Desconhecido',
        'data_auditoria': audit_meta['last_audited_at'] if audit_meta else 'N/A',
        'total_midias': len(midias),
        'midias_catalogadas': {},
        'midias_por_data': {}
    }

    for m in midias:
        msg_id = m['message_id']
        audit_dict['midias_catalogadas'][msg_id] = {
            'id': msg_id,
            'tipo': 'media',
            'tamanho': m['file_size'],
            'data': m['date'],
            'assinatura': m['signature'],
            'duracao': m['duration'],
            'dimensoes': (m['width'], m['height']) if m['width'] else None,
            'nome_arquivo': m['file_name']
        }
        
        # Agrupamento por data
        if m['date']:
            data_dia = m['date'].split('T')[0]
            audit_dict['midias_por_data'][data_dia] = audit_dict['midias_por_data'].get(data_dia, 0) + 1
            
    return audit_dict