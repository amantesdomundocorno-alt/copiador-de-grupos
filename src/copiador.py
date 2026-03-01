# copiador.py

import asyncio
import random
import time
import os
import sys
import math
from tqdm.asyncio import tqdm
from telethon import functions
from telethon.tl.types import InputPeerChannel
from telethon.errors.rpcerrorlist import MessageTooLongError, FloodWaitError

# Importa de nossos outros arquivos
from . import gerenciador_dados as dados
from .estilo import (
    print_success, print_error, print_warning, print_info, 
    countdown_timer, print_section_header
)
from .interface import send_message_with_retry
from .limiter import global_limiter
from .database import db
from .config import get_config, get_retry_delay  # [S13] Configuração centralizada
from .logger import get_logger  # [S7] Logger

# Constante de segurança para o limite de caracteres do Telegram
TELEGRAM_CHAR_LIMIT = 4000 

class ClonadorCatalogador:
    def __init__(self, client, task_config, task_key, file_type_filter='all'):
        self.client = client
        self.config = task_config
        self.task_key = task_key
        self.copy_speed = task_config.get('copy_speed', 'traditional')
        self.media_per_pause = task_config.get('media_per_pause')
        self.pause_duration = task_config.get('pause_duration')
        
        # Entidades Telethon
        self.origem = None
        self.destino = None
        
        # Dados de Progresso
        self.progress_data = {}
        self.ultimo_id_copiado = 0
        self.total_midias_copiadas = 0
        self.id_msg_indice = None
        self.ultimo_save_time = time.time()
        self.media_since_last_pause = 0
        
        # [S13] Configuração de retry do config.py
        self._config = get_config()
        self.max_retries = self._config.retry.max_retries
        self.falhas_registradas = 0
        self._logger = get_logger()

    async def _inicializar_entidades(self):
        """Busca e valida as entidades de origem e destino."""
        try:
            self.origem = await self.client.get_entity(self.config['id_origem'])
            self.destino = await self.client.get_entity(self.config['id_destino'])
            return True
        except Exception as e:
            print_error(f"Erro fatal ao buscar grupos: {e}")
            print_error("Verifique se você ainda está nos dois grupos e tente novamente.")
            return False

    def _carregar_progresso(self):
        """Carrega o progresso salvo para esta tarefa."""
        self.progress_data = dados.get_task_progress(self.task_key)
        
        if self.config['modo_copia'] == 'tudo':
            self.ultimo_id_copiado = self.progress_data.get('ultimo_id_copiado', 0)
            self.total_midias_copiadas = self.progress_data.get('total_midias_copiadas', 0)
            self.id_msg_indice = self.progress_data.get('id_msg_indice', None)
            print_info(f"Progresso carregado: {self.total_midias_copiadas} mídias já copiadas.")
            print_info(f"Continuando a partir do ID de mensagem: {self.ultimo_id_copiado}")
        else:
            print_warning("Modo 'Quantidade Específica': O progresso anterior será ignorado.")
            self.ultimo_id_copiado = 0
            self.total_midias_copiadas = 0
            self.id_msg_indice = None


    def _salvar_progresso(self, ultimo_id_processado):
        """
        Salva o progresso no arquivo JSON usando o gerenciador_dados (Write-Safe).
        """
        if self.config['modo_copia'] != 'tudo':
            return
            
        self.ultimo_id_copiado = ultimo_id_processado
        
        novos_dados_progresso = {
            'ultimo_id_copiado': self.ultimo_id_copiado,
            'total_midias_copiadas': self.total_midias_copiadas,
            'id_msg_indice': self.id_msg_indice
        }
        
        dados.save_progress(self.task_key, novos_dados_progresso)
        self.ultimo_save_time = time.time() 

    async def _pausa_aleatoria_segura(self):
        """
        DEPRECADO: A pausa agora é gerenciada pelo global_limiter dentro do send_message.
        Mantido apenas para lógica de pausas 'estéticas' ou do modo 'custom'.
        """
        if self.copy_speed == 'traditional':
             # Com o limiter, pausas manuais longas são menos necessárias, 
             # mas mantemos uma pequena variação para parecer humano.
            await asyncio.sleep(random.uniform(1.0, 3.0))

    async def _handle_custom_pause(self, media_count_in_lote):
        if self.copy_speed == 'custom' and self.media_per_pause and self.pause_duration:
            self.media_since_last_pause += media_count_in_lote
            if self.media_since_last_pause >= self.media_per_pause:
                await countdown_timer(self.pause_duration, reason="Pausa personalizada")
                self.media_since_last_pause = 0

    async def _atualizar_indice(self, novo_titulo_topico, link_primeira_midia):
        """
        Edita ou cria a mensagem de índice, com paginação automática se 
        a mensagem ficar cheia.
        """
        if not self.config.get('id_topico_indice'):
            return 

        try:
            num_linha = math.ceil(self.total_midias_copiadas / self.config['lote_size'])
            nova_linha_indice = f"{num_linha} - [{novo_titulo_topico}]({link_primeira_midia})"

            if not self.id_msg_indice:
                print_info("Criando nova mensagem de índice...")
                cabecalho = f"**ÍNDICE DE MÍDIAS - {self.config['nome_origem']}**\n\n"
                msg_enviada = await self.client.send_message(
                    self.destino,
                    message=f"{cabecalho}{nova_linha_indice}",
                    reply_to=self.config['id_topico_indice'],
                    parse_mode='md'
                )
                self.id_msg_indice = msg_enviada.id
            else:
                print_info(f"Tentando editar mensagem de índice (ID: {self.id_msg_indice})...")
                msg_antiga = await self.client.get_messages(self.destino, ids=self.id_msg_indice)
                
                if not msg_antiga:
                    print_warning("Mensagem de índice não encontrada (pode ter sido deletada). Criando uma nova.")
                    self.id_msg_indice = None
                    await self._atualizar_indice(novo_titulo_topico, link_primeira_midia)
                    return

                texto_antigo = msg_antiga.text
                novo_texto = f"{texto_antigo}\n{nova_linha_indice}"

                if len(novo_texto) > TELEGRAM_CHAR_LIMIT:
                    print_warning("Mensagem de índice cheia. Criando uma nova página de índice...")
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

            print_success("Índice atualizado com sucesso!")

        except MessageTooLongError:
            print_warning("Mensagem de índice cheia (Detectado por Erro). Criando uma nova página de índice...")
            cabecalho_continua = f"**ÍNDICE DE MÍDIAS (Continuação)**\n\n"
            msg_enviada = await self.client.send_message(
                self.destino,
                message=f"{cabecalho_continua}{nova_linha_indice}", 
                reply_to=self.config['id_topico_indice'],
                parse_mode='md'
            )
            self.id_msg_indice = msg_enviada.id
            print_success("Índice atualizado com sucesso!")

        except Exception as e:
            print_error(f"Falha CRÍTICA ao atualizar índice: {e}")
            print_warning("O progresso da cópia continuará, mas o índice está dessincronizado.")
            self.id_msg_indice = None

    async def _run_modo_forum(self, pbar):
        """Lógica de cópia para Fóruns (Modo A)."""
        lote_atual = []
        ultimo_id_processado = self.ultimo_id_copiado
        
        media_count = 0 
        limit_desejado = self.config['quantidade']
        mensagens_sem_midia_consecutivas = 0
        MAX_MENSAGENS_SEM_MIDIA = 1000  # Para na iteração após 1000 mensagens consecutivas sem mídia

        reverse_flag = self.config['ordem'] == 'crescente'
        
        # CORREÇÃO CRÍTICA: Para ordem crescente, usamos min_id
        # Para ordem decrescente, NÃO usamos offset_id (isso estava causando o bug)
        # Deixamos o Telegram iterar naturalmente
        
        if self.config['modo_copia'] == 'tudo' and reverse_flag:
            # Modo crescente: pega mensagens COM ID MAIOR que o salvo
            print_info(f"Modo crescente: Buscando mensagens com ID > {self.ultimo_id_copiado}")
            iterador = self.client.iter_messages(
                self.origem,
                reverse=True,
                min_id=self.ultimo_id_copiado,
                limit=None
            )
        elif self.config['modo_copia'] == 'tudo' and not reverse_flag:
            # Modo decrescente COM progresso salvo: precisamos buscar mensagens ANTERIORES ao último ID
            print_info(f"Modo decrescente: Buscando mensagens com ID < {self.ultimo_id_copiado}")
            iterador = self.client.iter_messages(
                self.origem,
                reverse=False,
                offset_id=self.ultimo_id_copiado if self.ultimo_id_copiado > 0 else 0,
                limit=None
            )
        else:
            # Modo quantidade específica: começa do início
            iterador = self.client.iter_messages(
                self.origem,
                reverse=reverse_flag,
                limit=None
            )
        
        mensagens_processadas = 0
        
        async for message in iterador:
            mensagens_processadas += 1
            ultimo_id_processado = message.id
            
            # Log de progresso a cada 100 mensagens
            if mensagens_processadas % 100 == 0:
                print_info(f"Processadas {mensagens_processadas} mensagens. Último ID: {ultimo_id_processado}")
            
            if not message.media:
                mensagens_sem_midia_consecutivas += 1
                
                # Se passou de X mensagens sem mídia, pode ter chegado no final
                if mensagens_sem_midia_consecutivas >= MAX_MENSAGENS_SEM_MIDIA:
                    print_warning(f"Detectadas {MAX_MENSAGENS_SEM_MIDIA} mensagens consecutivas sem mídia.")
                    print_info("Provavelmente chegamos ao final das mídias disponíveis.")
                    break
                    
                continue
            
            # Resetar contador quando encontrar mídia
            mensagens_sem_midia_consecutivas = 0

            media_count += 1
            lote_atual.append(message)
            
            lote_cheio = len(lote_atual) >= self.config['lote_size']
            limite_atingido = limit_desejado and media_count >= limit_desejado

            if lote_cheio or limite_atingido:
                
                lote_para_processar = lote_atual
                
                if limite_atingido:
                    midias_ja_contadas = media_count - len(lote_atual)
                    midias_necessarias = limit_desejado - midias_ja_contadas
                    lote_para_processar = lote_atual[:midias_necessarias]

                sucesso = await self._processar_lote_forum(lote_para_processar, pbar)
                
                if sucesso:
                    lote_atual = [] 
                    self._salvar_progresso(ultimo_id_processado)
                else:
                    print_error("Falha ao processar o lote. O lote será ignorado e a tarefa continuará.")
                    print_warning("O progresso NÃO foi salvo para que este lote seja tentado novamente na próxima execução.")
                    lote_atual = [] # Limpa o lote para não tentar de novo
                    continue # Pula para a próxima iteração do loop principal

                if limite_atingido:
                    print_info(f"Limite de {limit_desejado} mídias atingido.")
                    break

        # Processar lote final se houver
        if lote_atual and not (limit_desejado and media_count >= limit_desejado):
            sucesso = await self._processar_lote_forum(lote_atual, pbar)
            if sucesso:
                self._salvar_progresso(ultimo_id_processado)
        
        print_info(f"Total de mensagens processadas nesta sessão: {mensagens_processadas}")
        print_info(f"Total de mídias encontradas nesta sessão: {media_count}")

    async def _processar_lote_forum(self, lote_de_midias, pbar):
        """
        Cria o tópico, envia as mídias e atualiza o índice.
        Retorna True se bem-sucedido, False se falhar.
        """
        if not lote_de_midias:
            return True

        contador_inicio = self.total_midias_copiadas + 1
        contador_fim = self.total_midias_copiadas + len(lote_de_midias)
        nome_topico = f"Mídias ({contador_inicio} a {contador_fim})"

        print_info(f"Criando tópico-lote: '{nome_topico}'")
        
        # Limiter também espera antes de criar tópico
        await global_limiter.wait(cost=2) # Tópicos custam mais

        id_novo_topico = None
        while True:  # Loop para tentar criar o tópico
            try:
                updates = await self.client(functions.channels.CreateForumTopicRequest(
                    channel=self.destino,
                    title=nome_topico,
                    random_id=int.from_bytes(os.urandom(8), 'big', signed=True)
                ))
                id_novo_topico = updates.updates[0].id
                break  # Sucesso, sai do loop

            except FloodWaitError as e:
                await global_limiter.report_flood_wait(e.seconds)
                continue

            except Exception as e:
                print_error(f"Falha ao criar tópico '{nome_topico}': {e}")
                if self.copy_speed == 'traditional':
                    await self._pausa_aleatoria_segura()
                return False  # Falha crítica, desiste deste lote

        # Se o tópico não pôde ser criado após as tentativas, não podemos continuar
        if id_novo_topico is None:
            print_error(f"Não foi possível criar o tópico '{nome_topico}' após as tentativas. O lote será ignorado.")
            return False

        link_primeira_midia = None
        for i in range(0, len(lote_de_midias), 10):
            sub_lote = lote_de_midias[i:i+10]
            
            await send_message_with_retry(
                self.client,
                self.destino,
                copy_speed=self.copy_speed,
                file=[m.media for m in sub_lote],
                reply_to=id_novo_topico
            )
            
            if i == 0:
                try:
                    primeira_msg_album = (await self.client.get_messages(self.destino, reply_to=id_novo_topico, limit=1))[0]
                    link_primeira_midia = f"https://t.me/c/{self.destino.id}/{id_novo_topico}/{primeira_msg_album.id}"
                except Exception as e:
                    print_warning(f"Não foi possível pegar o link da mídia: {e}")

            if self.copy_speed == 'traditional':
                await self._pausa_aleatoria_segura()
            await self._handle_custom_pause(len(sub_lote))

        if not link_primeira_midia:
            print_warning("Não foi possível gerar link para o índice.")
            link_primeira_midia = f"https://t.me/c/{self.destino.id}/{id_novo_topico}"

        self.total_midias_copiadas += len(lote_de_midias)
        pbar.update(len(lote_de_midias))
        
        await self._atualizar_indice(nome_topico, link_primeira_midia)
        return True 

    async def _run_modo_simples(self, pbar):
        """Lógica de cópia para Grupos Tradicionais (Modo B)."""
        lote_atual = []
        ultimo_id_processado = self.ultimo_id_copiado
        
        media_count = 0
        limit_desejado = self.config['quantidade']
        mensagens_sem_midia_consecutivas = 0
        MAX_MENSAGENS_SEM_MIDIA = 1000

        reverse_flag = self.config['ordem'] == 'crescente'
        
        if self.config['modo_copia'] == 'tudo' and reverse_flag:
            print_info(f"Modo crescente: Buscando mensagens com ID > {self.ultimo_id_copiado}")
            iterador = self.client.iter_messages(
                self.origem,
                reverse=True,
                min_id=self.ultimo_id_copiado,
                limit=None
            )
        elif self.config['modo_copia'] == 'tudo' and not reverse_flag:
            print_info(f"Modo decrescente: Buscando mensagens com ID < {self.ultimo_id_copiado}")
            iterador = self.client.iter_messages(
                self.origem,
                reverse=False,
                offset_id=self.ultimo_id_copiado if self.ultimo_id_copiado > 0 else 0,
                limit=None
            )
        else:
            iterador = self.client.iter_messages(
                self.origem,
                reverse=reverse_flag,
                limit=None
            )
        
        mensagens_processadas = 0
        
        async for message in iterador:
            mensagens_processadas += 1
            ultimo_id_processado = message.id
            
            if mensagens_processadas % 100 == 0:
                print_info(f"Processadas {mensagens_processadas} mensagens. Último ID: {ultimo_id_processado}")
            
            if not message.media:
                mensagens_sem_midia_consecutivas += 1
                
                if mensagens_sem_midia_consecutivas >= MAX_MENSAGENS_SEM_MIDIA:
                    print_warning(f"Detectadas {MAX_MENSAGENS_SEM_MIDIA} mensagens consecutivas sem mídia.")
                    print_info("Provavelmente chegamos ao final das mídias disponíveis.")
                    break
                    
                continue
            
            mensagens_sem_midia_consecutivas = 0

            media_count += 1
            lote_atual.append(message)
            
            lote_cheio = len(lote_atual) >= 10 
            limite_atingido = limit_desejado and media_count >= limit_desejado

            if lote_cheio or limite_atingido:
                
                lote_para_processar = lote_atual
                
                if limite_atingido:
                    midias_ja_contadas = media_count - len(lote_atual)
                    midias_necessarias = limit_desejado - midias_ja_contadas
                    lote_para_processar = lote_atual[:midias_necessarias]

                await send_message_with_retry(
                    self.client,
                    self.destino,
                    copy_speed=self.copy_speed,
                    file=[m.media for m in lote_para_processar]
                )
                
                self.total_midias_copiadas += len(lote_para_processar)
                pbar.update(len(lote_para_processar))
                
                if self.copy_speed == 'traditional':
                    await self._pausa_aleatoria_segura()
                await self._handle_custom_pause(len(lote_para_processar))

                self._salvar_progresso(ultimo_id_processado)
                lote_atual = []

                if limite_atingido:
                    print_info(f"Limite de {limit_desejado} mídias atingido.")
                    break 

        if lote_atual and not (limit_desejado and media_count >= limit_desejado):
            await send_message_with_retry(
                self.client,
                self.destino,
                copy_speed=self.copy_speed,
                file=[m.media for m in lote_atual]
            )
            self.total_midias_copiadas += len(lote_atual)
            pbar.update(len(lote_atual))
            if self.copy_speed == 'traditional':
                await self._pausa_aleatoria_segura()
            await self._handle_custom_pause(len(lote_atual))
            self._salvar_progresso(ultimo_id_processado)
        
        print_info(f"Total de mensagens processadas nesta sessão: {mensagens_processadas}")
        print_info(f"Total de mídias encontradas nesta sessão: {media_count}")

    async def run(self):
        """Ponto de entrada principal para executar a tarefa."""
        if not await self._inicializar_entidades():
            return
        
        self._carregar_progresso()
        
        print_section_header("Iniciando Cópia")
        print_info(f"Origem: {self.config['nome_origem']}")
        print_info(f"Destino: {self.config['nome_destino']}")
        print_info(f"Modo: {self.config['modo']}")
        
        pbar = tqdm(
            initial=0,
            desc="Mídias Copiadas (nesta sessão)",
            unit=" mídia",
            dynamic_ncols=True,
            file=sys.stderr
        )
        
        try:
            if self.config['modo'] == "Fórum (Indexado)":
                await self._run_modo_forum(pbar)
            else:
                await self._run_modo_simples(pbar)
            
            print_success("\nTarefa de cópia concluída!")

        except KeyboardInterrupt:
            print_warning("\nCópia interrompida pelo usuário. O progresso foi salvo.")
        except Exception as e:
            print_error(f"\nErro fatal durante a cópia: {e}")
            print_error("O progresso foi salvo até o último lote bem-sucedido.")
        finally:
            pbar.close() 
            
            if self.config['modo_copia'] == 'tudo' and self.ultimo_id_copiado > self.progress_data.get('ultimo_id_copiado', 0):
                self._salvar_progresso(self.ultimo_id_copiado)
                print_info("Progresso final salvo com segurança.")