# copiador_inteligente.py
# Nova versão do copiador que usa o sistema de auditoria

import asyncio
import random
import time
import os
import sys
import math
from tqdm.asyncio import tqdm
from telethon import functions
from telethon.errors.rpcerrorlist import MessageTooLongError, FloodWaitError
import inquirer

# Importa dos outros arquivos
from . import gerenciador_dados as dados
from . import interface
from .estilo import (
    print_success, print_error, print_warning, print_info, 
    print_section_header, countdown_timer
)
from .interface import send_message_with_retry
from .auditoria import AuditoriaGrupo
from .comparador import ComparadorMidias
from .limiter import global_limiter
from .database import db
from .config import get_config, get_retry_delay  # [S13] Configuração centralizada
from .logger import get_logger  # [S7] Logger

TELEGRAM_CHAR_LIMIT = 4000

class CopiadorInteligente:
    """Copiador que usa auditoria para copiar apenas o que falta."""
    
    def __init__(self, client, task_config, task_key, file_type_filter='all', account_phone=None, client_pool=None):
        self.client = client
        self.client_pool = client_pool  # Pool de múltiplas contas para rotação
        self.config = task_config
        self.task_key = task_key
        self.file_type_filter = file_type_filter
        self.account_phone = account_phone
        self.copy_speed = task_config.get('copy_speed', 'traditional')
        self.media_per_pause = task_config.get('media_per_pause')
        self.pause_duration = task_config.get('pause_duration')
        self.datas_selecionadas = 'all'
        
        # Entidades
        self.origem = None
        self.destino = None
        
        # Sistema de auditoria
        self.auditoria_origem = None
        self.auditoria_destino = None
        self.comparador = None
        self.ids_pendentes = []
        
        # Progresso
        self.total_midias_copiadas = 0
        self.id_msg_indice = None
        self.indice_atual_pendentes = 0
        self.media_since_last_pause = 0
        
        # [S13] Configuração de retry do config.py
        self._config = get_config()
        self.max_retries = self._config.retry.max_retries
        self.falhas_registradas = 0
        self._logger = get_logger()

    async def _inicializar_entidades(self):
        """Busca e valida as entidades."""
        try:
            self.origem = await self.client.get_entity(self.config['id_origem'])
            self.destino = await self.client.get_entity(self.config['id_destino'])
            return True
        except Exception as e:
            print_error(f"Erro ao buscar grupos: {e}")
            return False
    
    async def _executar_auditoria(self):
        """Executa a auditoria de origem e destino, reutilizando auditorias existentes se o usuário desejar."""
        from .database import db
        from datetime import datetime
        
        print_section_header("Fase 1: Auditoria dos Grupos")
        
        # ========== AUDITORIA ORIGEM ==========
        print("\n" + "="*60)
        print_info("🔍 AUDITANDO GRUPO ORIGEM")
        print("="*60)
        
        # Verificar se já existe auditoria para origem
        metadata_origem = db.get_audit_metadata(self.config['id_origem'])
        modo_origem = 'auto'
        
        if metadata_origem and metadata_origem['total_media_count'] > 0:
            # Calcular idade da auditoria
            idade_horas = 0
            if metadata_origem['last_audited_at']:
                idade_horas = (datetime.now() - metadata_origem['last_audited_at']).total_seconds() / 3600
            
            print_success(f"✅ Auditoria existente encontrada para '{self.config['nome_origem']}'!")
            print_info(f"   📊 {metadata_origem['total_media_count']:,} mídias catalogadas")
            print_info(f"   ⏰ Feita há {idade_horas:.1f} horas")
            
            # Verificar autormação ou perguntar
            if self.config.get('automacao_total'):
                print_info("🤖 Modo Automático: Usando auditoria existente (Incremental).")
                modo_origem = 'incremental' # Força incremental para pegar novos
            else:
                escolha = inquirer.prompt([
                    inquirer.List('modo',
                                  message="O que deseja fazer com a auditoria de ORIGEM?",
                                  choices=[
                                      ('✅ Usar auditoria existente (Rápido)', 'usar'),
                                      ('🔄 Atualizar auditoria (Buscar só novas)', 'incremental'),
                                      ('🌐 Refazer auditoria completa (Do zero)', 'full')
                                  ])
                ])
                
                if escolha and escolha['modo'] == 'usar':
                    modo_origem = 'auto'  # Vai usar cache automaticamente
                    print_info("Usando auditoria existente...")
                elif escolha and escolha['modo'] == 'full':
                    modo_origem = 'full'
                else:
                    modo_origem = 'incremental'
        
        self.auditoria_origem = AuditoriaGrupo(
            self.client,
            self.origem,
            self.config['nome_origem'],
            self.account_phone
        )
        
        sucesso = await self.auditoria_origem.auditar(modo=modo_origem)
        if not sucesso:
            return False
        
        # ========== AUDITORIA DESTINO ==========
        print("\n" + "="*60)
        print_info("🔍 AUDITANDO GRUPO DESTINO")
        print("="*60)
        
        # Verificar se já existe auditoria para destino
        metadata_destino = db.get_audit_metadata(self.config['id_destino'])
        modo_destino = 'auto'
        
        if metadata_destino and metadata_destino['total_media_count'] > 0:
            # Calcular idade da auditoria
            idade_horas = 0
            if metadata_destino['last_audited_at']:
                idade_horas = (datetime.now() - metadata_destino['last_audited_at']).total_seconds() / 3600
            
            print_success(f"✅ Auditoria existente encontrada para '{self.config['nome_destino']}'!")
            print_info(f"   📊 {metadata_destino['total_media_count']:,} mídias catalogadas")
            print_info(f"   ⏰ Feita há {idade_horas:.1f} horas")
            
            # Verificar autormação ou perguntar
            if self.config.get('automacao_total'):
                print_info("🤖 Modo Automático: Usando auditoria existente (Incremental).")
                modo_destino = 'incremental'
            else:
                escolha = inquirer.prompt([
                    inquirer.List('modo',
                                  message="O que deseja fazer com a auditoria de DESTINO?",
                                  choices=[
                                      ('✅ Usar auditoria existente (Rápido)', 'usar'),
                                      ('🔄 Atualizar auditoria (Buscar só novas)', 'incremental'),
                                      ('🌐 Refazer auditoria completa (Do zero)', 'full')
                                  ])
                ])
                
                if escolha and escolha['modo'] == 'usar':
                    modo_destino = 'auto'
                    print_info("Usando auditoria existente...")
                elif escolha and escolha['modo'] == 'full':
                    modo_destino = 'full'
                else:
                    modo_destino = 'incremental'
        
        self.auditoria_destino = AuditoriaGrupo(
            self.client,
            self.destino,
            self.config['nome_destino'],
            self.account_phone
        )
        
        sucesso = await self.auditoria_destino.auditar(modo=modo_destino)
        if not sucesso:
            return False
        
        return True
    
    def _executar_comparacao(self):
        """Compara as auditorias e identifica o que falta copiar."""
        print_section_header("Fase 2: Comparação e Identificação")
        
        self.comparador = ComparadorMidias(
            self.auditoria_origem,
            self.auditoria_destino
        )
        
        self.ids_pendentes = self.comparador.comparar()
        
        if not self.ids_pendentes:
            print_success("\n🎉 Todas as mídias já foram copiadas!")
            return False
        
        # Salva lista de pendentes
        self.comparador.salvar_lista_pendentes(self.task_key)
        
        # Carrega progresso (quantas já foram copiadas desta lista)
        progress = dados.get_task_progress(f"{self.task_key}_inteligente")
        self.indice_atual_pendentes = progress.get('indice_pendentes', 0)
        self.total_midias_copiadas = progress.get('total_midias_copiadas', self.auditoria_destino.total_midias)
        self.id_msg_indice = progress.get('id_msg_indice', None)
        
        if self.indice_atual_pendentes > 0:
            print_warning(f"\n⚠️ Encontrado progresso salvo de execução anterior.")
            print_info(f"   Já foram processados {self.indice_atual_pendentes} de {len(self.ids_pendentes)} itens desta lista.")
            
            acao_escolhida = None
            
            if self.config.get('automacao_total'):
                print_info("🤖 Modo Automático: REINICIANDO para garantir completude.")
                acao_escolhida = 'reiniciar'
            else:
                print_info(f"   Se você auditou novamente, é recomendado REINICIAR para tentar copiar itens que falharam.")
                escolha = inquirer.prompt([
                    inquirer.List('acao',
                                  message="O que deseja fazer?",
                                  choices=[
                                      ('🔄 Reiniciar (Copiar todos os pendentes)', 'reiniciar'),
                                      ('⏩ Retomar de onde parou (Pular processados)', 'retomar')
                                  ])
                ])
                acao_escolhida = escolha['acao'] if escolha else 'retomar'
            
            if acao_escolhida == 'reiniciar':
                print_info("Reiniciando contagem. Todas as mídias pendentes serão processadas.")
                self.indice_atual_pendentes = 0
                self._salvar_progresso(0) # Reseta no arquivo
            else:
                print_info(f"Retomando cópia a partir do item {self.indice_atual_pendentes}...")
                self.ids_pendentes = self.ids_pendentes[self.indice_atual_pendentes:]
        
        return True
    
    def _salvar_progresso(self, indice_processado):
        """Salva o progresso da cópia inteligente."""
        progress_data = {
            'indice_pendentes': indice_processado,
            'total_midias_copiadas': self.total_midias_copiadas,
            'id_msg_indice': self.id_msg_indice
        }
        dados.save_progress(f"{self.task_key}_inteligente", progress_data)
    
    async def _pausa_aleatoria_segura(self):
        """Espera de 3 a 8 segundos."""
        await asyncio.sleep(random.randint(3, 8))

    async def _handle_custom_pause(self, media_count_in_lote):
        if self.copy_speed == 'custom' and self.media_per_pause and self.pause_duration:
            self.media_since_last_pause += media_count_in_lote
            if self.media_since_last_pause >= self.media_per_pause:
                await countdown_timer(self.pause_duration, reason="Pausa personalizada")
                self.media_since_last_pause = 0

    async def _atualizar_indice(self, novo_titulo_topico, link_primeira_midia):
        """Atualiza o índice (igual ao copiador original)."""
        if not self.config.get('id_topico_indice'):
            return
        
        try:
            num_linha = math.ceil(self.total_midias_copiadas / self.config['lote_size'])
            nova_linha_indice = f"{num_linha} - [{novo_titulo_topico}]({link_primeira_midia})"
            
            if not self.id_msg_indice:
                cabecalho = f"**ÍNDICE DE MÍDIAS - {self.config['nome_origem']}**\n\n"
                msg_enviada = await self.client.send_message(
                    self.destino,
                    message=f"{cabecalho}{nova_linha_indice}",
                    reply_to=self.config['id_topico_indice'],
                    parse_mode='md'
                )
                self.id_msg_indice = msg_enviada.id
            else:
                msg_antiga = await self.client.get_messages(self.destino, ids=self.id_msg_indice)
                
                if not msg_antiga:
                    self.id_msg_indice = None
                    await self._atualizar_indice(novo_titulo_topico, link_primeira_midia)
                    return
                
                texto_antigo = msg_antiga.text
                novo_texto = f"{texto_antigo}\n{nova_linha_indice}"
                
                if len(novo_texto) > TELEGRAM_CHAR_LIMIT:
                    cabecalho_continua = f"**ÍNDICE DE MÍDIAS (Continuação)**\n\n"
                    msg_enviada = await self.client.send_message(
                        self.destino,
                        message=f"{cabecalho_continua}{nova_linha_indice}",
                        reply_to=self.config['id_topico_indice'],
                        parse_mode='md'
                    )
                    self.id_msg_indice = msg_enviada.id
                else:
                    await self.client.edit_message(
                        self.destino,
                        message=self.id_msg_indice,
                        text=novo_texto,
                        parse_mode='md'
                    )
            
            print_success("Índice atualizado!")
            
        except MessageTooLongError:
            cabecalho_continua = f"**ÍNDICE DE MÍDIAS (Continuação)**\n\n"
            msg_enviada = await self.client.send_message(
                self.destino,
                message=f"{cabecalho_continua}{nova_linha_indice}",
                reply_to=self.config['id_topico_indice'],
                parse_mode='md'
            )
            self.id_msg_indice = msg_enviada.id
        except Exception as e:
            print_warning(f"Erro ao atualizar índice: {e}")
    
    async def _executar_copia(self):
        """Executa a cópia das mídias pendentes."""
        print_section_header("Fase 3: Cópia Inteligente")
        
        if self.config.get('ordem') == 'decrescente':
            self.ids_pendentes.reverse()

        is_forum = self.config['modo'] == "Fórum (Indexado)"
        tamanho_lote = self.config['lote_size'] if is_forum else 10
        
        pbar = tqdm(
            total=len(self.ids_pendentes),
            initial=0,
            desc="Mídias Copiadas",
            unit=" mídia",
            dynamic_ncols=True,
            file=sys.stderr
        )
        
        lote_atual = []
        indice_processado = self.indice_atual_pendentes
        
        try:
            for i, msg_id in enumerate(self.ids_pendentes):
                # NOVO: Loop de retry com backoff exponencial
                message = None
                for attempt in range(self.max_retries):
                    try:
                        message = await self.client.get_messages(self.origem, ids=msg_id)
                        break  # Sucesso, sai do retry loop
                    except FloodWaitError as e:
                        await global_limiter.report_flood_wait(e.seconds)
                        continue  # Tenta novamente após cooldown
                    except Exception as e:
                        if attempt == self.max_retries - 1:
                            # Última tentativa falhou - registrar no banco
                            print_warning(f"⚠️ Mídia {msg_id} falhou após {self.max_retries} tentativas: {e}")
                            db.log_copy_failure(self.task_key, msg_id, str(e))
                            self.falhas_registradas += 1
                            message = None
                        else:
                            # [S13] Backoff exponencial configurável
                            wait_time = get_retry_delay(attempt)
                            self._logger.warning(f"Retry {attempt+1}/{self.max_retries} para mídia {msg_id}, aguardando {wait_time:.1f}s")
                            await asyncio.sleep(wait_time)
                
                if not message:
                    continue  # Pula para próxima mídia

                # Filtro de tipo de arquivo
                if self.file_type_filter != 'all':
                    if not message.media:
                        continue
                    if self.file_type_filter == 'photo' and not message.photo:
                        continue
                    if self.file_type_filter == 'video' and not message.video:
                        continue
                    if self.file_type_filter == 'subtitle' and not (message.document and 'video' in message.document.mime_type):
                        continue
                    if self.file_type_filter == 'hyperlink' and not message.entities:
                        continue

                lote_atual.append(message)
                
                if len(lote_atual) >= tamanho_lote or i == len(self.ids_pendentes) - 1:
                    if is_forum:
                        sucesso = await self._copiar_lote_forum(lote_atual, pbar)
                    else:
                        sucesso = await self._copiar_lote_simples(lote_atual, pbar)
                    
                    if sucesso:
                        indice_processado = self.indice_atual_pendentes + i + 1
                        self._salvar_progresso(indice_processado)
                        lote_atual = []
                    else:
                        # Tenta continuar com próximo lote em vez de parar
                        print_warning("Lote falhou, continuando com próximo...")
                        lote_atual = []
            
            pbar.close()
            
            # Resumo final
            if self.falhas_registradas > 0:
                print_warning(f"\n⚠️ {self.falhas_registradas} mídias falharam e foram registradas para revisão posterior.")
            print_success("\n✅ Cópia inteligente concluída!")
            
        except KeyboardInterrupt:
            pbar.close()
            print_warning("\nCópia interrompida. Progresso salvo.")
            self._salvar_progresso(indice_processado)
        except Exception as e:
            pbar.close()
            print_error(f"\nErro durante cópia: {e}")
            self._salvar_progresso(indice_processado)

    async def _copiar_lote_simples(self, lote_de_msgs, pbar):
        """Copia um lote de mensagens para grupo tradicional."""
        if not lote_de_msgs:
            return True
        
        # Separate messages with media and without media
        media_msgs = [m for m in lote_de_msgs if m.media]
        text_msgs = [m for m in lote_de_msgs if not m.media]

        # Send media messages in batches of 10
        for i in range(0, len(media_msgs), 10):
            sub_lote = media_msgs[i:i+10]
            
            # Usar rotação de contas se disponível
            if self.client_pool and self.client_pool.has_multiple_accounts():
                client, telefone, limiter = self.client_pool.get_next_client()
            else:
                client, limiter = self.client, None
            
            await send_message_with_retry(
                client,
                self.destino,
                copy_speed=self.copy_speed,
                limiter=limiter,
                file=[m.media for m in sub_lote],
                caption=[m.text for m in sub_lote]
            )
            if self.copy_speed == 'traditional':
                await self._pausa_aleatoria_segura()
            await self._handle_custom_pause(len(sub_lote))

        # Send text messages one by one
        for message in text_msgs:
            # Usar rotação de contas se disponível
            if self.client_pool and self.client_pool.has_multiple_accounts():
                client, telefone, limiter = self.client_pool.get_next_client()
            else:
                client, limiter = self.client, None
            
            await send_message_with_retry(
                client,
                self.destino,
                copy_speed=self.copy_speed,
                limiter=limiter,
                message=message.text
            )
            if self.copy_speed == 'traditional':
                await self._pausa_aleatoria_segura()
            await self._handle_custom_pause(1)

        self.total_midias_copiadas += len(lote_de_msgs)
        pbar.update(len(lote_de_msgs))
        return True

    async def _copiar_lote_forum(self, lote_de_msgs, pbar):
        """Copia um lote de mensagens para o fórum."""
        if not lote_de_msgs:
            return True
        
        contador_inicio = self.total_midias_copiadas + 1
        contador_fim = self.total_midias_copiadas + len(lote_de_msgs)
        nome_topico = f"Mídias ({contador_inicio} a {contador_fim})"
        
        print_info(f"Criando tópico: '{nome_topico}'")
        
        # Limiter espera antes de criar tópico (custo maior)
        await global_limiter.wait(cost=2)
        
        try:
            updates = await self.client(functions.channels.CreateForumTopicRequest(
                channel=self.destino,
                title=nome_topico,
                random_id=int.from_bytes(os.urandom(8), 'big', signed=True)
            ))
            id_novo_topico = updates.updates[0].id
        except FloodWaitError as e:
            await global_limiter.report_flood_wait(e.seconds)
            return False
        except Exception as e:
            print_error(f"Falha ao criar tópico: {e}")
            if self.copy_speed == 'traditional':
                await self._pausa_aleatoria_segura()
            return False
        
        link_primeira_midia = None
        for i, message in enumerate(lote_de_msgs):
            # Usar rotação de contas se disponível
            if self.client_pool and self.client_pool.has_multiple_accounts():
                client, telefone, limiter = self.client_pool.get_next_client()
            else:
                client, limiter = self.client, None
            
            await send_message_with_retry(
                client,
                self.destino,
                copy_speed=self.copy_speed,
                limiter=limiter,
                message=message,
                reply_to=id_novo_topico
            )
            
            if i == 0:
                try:
                    primeira_msg = (await self.client.get_messages(self.destino, reply_to=id_novo_topico, limit=1))[0]
                    link_primeira_midia = f"https://t.me/c/{self.destino.id}/{id_novo_topico}/{primeira_msg.id}"
                except:
                    pass
            
            if self.copy_speed == 'traditional':
                await self._pausa_aleatoria_segura()
            await self._handle_custom_pause(1)

        if not link_primeira_midia:
            link_primeira_midia = f"https://t.me/c/{self.destino.id}/{id_novo_topico}"
        
        self.total_midias_copiadas += len(lote_de_msgs)
        pbar.update(len(lote_de_msgs))
        
        await self._atualizar_indice(nome_topico, link_primeira_midia)
        return True
    
    async def run(self):
        """Executa o fluxo completo: auditar -> comparar -> selecionar datas -> copiar."""
        if not await self._inicializar_entidades():
            return
        
        # Fase 1: Auditoria
        if not await self._executar_auditoria():
            print_error("Auditoria falhou ou foi cancelada.")
            return
        
        # Fase 2: Comparação
        if not self._executar_comparacao():
            return

        # Fase 2.5: Seleção de Datas e Horários
        if self.config.get('automacao_total'):
            print_info("🤖 Modo Automático: Selecionando 'TODAS AS DATAS' e iniciando cópia...")
            self.datas_selecionadas = {'all': 'all'}
        else:
            self.datas_selecionadas = interface.prompt_selecionar_datas_para_copia(self.config['id_origem'])
        
        # Verifica se o dicionário está vazio (usuário cancelou)
        if not self.datas_selecionadas:
            print_warning("Nenhuma data selecionada. A cópia foi cancelada.")
            return
            
        # Verifica se é para copiar tudo ('all': 'all') ou filtrar
        copiar_tudo = False
        if 'all' in self.datas_selecionadas and self.datas_selecionadas['all'] == 'all':
            copiar_tudo = True

        if not copiar_tudo:
            # Extrai as datas para log
            datas_keys = [d for d in self.datas_selecionadas.keys()]
            print_info(f"Filtrando mídias para as datas selecionadas: {', '.join(datas_keys)}")
            
            # Buscar detalhes das mídias pendentes no banco para poder filtrar por data
            # (pois com auditoria otimizada, não temos tudo na memória)
            print_info("⏳ Buscando detalhes das mídias pendentes no banco...")
            detalhes_midias = db.get_media_by_ids(self.config['id_origem'], self.ids_pendentes)
            
            # Criar mapa para acesso rápido: message_id -> dados
            mapa_detalhes = {m['message_id']: m for m in detalhes_midias}
            
            ids_filtrados = []
            for msg_id in self.ids_pendentes:
                # Tenta pegar da memória (fallback) ou do banco
                midia_info = mapa_detalhes.get(int(msg_id)) or self.auditoria_origem.midias_catalogadas.get(int(msg_id))
                
                if midia_info and midia_info.get('date'): # Mudado de 'data' para 'date' conforme schema do banco
                    data_completa = midia_info['date'] # YYYY-MM-DDTHH:MM:SS
                    data_dia = data_completa.split('T')[0]
                    
                    # Verifica se a data está nas permitidas
                    if data_dia in self.datas_selecionadas:
                        filtro_horario = self.datas_selecionadas[data_dia]
                        
                        if filtro_horario == 'all':
                            # Se for 'all', aceita qualquer hora desse dia
                            ids_filtrados.append(msg_id)
                        else:
                            # Se tiver lista de horas, verifica a hora
                            hora_midia = data_completa.split('T')[1][:2] # HH
                            if hora_midia in filtro_horario:
                                ids_filtrados.append(msg_id)
            
            print_info(f"Encontradas {len(ids_filtrados)} mídias pendentes nos filtros selecionados (de um total de {len(self.ids_pendentes)}).")
            self.ids_pendentes = ids_filtrados

            if not self.ids_pendentes:
                print_success("Nenhuma mídia pendente encontrada nos filtros selecionados.")
                return
        
        # Fase 3: Cópia
        await self._executar_copia()