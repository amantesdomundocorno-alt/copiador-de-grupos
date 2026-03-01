# auditoria.py
# Sistema de auditoria inteligente com cache e detecção de duplicatas por file_unique_id

import os
import hashlib
from datetime import datetime, timedelta
from telethon import utils
from telethon.tl.types import DocumentAttributeVideo

from .estilo import print_info, print_success, print_error, print_warning
from .database import db


def get_file_unique_id(message):
    """
    Extrai o file_unique_id do Telegram - identificador único global do arquivo.
    Este ID é o MESMO para a mídia, não importa em qual chat ela esteja!
    Perfeito para detectar duplicatas de mídias inseridas manualmente.
    """
    if not message.media:
        return None
    
    try:
        # Para documentos (vídeos, arquivos, etc)
        if hasattr(message.media, 'document') and message.media.document:
            doc = message.media.document
            # O access_hash combinado com o id forma o identificador único
            return f"doc_{doc.id}_{doc.access_hash}"
        
        # Para fotos
        if hasattr(message.media, 'photo') and message.media.photo:
            photo = message.media.photo
            return f"photo_{photo.id}_{photo.access_hash}"
    except Exception:
        pass
    
    return None


def get_media_signature(message):
    """
    Gera uma assinatura baseada em metadados (fallback quando file_unique_id não disponível).
    Combina: tamanho + duração + dimensões + nome
    """
    if not message.media:
        return None
        
    parts = []
    
    # 1. Tamanho do Arquivo
    if hasattr(message.media, 'document') and message.media.document:
        parts.append(str(message.media.document.size))
    elif hasattr(message.media, 'photo') and message.media.photo:
        # Para fotos, usamos o ID como parte da assinatura
        parts.append(f"photo_{message.media.photo.id}")
    
    # 2. Duração (para vídeos/áudios)
    if message.file and hasattr(message.file, 'duration') and message.file.duration:
        parts.append(str(message.file.duration))
        
    # 3. Nome do arquivo (se houver)
    if message.file and hasattr(message.file, 'name') and message.file.name:
        parts.append(message.file.name)
        
    # 4. Dimensões
    w, h = 0, 0
    if hasattr(message, 'video') and message.video:
        for attr in message.video.attributes:
            if isinstance(attr, DocumentAttributeVideo):
                w, h = attr.w, attr.h
                break
        if w and h:
            parts.append(f"{w}x{h}")
            
    elif hasattr(message, 'photo') and message.photo:
        sizes = message.photo.sizes
        if sizes:
            last = sizes[-1]
            if hasattr(last, 'w'):
                parts.append(f"{last.w}x{last.h}")

    if not parts:
        return None
        
    # Cria hash MD5 da string de assinatura
    signature_str = "|".join(parts)
    return hashlib.md5(signature_str.encode()).hexdigest()


def listar_auditorias_salvas():
    """Retorna lista de auditorias salvas do banco de dados."""
    return db.get_all_audit_metadata()


def deletar_auditoria_salva(channel_id):
    """Deleta uma auditoria do banco de dados."""
    try:
        cursor = db.conn.cursor()
        
        # Deletar as mídias catalogadas desse canal
        cursor.execute('DELETE FROM media_log WHERE channel_id = ?', (channel_id,))
        midias_deletadas = cursor.rowcount
        
        # Deletar os metadados de auditoria
        cursor.execute('DELETE FROM audit_metadata WHERE channel_id = ?', (channel_id,))
        
        db.conn.commit()
        
        print_success(f"Auditoria deletada: {midias_deletadas:,} mídias removidas do banco.")
        return True
    except Exception as e:
        print_error(f"Erro ao deletar auditoria: {e}")
        return False


