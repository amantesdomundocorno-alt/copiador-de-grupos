import sqlite3
import json
import os
import time
import logging
import threading
from datetime import datetime

DB_FILE = 'dados/copiador.db'

class DatabaseManager:
    _instance = None
    _lock = threading.Lock()  # [S9] Lock para thread-safety

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                # Double-check locking
                if cls._instance is None:
                    cls._instance = super(DatabaseManager, cls).__new__(cls)
                    cls._instance.conn = None
                    cls._instance._db_lock = threading.Lock()  # Lock para operações
                    cls._instance._initialize_db()
        return cls._instance

    def _initialize_db(self):
        """Inicializa o banco de dados e cria as tabelas se não existirem."""
        os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
        self.conn = sqlite3.connect(DB_FILE, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row  # Permite acessar colunas pelo nome
        
        # [S3] Habilitar WAL mode para melhor performance
        self.conn.execute('PRAGMA journal_mode=WAL')
        self.conn.execute('PRAGMA synchronous=NORMAL')
        
        self._create_tables()

    def _create_tables(self):
        cursor = self.conn.cursor()

        # Tabela de Logs de Mídia (Auditoria)
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS media_log (
            channel_id INTEGER,
            message_id INTEGER,
            file_unique_id TEXT,
            file_size INTEGER,
            duration INTEGER,
            width INTEGER,
            height INTEGER,
            file_name TEXT,
            date TEXT,
            grouped_id INTEGER,
            signature TEXT,
            media_type TEXT DEFAULT 'unknown',
            PRIMARY KEY (channel_id, message_id)
        )
        ''')
        
        # Adicionar coluna media_type se não existir (migração)
        try:
            cursor.execute('ALTER TABLE media_log ADD COLUMN media_type TEXT DEFAULT "unknown"')
            logging.info("Migração: coluna 'media_type' adicionada à tabela media_log")
        except sqlite3.OperationalError:
            pass  # Coluna já existe - esperado em execuções subsequentes
        # Índice para busca rápida por assinatura (hash)
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_media_signature ON media_log (signature)')
        # Índice para busca rápida por tamanho (fuzzy matching)
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_media_size ON media_log (file_size)')
        # NOVO: Índice para file_unique_id (detecção de duplicatas manuais)
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_file_unique_id ON media_log (file_unique_id)')
        # NOVO: Índice composto para performance em grupos grandes
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_channel_date ON media_log (channel_id, date)')

        # NOVA TABELA: Metadados de Auditoria (cache para não re-auditar sempre)
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS audit_metadata (
            channel_id INTEGER PRIMARY KEY,
            channel_name TEXT,
            last_audited_at TIMESTAMP,
            last_message_id INTEGER DEFAULT 0,
            total_media_count INTEGER DEFAULT 0,
            is_complete BOOLEAN DEFAULT FALSE,
            account_phone TEXT
        )
        ''')
        
        # Migração: Adicionar coluna account_phone se não existir
        try:
            cursor.execute('ALTER TABLE audit_metadata ADD COLUMN account_phone TEXT')
            logging.info("Migração: coluna 'account_phone' adicionada à tabela audit_metadata")
        except sqlite3.OperationalError:
            pass  # Coluna já existe - esperado em execuções subsequentes

        # NOVA TABELA: Log de falhas de cópia (para revisão posterior)
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS copy_failures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_key TEXT,
            message_id INTEGER,
            error_message TEXT,
            failed_at TIMESTAMP,
            resolved BOOLEAN DEFAULT FALSE
        )
        ''')

        # Tabela de Tarefas
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS tasks (
            task_key TEXT PRIMARY KEY,
            config TEXT,
            status TEXT DEFAULT 'stopped',
            updated_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        try:
            cursor.execute('ALTER TABLE tasks ADD COLUMN created_at TIMESTAMP')
            logging.info("Migração: coluna 'created_at' adicionada à tabela tasks")
        except sqlite3.OperationalError:
            pass  # Coluna já existe

        # Tabela de Progresso
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS progress (
            task_key TEXT PRIMARY KEY,
            last_id INTEGER DEFAULT 0,
            total_copied INTEGER DEFAULT 0,
            id_msg_indice INTEGER,
            pending_index INTEGER DEFAULT 0,
            pending_list TEXT,
            updated_at TIMESTAMP
        )
        ''')

        # Tabela de Usuários Autorizados do Bot
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS bot_users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            authenticated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')

        self.conn.commit()

    # --- Métodos de Mídia (Auditoria) ---

    def insert_media_log(self, media_data):
        """
        Insere ou ignora um log de mídia.
        media_data: dict com chaves correspondentes às colunas.
        """
        keys = ['channel_id', 'message_id', 'file_unique_id', 'file_size', 
                'duration', 'width', 'height', 'file_name', 'date', 'grouped_id', 'signature']
        
        values = [media_data.get(k) for k in keys]
        
        cursor = self.conn.cursor()
        cursor.execute('''
        INSERT OR IGNORE INTO media_log 
        (channel_id, message_id, file_unique_id, file_size, duration, width, height, file_name, date, grouped_id, signature)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', values)
        self.conn.commit()

    def insert_media_logs_batch(self, media_list):
        """Insere múltiplos logs de mídia de uma vez (Performance)."""
        if not media_list:
            return

        cursor = self.conn.cursor()
        cursor.executemany('''
        INSERT OR IGNORE INTO media_log 
        (channel_id, message_id, file_unique_id, file_size, duration, width, height, file_name, date, grouped_id, signature, media_type)
        VALUES (:channel_id, :message_id, :file_unique_id, :file_size, :duration, :width, :height, :file_name, :date, :grouped_id, :signature, :media_type)
        ''', media_list)
        self.conn.commit()

    def get_max_message_id(self, channel_id):
        """Retorna o maior ID de mensagem já auditado para um canal."""
        cursor = self.conn.cursor()
        cursor.execute('SELECT MAX(message_id) as max_id FROM media_log WHERE channel_id = ?', (channel_id,))
        result = cursor.fetchone()
        return result['max_id'] if result and result['max_id'] else 0

    def get_all_media(self, channel_id):
        """Retorna todas as mídias de um canal como uma lista de dicts."""
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM media_log WHERE channel_id = ?', (channel_id,))
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def get_media_by_ids(self, channel_id, message_ids):
        """Retorna detalhes de mídias específicas de um canal."""
        if not message_ids:
            return []
            
        cursor = self.conn.cursor()
        
        # SQLite tem limite de variáveis, então fazemos em lotes
        chunk_size = 900
        todos_detalhes = []
        
        for i in range(0, len(message_ids), chunk_size):
            chunk = message_ids[i:i + chunk_size]
            placeholders = ','.join(['?'] * len(chunk))
            
            cursor.execute(
                f'SELECT * FROM media_log WHERE channel_id = ? AND message_id IN ({placeholders})',
                (channel_id, *chunk)
            )
            rows = cursor.fetchall()
            todos_detalhes.extend([dict(row) for row in rows])
            
        return todos_detalhes

    def count_media(self, channel_id):
        """Retorna a contagem de mídias de um canal."""
        cursor = self.conn.cursor()
        cursor.execute('SELECT COUNT(*) as count FROM media_log WHERE channel_id = ?', (channel_id,))
        return cursor.fetchone()['count']
    
    def get_media_stats_by_type(self, channel_id):
        """Retorna estatísticas detalhadas de mídias por tipo."""
        cursor = self.conn.cursor()
        
        stats = {
            'total': 0,
            'por_tipo': {},
            'por_hora': {},
            'por_data': {},
            'tamanho_total_mb': 0
        }
        
        # Contagem por tipo
        cursor.execute('''
            SELECT media_type, COUNT(*) as count, SUM(file_size) as total_size
            FROM media_log WHERE channel_id = ? 
            GROUP BY media_type
        ''', (channel_id,))
        
        for row in cursor.fetchall():
            tipo = row['media_type'] or 'unknown'
            stats['por_tipo'][tipo] = row['count']
            stats['total'] += row['count']
            if row['total_size']:
                stats['tamanho_total_mb'] += row['total_size']
        
        stats['tamanho_total_mb'] = round(stats['tamanho_total_mb'] / (1024 * 1024), 2)
        
        # Contagem por hora do dia
        cursor.execute('''
            SELECT SUBSTR(date, 12, 2) as hora, COUNT(*) as count
            FROM media_log WHERE channel_id = ? AND date IS NOT NULL
            GROUP BY hora ORDER BY hora
        ''', (channel_id,))
        
        for row in cursor.fetchall():
            if row['hora']:
                stats['por_hora'][row['hora'] + 'h'] = row['count']
        
        # Contagem por data
        cursor.execute('''
            SELECT SUBSTR(date, 1, 10) as data, COUNT(*) as count
            FROM media_log WHERE channel_id = ? AND date IS NOT NULL
            GROUP BY data ORDER BY data DESC LIMIT 30
        ''', (channel_id,))
        
        for row in cursor.fetchall():
            if row['data']:
                stats['por_data'][row['data']] = row['count']
        
        return stats

    # --- Métodos de Tarefa ---

    def save_task(self, task_key, config):
        """Salva ou atualiza uma tarefa."""
        cursor = self.conn.cursor()
        
        cursor.execute('SELECT created_at, status FROM tasks WHERE task_key = ?', (task_key,))
        row = cursor.fetchone()
        now = datetime.now()
        
        created_at = row['created_at'] if row and row['created_at'] else now
        status = row['status'] if row and row['status'] else 'stopped'
        
        cursor.execute('''
        INSERT OR REPLACE INTO tasks (task_key, config, status, updated_at, created_at)
        VALUES (?, ?, ?, ?, ?)
        ''', (task_key, json.dumps(config, ensure_ascii=False), status, now, created_at))
        self.conn.commit()

    def get_task(self, task_key):
        """Recupera uma tarefa."""
        cursor = self.conn.cursor()
        cursor.execute('SELECT config FROM tasks WHERE task_key = ?', (task_key,))
        row = cursor.fetchone()
        return json.loads(row['config']) if row else None

    def get_all_tasks(self):
        """Recupera todas as tarefas."""
        cursor = self.conn.cursor()
        cursor.execute('SELECT task_key, config, status, updated_at, created_at FROM tasks')
        tasks = {}
        for row in cursor.fetchall():
            config = json.loads(row['config'])
            # Adiciona os metadados de tempo no dict para uso na interface
            config['_created_at'] = row['created_at']
            config['_updated_at'] = row['updated_at']
            config['_status'] = row['status']
            tasks[row['task_key']] = config
        return tasks

    def delete_task(self, task_key):
        """Deleta uma tarefa e seu progresso."""
        cursor = self.conn.cursor()
        cursor.execute('DELETE FROM tasks WHERE task_key = ?', (task_key,))
        cursor.execute('DELETE FROM progress WHERE task_key = ?', (task_key,))
        self.conn.commit()

    def set_task_status(self, task_key, status):
        """Atualiza o status de uma tarefa (ex: 'running', 'stopped')."""
        cursor = self.conn.cursor()
        cursor.execute('UPDATE tasks SET status = ?, updated_at = ? WHERE task_key = ?', 
                       (status, datetime.now(), task_key))
        self.conn.commit()

    def get_active_tasks(self):
        """Retorna tarefas marcadas como 'running'."""
        cursor = self.conn.cursor()
        cursor.execute('SELECT task_key, config FROM tasks WHERE status = "running"')
        tasks = []
        for row in cursor.fetchall():
            tasks.append({
                'key': row['task_key'],
                'config': json.loads(row['config'])
            })
        return tasks

    # --- Métodos de Progresso ---

    def save_progress(self, task_key, progress_data):
        """Salva o progresso."""
        pending_list = json.dumps(progress_data.get('pending_list', []), ensure_ascii=False)
        
        cursor = self.conn.cursor()
        cursor.execute('''
        INSERT OR REPLACE INTO progress 
        (task_key, last_id, total_copied, id_msg_indice, pending_index, pending_list, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            task_key,
            progress_data.get('last_id', 0),
            progress_data.get('total_copied', 0),
            progress_data.get('id_msg_indice'),
            progress_data.get('pending_index', 0),
            pending_list,
            datetime.now()
        ))
        self.conn.commit()

    def get_progress(self, task_key):
        """Recupera o progresso."""
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM progress WHERE task_key = ?', (task_key,))
        row = cursor.fetchone()
        if not row:
            return {}
        
        return {
            'last_id': row['last_id'],
            'total_copied': row['total_copied'],
            'id_msg_indice': row['id_msg_indice'],
            'pending_index': row['pending_index'],
            'pending_list': json.loads(row['pending_list']) if row['pending_list'] else []
        }

    def close_connection(self):
        """Fecha a conexão com o banco de dados."""
        if self.conn:
            self.conn.close()
            self.conn = None

    # --- Métodos de Metadados de Auditoria (NOVO) ---

    def save_audit_metadata(self, channel_id, metadata):
        """Salva ou atualiza os metadados de uma auditoria."""
        cursor = self.conn.cursor()
        cursor.execute('''
        INSERT OR REPLACE INTO audit_metadata 
        (channel_id, channel_name, last_audited_at, last_message_id, total_media_count, is_complete, account_phone)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            channel_id,
            metadata.get('channel_name', ''),
            datetime.now(),
            metadata.get('last_message_id', 0),
            metadata.get('total_media_count', 0),
            metadata.get('is_complete', False),
            metadata.get('account_phone', None)
        ))
        self.conn.commit()

    def get_audit_metadata(self, channel_id):
        """Recupera os metadados de uma auditoria."""
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM audit_metadata WHERE channel_id = ?', (channel_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return {
            'channel_id': row['channel_id'],
            'channel_name': row['channel_name'],
            'last_audited_at': datetime.fromisoformat(row['last_audited_at']) if row['last_audited_at'] else None,
            'last_message_id': row['last_message_id'],
            'total_media_count': row['total_media_count'],
            'is_complete': bool(row['is_complete']),
            'account_phone': row['account_phone'] if 'account_phone' in row.keys() else None
        }

    def get_audited_channel_ids(self):
        """Retorna set de channel_ids que possuem auditoria salva."""
        cursor = self.conn.cursor()
        cursor.execute('SELECT channel_id FROM audit_metadata')
        return set(row['channel_id'] for row in cursor.fetchall())

    def get_all_audit_metadata(self):
        """Retorna todos os metadados de auditorias."""
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM audit_metadata ORDER BY last_audited_at DESC')
        return [dict(row) for row in cursor.fetchall()]

    # --- Métodos de Detecção de Duplicatas (NOVO) ---

    def check_duplicate_by_file_unique_id(self, channel_id, file_unique_id):
        """Verifica se uma mídia já existe no destino pelo file_unique_id."""
        if not file_unique_id:
            return False
        cursor = self.conn.cursor()
        cursor.execute(
            'SELECT 1 FROM media_log WHERE channel_id = ? AND file_unique_id = ? LIMIT 1',
            (channel_id, file_unique_id)
        )
        return cursor.fetchone() is not None

    def get_existing_file_unique_ids(self, channel_id):
        """Retorna set de file_unique_ids existentes em um canal (para comparação rápida)."""
        cursor = self.conn.cursor()
        cursor.execute(
            'SELECT file_unique_id FROM media_log WHERE channel_id = ? AND file_unique_id IS NOT NULL',
            (channel_id,)
        )
        return set(row['file_unique_id'] for row in cursor.fetchall())

    def get_existing_signatures(self, channel_id):
        """Retorna set de assinaturas existentes em um canal."""
        cursor = self.conn.cursor()
        cursor.execute(
            'SELECT signature FROM media_log WHERE channel_id = ? AND signature IS NOT NULL',
            (channel_id,)
        )
        return set(row['signature'] for row in cursor.fetchall())

    # --- Métodos de Log de Falhas (NOVO) ---

    def log_copy_failure(self, task_key, message_id, error_message):
        """Registra uma falha de cópia para revisão posterior."""
        cursor = self.conn.cursor()
        cursor.execute('''
        INSERT INTO copy_failures (task_key, message_id, error_message, failed_at)
        VALUES (?, ?, ?, ?)
        ''', (task_key, message_id, error_message, datetime.now()))
        self.conn.commit()

    def get_copy_failures(self, task_key, only_unresolved=True):
        """Recupera falhas de cópia de uma tarefa."""
        cursor = self.conn.cursor()
        if only_unresolved:
            cursor.execute(
                'SELECT * FROM copy_failures WHERE task_key = ? AND resolved = 0 ORDER BY failed_at',
                (task_key,)
            )
        else:
            cursor.execute(
                'SELECT * FROM copy_failures WHERE task_key = ? ORDER BY failed_at',
                (task_key,)
            )
        return [dict(row) for row in cursor.fetchall()]

    def mark_failure_resolved(self, failure_id):
        """Marca uma falha como resolvida."""
        cursor = self.conn.cursor()
        cursor.execute('UPDATE copy_failures SET resolved = 1 WHERE id = ?', (failure_id,))
        self.conn.commit()

    def cleanup_orphaned_media(self):
        """Remove registros de mídia órfãos (sem entrada em audit_metadata)."""
        cursor = self.conn.cursor()
        cursor.execute('''
            DELETE FROM media_log 
            WHERE channel_id NOT IN (SELECT channel_id FROM audit_metadata)
        ''')
        deleted = cursor.rowcount
        self.conn.commit()
        return deleted

    # --- Métodos de Contas do Bot (NOVO) ---
    def authenticate_user(self, user_id, username, first_name):
        """Salva um novo usuário autorizado na base de dados do bot."""
        cursor = self.conn.cursor()
        cursor.execute('''
        INSERT OR REPLACE INTO bot_users (user_id, username, first_name, authenticated_at)
        VALUES (?, ?, ?, ?)
        ''', (user_id, username, first_name, datetime.now()))
        self.conn.commit()
        
    def is_user_authenticated(self, user_id):
        """Verifica se um dado user_id está na lista de autorizados."""
        cursor = self.conn.cursor()
        cursor.execute('SELECT 1 FROM bot_users WHERE user_id = ? LIMIT 1', (user_id,))
        return cursor.fetchone() is not None

db = DatabaseManager()
