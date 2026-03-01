# clonador_completo.py
# Clona um grupo inteiro para um novo grupo criado automaticamente
# COM PERSISTÊNCIA para grupos de 500k+ mídias

import asyncio
import os
import sys
import time
import json
from datetime import datetime
from typing import Optional, List, Dict, Any
from tqdm.asyncio import tqdm

from telethon import functions
from telethon.tl.types import (
    Channel, Chat, InputPeerChannel,
    MessageMediaPhoto, MessageMediaDocument,
    DocumentAttributeVideo, DocumentAttributeAnimated,
    ForumTopicDeleted
)
from telethon.errors import FloodWaitError, ChatAdminRequiredError

from .estilo import (
    print_success, print_error, print_warning, print_info,
    print_section_header, countdown_timer
)
from .interface import get_all_forum_topics, send_message_with_retry
from .logger import get_logger
from .database import db

logger = get_logger()

# Configurações
LOTE_SIZE = 10
PAUSA_SEGUNDOS = 15
MAX_ERROS_SEGUIDOS = 500
ARQUIVO_MIDIAS_PULADAS = 'dados/midias_puladas.txt'
ARQUIVO_PROGRESSO = 'dados/clonagem_progresso.json'


def _is_video(media) -> bool:
    """Verifica se a mídia é um vídeo (não GIF)."""
    if not isinstance(media, MessageMediaDocument):
        return False
    doc = media.document
    if not doc:
        return False
    for attr in doc.attributes:
        if isinstance(attr, DocumentAttributeAnimated):
            return False  # É GIF, não vídeo
        if isinstance(attr, DocumentAttributeVideo):
            return True
    return False


def _is_photo_or_video(message) -> bool:
    """Verifica se a mensagem contém foto ou vídeo."""
    if not message.media:
        return False
    
    if isinstance(message.media, MessageMediaPhoto):
        return True
    
    if _is_video(message.media):
        return True
    
    return False