class AuditoriaGrupo:
    """Sistema de auditoria com cache inteligente para evitar re-escanear grupos grandes."""
    
    # Configurações de cache
    CACHE_MAX_AGE_HOURS = 6  # Tempo máximo para considerar cache válido
    
    def __init__(self, client, entity, nome_grupo, account_phone=None):
        self.client = client
        self.entity = entity
        self.grupo_id = entity.id
        self.nome_grupo = nome_grupo
        self.account_phone = account_phone
        self.midias_catalogadas = {} 
        self.midias_por_data = {}
        self.total_midias = 0
        self._max_message_id_scanned = 0
    
    async def auditar(self, modo='auto', max_age_hours=None):
        """
        Executa a auditoria inteligente usando o DB.
        
        Modos:
        - 'auto': Usa cache se disponível e válido, senão faz incremental
        - 'full': Força re-escanear tudo do zero
        - 'incremental': Apenas novas mensagens desde a última auditoria
        """
        if max_age_hours is None:
            max_age_hours = self.CACHE_MAX_AGE_HOURS
            
        print_info(f"Iniciando auditoria para: {self.nome_grupo} (ID: {self.grupo_id})")
        
        # Verificar cache de auditoria
        metadata = db.get_audit_metadata(self.grupo_id)
        
        if metadata and modo == 'auto':
            # Verificar idade do cache
            if metadata['last_audited_at']:
                hours_since = (datetime.now() - metadata['last_audited_at']).total_seconds() / 3600
                
                if hours_since < max_age_hours and metadata['is_complete']:
                    print_success(f"✅ Auditoria recente encontrada ({hours_since:.1f}h atrás).")
                    print_info(f"   Última auditoria: {metadata['total_media_count']:,} mídias")
                    
                    # Perguntar se quer atualizar ou usar cache
                    # Por enquanto, usamos cache automaticamente
                    print_info("   Usando cache existente. Para forçar atualização, use 'Atualizar Auditoria'.")
                    
                    self.total_midias = metadata['total_media_count']
                    self._carregar_do_db_otimizado()
                    return True
                else:
                    print_info(f"⏰ Cache expirado ({hours_since:.1f}h > {max_age_hours}h). Atualizando...")
        
        # Buscar último ID processado
        max_id = db.get_max_message_id(self.grupo_id)
        
        if max_id > 0 and modo != 'full':
            print_info(f"🔄 Auditoria Incremental: Buscando mensagens após ID {max_id}")
            await self._scan_messages(min_id=max_id)
        else:
            print_info("📊 Auditoria Completa: Escaneando todo o histórico...")
            await self._scan_messages(min_id=0)
        
        # Atualizar contagem e metadados
        self.total_midias = db.count_media(self.grupo_id)
        
        # Salvar metadados de auditoria para cache
        # Sempre marca como completa para aparecer na seção de Gerenciar Auditorias
        db.save_audit_metadata(self.grupo_id, {
            'channel_name': self.nome_grupo,
            'last_message_id': self._max_message_id_scanned,
            'total_media_count': self.total_midias,
            'is_complete': True,
            'account_phone': self.account_phone
        })
        
        # Carregar para memória (otimizado)
        self._carregar_do_db_otimizado()
        
        print_success(f"✅ Auditoria concluída! Total de mídias catalogadas: {self.total_midias:,}")
        return True

    async def auditar_completo(self, force_refresh=True):
        """Força uma auditoria completa, ignorando cache."""
        return await self.auditar(modo='full')

    async def auditar_reverso_incremental(self):
        """Atualiza a auditoria com novas mensagens apenas."""
        return await self.auditar(modo='incremental')

    async def _scan_messages(self, min_id=0):
        """Escaneia mensagens e extrai informações de mídia, incluindo file_unique_id."""
        batch = []
        count = 0
        skipped = 0
        
        # Barra de progresso para auditoria
        from tqdm.asyncio import tqdm
        import sys
        
        pbar = tqdm(
            desc="   Catalogando mídias",
            unit=" mídia",
            dynamic_ncols=True,
            file=sys.stderr
        )
        
        try:
            # Configura argumentos para otimizar busca
            iter_args = {'limit': None}
            if min_id > 0:
                iter_args['min_id'] = min_id

            # NOTA: Não usamos reverse=True pois causa bug no Telethon
            async for message in self.client.iter_messages(self.entity, **iter_args):
                # Atualizar max ID escaneado
                if message.id > self._max_message_id_scanned:
                    self._max_message_id_scanned = message.id
                
                # Pular mensagens já processadas (para modo incremental)
                if min_id > 0 and message.id <= min_id:
                    skipped += 1
                    break  # CRÍTICO: Parar imediatamente se encontrar uma mensagem antiga
                    
                if not message.media:
                    continue
                
                # Extrair file_unique_id (NOVO - para detectar duplicatas manuais)
                file_unique_id = get_file_unique_id(message)
                
                # Extrair assinatura de metadados (fallback)
                signature = get_media_signature(message)
                
                # Extrair tamanho
                size = 0
                if hasattr(message.media, 'document') and message.media.document:
                    size = message.media.document.size
                elif hasattr(message.media, 'photo') and message.media.photo:
                    # Tentar obter tamanho da maior versão da foto
                    try:
                        sizes = message.media.photo.sizes
                        if sizes and hasattr(sizes[-1], 'size'):
                            size = sizes[-1].size
                    except:
                        size = 0
                
                # Extrair duração
                duration = 0
                if message.file and hasattr(message.file, 'duration') and message.file.duration:
                    duration = message.file.duration
                
                # Extrair dimensões
                w, h = 0, 0
                if hasattr(message, 'video') and message.video:
                    for attr in message.video.attributes:
                        if isinstance(attr, DocumentAttributeVideo):
                            w, h = attr.w, attr.h
                            break
                elif hasattr(message, 'photo') and message.photo:
                    sizes = message.photo.sizes
                    if sizes:
                        last = sizes[-1]
                        if hasattr(last, 'w'):
                            w, h = last.w, last.h
                
                # Extrair nome do arquivo
                fname = None
                if message.file and hasattr(message.file, 'name'):
                    fname = message.file.name
                
                # NOVO: Detectar tipo de mídia
                media_type = 'unknown'
                if message.photo:
                    media_type = 'photo'
                elif message.video:
                    media_type = 'video'
                elif message.audio:
                    media_type = 'audio'
                elif message.voice:
                    media_type = 'voice'
                elif message.video_note:
                    media_type = 'video_note'
                elif message.sticker:
                    media_type = 'sticker'
                elif message.gif:
                    media_type = 'gif'
                elif message.document:
                    media_type = 'document'

                media_data = {
                    'channel_id': self.grupo_id,
                    'message_id': message.id,
                    'file_unique_id': file_unique_id,
                    'file_size': size,
                    'duration': duration,
                    'width': w,
                    'height': h,
                    'file_name': fname,
                    'date': message.date.isoformat() if message.date else None,
                    'grouped_id': message.grouped_id,
                    'signature': signature,
                    'media_type': media_type  # NOVO
                }
                
                batch.append(media_data)
                count += 1
                pbar.update(1)
                
                # Inserir em lotes para performance
                if len(batch) >= 500:  # Aumentado para 500 para melhor performance
                    db.insert_media_logs_batch(batch)
                    batch = []
                    
        finally:
            pbar.close()
            
        if skipped > 0:
            print_info(f"   Puladas {skipped:,} mensagens antigas (já auditadas).")
            
    def _carregar_do_db_otimizado(self):
        """
        Carrega dados do DB de forma otimizada.
        NÃO carrega tudo na memória se não for necessário.
        """
        # Contagem apenas
        self.total_midias = db.count_media(self.grupo_id)
        
        # Carregar apenas estrutura mínima necessária
        # O comparador irá usar queries SQL diretas para eficiência
        self.midias_catalogadas = {}
        self.midias_por_data = {}
        
    def _carregar_do_db(self):
        """Carrega dados completos para compatibilidade com código legado."""
        from .gerenciador_dados import load_audit
        dados = load_audit(self.grupo_id)
        self.midias_catalogadas = dados['midias_catalogadas']
        self.midias_por_data = dados['midias_por_data']