class ClonadorCompleto:
    """
    Clona um grupo inteiro para um novo grupo criado automaticamente.
    
    COM PERSISTÊNCIA:
    - Salva progresso a cada lote
    - Permite retomar de onde parou
    - Suporta grupos de 500k+ mídias
    """
    
    def __init__(self, client, grupo_origem, copiar_legendas: bool = True, destino_existente=None, auditar_destino: bool = False):
        self.client = client
        self.origem = grupo_origem
        self.copiar_legendas = copiar_legendas
        self.auditar_destino_flag = auditar_destino
        
        # Configurações de cópia
        self.lote_size = LOTE_SIZE
        self.pausa_segundos = PAUSA_SEGUNDOS
        self.max_erros_seguidos = MAX_ERROS_SEGUIDOS
        
        # NOVO: Configurações de álbum
        self.album_mode = 'copy_origin'  # 'copy_origin' ou 'manual'
        self.album_size = 10  # Usado apenas se album_mode == 'manual'
        
        # Estado
        self.destino = destino_existente
        self.is_forum = False
        self.erros_seguidos = 0
        self.midias_puladas: List[str] = []
        self.total_copiadas = 0
        self.total_puladas = 0
        
        # Persistência
        self.progresso = {
            'origem_id': grupo_origem.id,
            'origem_nome': grupo_origem.title,
            'destino_id': None,
            'is_forum': False,
            'topicos_concluidos': [],
            'topico_atual': None,
            'ultimo_msg_id_copiado': {},  # {topico_id: ultimo_msg_id}
            'total_copiadas': 0,
            'mapa_topicos': {},  # {origem_id: destino_id}
            'iniciado_em': None,
            'atualizado_em': None
        }
        
        self._logger = logger
    
    def _salvar_progresso(self):
        """Salva progresso em DB SQLite."""
        try:
            if not getattr(self, 'task_key', None):
                self._logger.warning("task_key não definido, omitindo salvamento")
                return

            self.progresso['total_copiadas'] = self.total_copiadas
            self.progresso['atualizado_em'] = datetime.now().isoformat()
            
            # Map para a estrutura do banco de dados (progress)
            progress_param = {
                'total_copied': self.total_copiadas,
                'last_id': self.progresso['ultimo_msg_id_copiado'].get('0', 0),
                'pending_list': self.progresso
            }
            db.save_progress(self.task_key, progress_param)
            
            self._logger.info(f"Progresso salvo no banco: {self.total_copiadas} mídias")
        except Exception as e:
            self._logger.error(f"Erro ao salvar progresso: {e}")
    
    def _carregar_progresso(self) -> bool:
        """Carrega progresso salvo se existir no banco."""
        try:
            if not getattr(self, 'task_key', None):
                return False

            row = db.get_progress(self.task_key)
            if not row or not row.get('pending_list'):
                return False
                
            prog = row['pending_list']
            if not isinstance(prog, dict) or prog.get('origem_id') != self.origem.id:
                return False
                
            self.progresso = prog
            self.total_copiadas = self.progresso.get('total_copiadas', 0)
            
            print_success(f"✅ Progresso anterior recuperado do banco de dados!")
            print_info(f"   Mídias já copiadas: {self.total_copiadas:,}")
            print_info(f"   Última atualização: {prog.get('atualizado_em', 'N/A')}")
            
            return True
        except Exception as e:
            self._logger.error(f"Erro ao carregar progresso: {e}")
            return False
    
    def _limpar_progresso(self):
        """Mantém-se para manter formato da API, progresso no db não é deletado nativamente aqui."""
        pass
    
    async def _obter_destino_existente(self) -> Optional[Channel]:
        """Tenta obter grupo destino salvo no progresso."""
        destino_id = self.progresso.get('destino_id')
        if not destino_id:
            return None
        
        try:
            entity = await self.client.get_entity(destino_id)
            print_success(f"✅ Grupo destino encontrado: {entity.title}")
            return entity
        except Exception as e:
            print_warning(f"⚠️ Não foi possível encontrar grupo destino: {e}")
            return None
    
    async def _auditar_destino(self):
        """
        Audita o grupo destino para verificar o que realmente existe.
        Atualiza mapa de tópicos e verifica mídias já copiadas.
        """
        print_info("🔍 Auditando grupo destino...")
        
        # 1. Verificar tópicos existentes no destino
        if self.is_forum and self.destino:
            try:
                topicos_destino = await get_all_forum_topics(self.client, self.destino)
                
                # Criar mapa: nome_maiusculo -> id
                mapa_nomes = {}
                for t in topicos_destino:
                    if not isinstance(t, ForumTopicDeleted):
                        mapa_nomes[t.title.upper()] = t.id
                
                print_info(f"   📁 Encontrados {len(mapa_nomes)} tópicos no destino")
                
                # Atualizar progresso com tópicos encontrados
                self.progresso['topicos_destino'] = mapa_nomes
                self._salvar_progresso()
                
            except Exception as e:
                print_warning(f"   ⚠️ Erro ao listar tópicos do destino: {e}")
        
        # 2. Coletar file_unique_ids das mídias no destino (para verificar duplicatas)
        print_info("   🔍 Coletando mídias existentes no destino...")
        self.midias_destino = set()
        
        try:
            count = 0
            async for msg in self.client.iter_messages(self.destino, limit=None):
                if msg.media:
                    # Usar file_unique_id para identificar mídia
                    if hasattr(msg.media, 'photo') and msg.media.photo:
                        self.midias_destino.add(msg.media.photo.id)
                    elif hasattr(msg.media, 'document') and msg.media.document:
                        self.midias_destino.add(msg.media.document.id)
                    count += 1
                    if count % 1000 == 0:
                        print_info(f"   Analisadas {count:,} mídias...")
            
            print_success(f"   ✅ {len(self.midias_destino):,} mídias únicas encontradas no destino")
            
        except Exception as e:
            print_warning(f"   ⚠️ Erro ao auditar mídias: {e}")
            self.midias_destino = set()
    
    def _midia_ja_copiada(self, msg) -> bool:
        """Verifica se uma mídia já existe no destino."""
        if not hasattr(self, 'midias_destino') or not self.midias_destino:
            return False
        
        try:
            if hasattr(msg.media, 'photo') and msg.media.photo:
                return msg.media.photo.id in self.midias_destino
            elif hasattr(msg.media, 'document') and msg.media.document:
                return msg.media.document.id in self.midias_destino
        except Exception:
            pass
        
        return False
    
    async def _criar_grupo_destino(self) -> Optional[Channel]:
        """Cria um novo grupo com o mesmo nome da origem (ou nome customizado)."""
        try:
            # Usar nome customizado se definido
            nome_grupo = getattr(self, 'nome_grupo_customizado', None) or self.origem.title
            
            print_info(f"📦 Criando grupo: {nome_grupo}")
            
            result = await self.client(functions.channels.CreateChannelRequest(
                title=nome_grupo,
                about=f"Clone de {self.origem.title}",
                megagroup=True,
            ))
            
            novo_grupo = result.chats[0]
            self._logger.info(f"Grupo criado: {novo_grupo.id}")
            
            # Salvar ID no progresso
            self.progresso['destino_id'] = novo_grupo.id
            self.progresso['destino_nome'] = nome_grupo
            self.progresso['iniciado_em'] = datetime.now().isoformat()
            self._salvar_progresso()
            
            # Configurar histórico visível
            try:
                await self.client(functions.channels.TogglePreHistoryHiddenRequest(
                    channel=novo_grupo,
                    enabled=False
                ))
                print_success("✅ Histórico visível para novos membros ativado")
            except Exception as e:
                print_warning(f"⚠️ Não foi possível ativar histórico visível: {e}")
            
            print_success(f"✅ Grupo '{nome_grupo}' criado com sucesso!")
            return novo_grupo
            
        except Exception as e:
            print_error(f"❌ Erro ao criar grupo: {e}")
            self._logger.error(f"Erro ao criar grupo: {e}")
            return None
    
    async def _ativar_forum(self, grupo) -> bool:
        """Ativa o modo fórum (tópicos) no grupo."""
        try:
            await self.client(functions.channels.ToggleForumRequest(
                channel=grupo,
                enabled=True
            ))
            print_success("✅ Modo Fórum (tópicos) ativado!")
            return True
        except Exception as e:
            print_error(f"❌ Erro ao ativar modo fórum: {e}")
            return False
    
    async def _criar_topico(self, grupo, nome: str) -> Optional[int]:
        """Cria um tópico no grupo destino com nome em MAIÚSCULAS."""
        try:
            nome_maiusculo = nome.upper()
            
            result = await self.client(functions.channels.CreateForumTopicRequest(
                channel=grupo,
                title=nome_maiusculo,
                random_id=int.from_bytes(os.urandom(8), 'big', signed=True)
            ))
            
            topico_id = result.updates[0].id
            print_success(f"   ✅ Tópico criado: {nome_maiusculo}")
            return topico_id
            
        except FloodWaitError as e:
            print_warning(f"⏳ FloodWait: aguardando {e.seconds}s...")
            await countdown_timer(e.seconds + 5, "Aguardando FloodWait")
            return await self._criar_topico(grupo, nome)
        except Exception as e:
            print_error(f"   ❌ Erro ao criar tópico '{nome}': {e}")
            return None
    
    def _salvar_midia_pulada(self, mensagem, motivo: str = "erro"):
        """Salva erro da mídia no banco."""
        if not getattr(self, 'task_key', None):
            return
        try:
            db.log_copy_failure(self.task_key, mensagem.id, motivo)
            self.total_puladas += 1
        except Exception as e:
            self._logger.error(f"Erro ao salvar log de falha: {e}")
    
    async def _copiar_lote(self, mensagens: List, reply_to: Optional[int] = None, topico_id: int = 0, pbar=None) -> bool:
        """
        Copia um lote de mensagens para o destino.
        - Detecta álbuns originais (grouped_id)
        - Agrupa mídias conforme configuração (copy_origin ou manual)
        - Atualiza barra de progresso em tempo real
        NUNCA PARA POR ERROS - salva link das falhas e continua.
        """
        copiadas_no_lote = 0
        
        # Organizar mensagens por álbum (grouped_id)
        if self.album_mode == 'copy_origin':
            # Modo: Copiar exatamente como está na origem
            albuns_por_grupo = {}
            mensagens_individuais = []
            
            for msg in mensagens:
                if hasattr(msg, 'grouped_id') and msg.grouped_id:
                    # Faz parte de um álbum
                    if msg.grouped_id not in albuns_por_grupo:
                        albuns_por_grupo[msg.grouped_id] = []
                    albuns_por_grupo[msg.grouped_id].append(msg)
                else:
                    # Mensagem individual
                    mensagens_individuais.append(msg)
            
            # Copiar álbuns originais
            for grouped_id, album_msgs in albuns_por_grupo.items():
                album_msgs.sort(key=lambda m: m.id)  # Ordenar por ID
                
                try:
                    # Preparar lista de mídias e legendas
                    files = [m.media for m in album_msgs]
                    
                    # Pegar legenda apenas da primeira mensagem (padrão Telegram)
                    caption = album_msgs[0].text if self.copiar_legendas and album_msgs[0].text else None
                    
                    # Enviar como álbum
                    await send_message_with_retry(
                        self.client,
                        self.destino,
                        file=files,
                        caption=caption,
                        reply_to=reply_to
                    )
                    
                    copiadas_no_lote += len(album_msgs)
                    self.total_copiadas += len(album_msgs)
                    self.erros_seguidos = 0
                    
                    # Atualizar barra de progresso EM TEMPO REAL
                    if pbar:
                        pbar.update(len(album_msgs))
                    
                    # Salvar progresso
                    self.progresso['ultimo_msg_id_copiado'][str(topico_id)] = album_msgs[-1].id
                    
                    await asyncio.sleep(0.5)  # Pausa entre álbuns
                    
                except Exception as e:
                    for msg in album_msgs:
                        self._salvar_midia_pulada(msg, str(e)[:100])
                    self.erros_seguidos += len(album_msgs)
            
            # Copiar mensagens individuais
            for msg in mensagens_individuais:
                try:
                    await send_message_with_retry(
                        self.client,
                        self.destino,
                        file=msg.media,
                        caption=msg.text if self.copiar_legendas and msg.text else None,
                        reply_to=reply_to
                    )
                    
                    copiadas_no_lote += 1
                    self.total_copiadas += 1
                    self.erros_seguidos = 0
                    
                    # Atualizar barra EM TEMPO REAL
                    if pbar:
                        pbar.update(1)
                    
                    self.progresso['ultimo_msg_id_copiado'][str(topico_id)] = msg.id
                    await asyncio.sleep(0.3)
                    
                except Exception as e:
                    self._salvar_midia_pulada(msg, str(e)[:100])
                    self.erros_seguidos += 1
        
        else:
            # Modo: Álbum manual (agrupar por tamanho configurado)
            i = 0
            while i < len(mensagens):
                # Pegar próximo grupo de mídias (até album_size)
                grupo = mensagens[i:i + self.album_size]
                
                if len(grupo) > 1:
                    # Enviar como álbum
                    try:
                        files = [m.media for m in grupo]
                        caption = grupo[0].text if self.copiar_legendas and grupo[0].text else None
                        
                        await send_message_with_retry(
                            self.client,
                            self.destino,
                            file=files,
                            caption=caption,
                            reply_to=reply_to
                        )
                        
                        copiadas_no_lote += len(grupo)
                        self.total_copiadas += len(grupo)
                        self.erros_seguidos = 0
                        
                        if pbar:
                            pbar.update(len(grupo))
                        
                        self.progresso['ultimo_msg_id_copiado'][str(topico_id)] = grupo[-1].id
                        await asyncio.sleep(0.5)
                        
                    except Exception as e:
                        for msg in grupo:
                            self._salvar_midia_pulada(msg, str(e)[:100])
                        self.erros_seguidos += len(grupo)
                else:
                    # Enviar individual
                    msg = grupo[0]
                    try:
                        await send_message_with_retry(
                            self.client,
                            self.destino,
                            file=msg.media,
                            caption=msg.text if self.copiar_legendas and msg.text else None,
                            reply_to=reply_to
                        )
                        
                        copiadas_no_lote += 1
                        self.total_copiadas += 1
                        if pbar:
                            pbar.update(1)
                        self.progresso['ultimo_msg_id_copiado'][str(topico_id)] = msg.id
                        await asyncio.sleep(0.3)
                    except Exception as e:
                        self._salvar_midia_pulada(msg, str(e)[:100])
                        self.erros_seguidos += 1
                
                i += self.album_size
        
        # Salvar progresso após o lote
        self._salvar_progresso()
        
        return copiadas_no_lote > 0
    
    async def _clonar_grupo_simples(self):
        """Clona um grupo simples (sem tópicos)."""
        print_section_header("Clonando Grupo Simples")
        
        # Verificar último ID copiado
        ultimo_id = self.progresso['ultimo_msg_id_copiado'].get('0', 0)
        
        print_info(f"🔍 Escaneando mídias em '{self.origem.title}'...")
        if ultimo_id > 0:
            print_info(f"   Retomando após mensagem ID {ultimo_id}")
        
        mensagens_midia = []
        mensagens_escaneadas = 0
        
        # Barra de progresso para escaneamento (total desconhecido)
        pbar_scan = tqdm(
            desc="   Escaneando mensagens",
            unit=" msg",
            dynamic_ncols=True,
            file=sys.stderr
        )
        
        try:
            async for msg in self.client.iter_messages(self.origem, limit=None):
                mensagens_escaneadas += 1
                pbar_scan.update(1)
                
                if _is_photo_or_video(msg):
                    # Pular mídias já copiadas
                    if msg.id <= ultimo_id:
                        continue
                    mensagens_midia.append(msg)
                    pbar_scan.set_postfix(midias=len(mensagens_midia))
        finally:
            pbar_scan.close()
        
        total = len(mensagens_midia)
        print_info(f"📊 {total:,} mídias pendentes (fotos/vídeos)")
        
        if total == 0:
            print_success("✅ Todas as mídias já foram copiadas!")
            return
        
        mensagens_midia.reverse()
        
        lote_atual = []
        midias_desde_pausa = 0
        
        pbar = tqdm(total=total, desc=f"Clonando", unit=" mídia", dynamic_ncols=True, file=sys.stderr)
        
        try:
            for msg in mensagens_midia:
                # REMOVIDO: Não para mais por erros seguidos
                if self.erros_seguidos >= self.max_erros_seguidos and self.erros_seguidos % self.max_erros_seguidos == 0:
                     print_warning(f"\n⚠️ {self.erros_seguidos} mídias puladas seguidas. Continuando...")
                     # input("\n⏸️ Pressione Enter para continuar ou Ctrl+C para cancelar...")
                     # self.erros_seguidos = 0
                
                lote_atual.append(msg)
                
                if len(lote_atual) >= self.lote_size:
                    sucesso = await self._copiar_lote(lote_atual, None, 0, pbar)
                    
                    if sucesso:
                        midias_desde_pausa += len(lote_atual)
                    
                    lote_atual = []
                    
                    if midias_desde_pausa >= self.lote_size:
                        await countdown_timer(self.pausa_segundos, "Pausa programada")
                        midias_desde_pausa = 0
            
            if lote_atual:
                await self._copiar_lote(lote_atual, None, 0, pbar)
            
        finally:
            pbar.close()
    
    async def _clonar_grupo_forum(self):
        """Clona um grupo com tópicos."""
        print_section_header("Clonando Grupo com Tópicos")
        
        topicos_origem = await get_all_forum_topics(self.client, self.origem)
        topicos_validos = [t for t in topicos_origem if not isinstance(t, ForumTopicDeleted)]
        
        print_info(f"📁 Encontrados {len(topicos_validos)} tópicos")
        
        # Carregar progresso
        mapa_topicos = self.progresso.get('mapa_topicos', {})
        topicos_concluidos = self.progresso.get('topicos_concluidos', [])
        
        # FLUXO: Criar tópico → Copiar mídias → Próximo tópico
        # (Não criar todos de uma vez para evitar bloqueio)
        
        for i, topico in enumerate(topicos_validos):
            str_id = str(topico.id)
            
            # Pular tópicos já concluídos
            if str_id in topicos_concluidos:
                print_info(f"   ⏭️ [{i+1}/{len(topicos_validos)}] '{topico.title}' já concluído, pulando...")
                continue
            
            # Pular tópico General (id=1)
            if topico.id == 1:
                continue
            
            print_section_header(f"[{i+1}/{len(topicos_validos)}] Tópico: {topico.title.upper()}")
            self.progresso['topico_atual'] = str_id
            self._salvar_progresso()
            
            # 1. Criar tópico no destino (se ainda não existe)
            if str_id not in mapa_topicos:
                id_destino = await self._criar_topico(self.destino, topico.title)
                if id_destino:
                    mapa_topicos[str_id] = id_destino
                    self.progresso['mapa_topicos'] = mapa_topicos
                    self._salvar_progresso()
                else:
                    print_warning(f"   ⚠️ Não foi possível criar tópico, usando General")
                    id_destino = 1
            else:
                id_destino = mapa_topicos[str_id]
                print_info(f"   ✅ Tópico já existe no destino")
            
            # 2. Verificar último ID copiado neste tópico
            ultimo_id = self.progresso['ultimo_msg_id_copiado'].get(str_id, 0)
            if ultimo_id > 0:
                print_info(f"   Retomando após mensagem ID {ultimo_id}")
            
            # 3. Coletar mídias deste tópico
            mensagens_midia = []
            ja_copiadas = 0
            pbar_scan = tqdm(
                desc=f"   Escaneando {topico.title}",
                unit=" msg",
                dynamic_ncols=True,
                file=sys.stderr
            )
            
            try:
                async for msg in self.client.iter_messages(self.origem, reply_to=topico.id):
                    pbar_scan.update(1)
                    if _is_photo_or_video(msg):
                        if msg.id <= ultimo_id:
                            continue
                        # Verificar se mídia já existe no destino (se auditoria ativada)
                        if self._midia_ja_copiada(msg):
                            ja_copiadas += 1
                            continue
                        mensagens_midia.append(msg)
                        pbar_scan.set_postfix(midias=len(mensagens_midia))
            finally:
                pbar_scan.close()
            
            if ja_copiadas > 0:
                print_info(f"   ⏭️ {ja_copiadas} mídias já existem no destino, pulando...")
            
            if not mensagens_midia:
                print_info(f"   ✅ Nenhuma mídia nova no tópico")
                topicos_concluidos.append(str_id)
                self.progresso['topicos_concluidos'] = topicos_concluidos
                self._salvar_progresso()
                continue
            
            mensagens_midia.reverse()
            
            print_info(f"   📊 {len(mensagens_midia)} mídias pendentes")
            
            # 4. Copiar em lotes
            lote_atual = []
            midias_desde_pausa = 0
            
            pbar = tqdm(
                total=len(mensagens_midia),
                desc=f"   {topico.title.upper()}",
                unit=" mídia",
                dynamic_ncols=True,
                file=sys.stderr
            )
            
            try:
                for msg in mensagens_midia:
                    # REMOVIDO: Não para mais por erros seguidos
                    # Apenas loga se houver muitos erros
                    if self.erros_seguidos >= self.max_erros_seguidos and self.erros_seguidos % self.max_erros_seguidos == 0:
                        print_warning(f"⚠️ {self.erros_seguidos} erros seguidos. Continuando mesmo assim...")
                        self._logger.warning(f"{self.erros_seguidos} erros seguidos no tópico {topico.title}")
                    
                    lote_atual.append(msg)
                    
                    if len(lote_atual) >= self.lote_size:
                        sucesso = await self._copiar_lote(lote_atual, id_destino, topico.id, pbar)
                        
                        if sucesso:
                            midias_desde_pausa += len(lote_atual)
                        
                        lote_atual = []
                        
                        if midias_desde_pausa >= self.lote_size:
                            await countdown_timer(self.pausa_segundos, "Pausa")
                            midias_desde_pausa = 0
                
                if lote_atual:
                    await self._copiar_lote(lote_atual, id_destino, topico.id, pbar)
                
                # Marcar tópico como concluído
                topicos_concluidos.append(str_id)
                self.progresso['topicos_concluidos'] = topicos_concluidos
                self._salvar_progresso()
                    
            finally:
                pbar.close()
    
    async def run(self) -> bool:
        """Executa a clonagem completa."""
        print_section_header(f"CLONAGEM COMPLETA: {self.origem.title}")
        
        # Verificar se há progresso salvo
        retomando = self._carregar_progresso()
        
        # Verificar se origem é fórum
        self.is_forum = getattr(self.origem, 'forum', False)
        self.progresso['is_forum'] = self.is_forum
        
        if self.is_forum:
            print_info("📁 Grupo origem é um FÓRUM (com tópicos)")
        else:
            print_info("📁 Grupo origem é SIMPLES (sem tópicos)")
        
        # 1. Obter ou criar grupo destino
        if retomando:
            self.destino = await self._obter_destino_existente()
        
        if not self.destino:
            self.destino = await self._criar_grupo_destino()
        
        if not self.destino:
            return False
        
        # 2. Auditar destino (opcional)
        if self.auditar_destino_flag:
            await self._auditar_destino()
        
        # 3. Se for fórum, ativar no destino
        if self.is_forum:
            if not retomando:
                await self._ativar_forum(self.destino)
            await self._clonar_grupo_forum()
        else:
            await self._clonar_grupo_simples()
        
        # 3. Resumo final
        print_section_header("CLONAGEM CONCLUÍDA")
        print_success(f"✅ Total copiadas: {self.total_copiadas:,}")
        
        if self.total_puladas > 0:
            print_warning(f"⚠️ Total puladas: {self.total_puladas:,}")
            print_info(f"📁 Links salvos em: {ARQUIVO_MIDIAS_PULADAS}")
        
        if hasattr(self.destino, 'username') and self.destino.username:
            print_success(f"🔗 Link: https://t.me/{self.destino.username}")
        else:
            print_success(f"🔗 ID do grupo: {self.destino.id}")
        
        # Limpar arquivo de progresso após conclusão
        self._limpar_progresso()
        
        return True
