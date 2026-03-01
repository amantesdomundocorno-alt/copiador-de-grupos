# base_copiador.py
# [S6] Classe Base Unificada para Copiadores

import asyncio
import random
import time
import os
import math
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List
from tqdm.asyncio import tqdm
from telethon.errors.rpcerrorlist import MessageTooLongError, FloodWaitError

from . import gerenciador_dados as dados
from .estilo import (
    print_success, print_error, print_warning, print_info,
    print_section_header, countdown_timer
)
from .interface import send_message_with_retry
from .limiter import global_limiter
from .database import db
from .config import get_config, get_retry_delay
from .logger import get_logger
from .network_resilience import NetworkResilientOperation, reconnect_telegram_client

# Constante de segurança para o limite de caracteres do Telegram
TELEGRAM_CHAR_LIMIT = 4000


class BaseCopiador(ABC):
    """
    Classe base abstrata para todos os copiadores.
    Implementa funcionalidades comuns para evitar duplicação de código.
    """
    
    def __init__(self, client, task_config: Dict[str, Any], task_key: str):
        self.client = client
        self.config = task_config
        self.task_key = task_key
        
        # Configurações globais
        self._app_config = get_config()
        self._logger = get_logger()
        
        # Configurações de cópia
        self.copy_speed = task_config.get('copy_speed', 'traditional')
        self.media_per_pause = task_config.get('media_per_pause')
        self.pause_duration = task_config.get('pause_duration')
        
        # Entidades Telethon
        self.origem = None
        self.destino = None
        
        # Configuração de retry
        self.max_retries = self._app_config.retry.max_retries
        
        # Contadores
        self.total_midias_copiadas = 0
        self.falhas_registradas = 0
        self.media_since_last_pause = 0
        
        # Índice
        self.id_msg_indice = None
        
        # Network resilience
        self._resilient_op = NetworkResilientOperation(
            checkpoint_callback=self._salvar_checkpoint,
            on_reconnect=lambda: reconnect_telegram_client(self.client)
        )
    
    # ========================================
    # MÉTODOS ABSTRATOS (devem ser implementados)
    # ========================================
    
    @abstractmethod
    async def _executar_copia(self, pbar) -> None:
        """Executa a lógica principal de cópia. Deve ser implementado pelas subclasses."""
        pass
    
    @abstractmethod
    def _carregar_progresso(self) -> None:
        """Carrega o progresso salvo. Deve ser implementado pelas subclasses."""
        pass
    
    # ========================================
    # MÉTODOS COMUNS
    # ========================================
    
    async def _inicializar_entidades(self) -> bool:
        """Busca e valida as entidades de origem e destino."""
        try:
            self.origem = await self.client.get_entity(self.config['id_origem'])
            self.destino = await self.client.get_entity(self.config['id_destino'])
            self._logger.info(f"Entidades inicializadas: {self.config['nome_origem']} -> {self.config['nome_destino']}")
            return True
        except Exception as e:
            print_error(f"Erro fatal ao buscar grupos: {e}")
            print_error("Verifique se você ainda está nos dois grupos e tente novamente.")
            self._logger.error(f"Erro ao inicializar entidades: {e}")
            return False
    
    def _salvar_checkpoint(self) -> None:
        """
        Salva checkpoint do progresso atual.
        Chamado automaticamente pelo sistema de resiliência de rede.
        """
        progress_data = {
            'total_midias_copiadas': self.total_midias_copiadas,
            'id_msg_indice': self.id_msg_indice,
        }
        dados.save_progress(self.task_key, progress_data)
        self._logger.info(f"Checkpoint salvo: {self.total_midias_copiadas} mídias")
    
    async def _pausa_aleatoria_segura(self) -> None:
        """
        Pausa aleatória para simular comportamento humano.
        Usada no modo 'traditional'.
        """
        if self.copy_speed == 'traditional':
            delay = random.uniform(
                self._app_config.copy.default_pause_min,
                self._app_config.copy.default_pause_max
            )
            await asyncio.sleep(delay)
    
    async def _handle_custom_pause(self, media_count: int) -> None:
        """Gerencia pausas personalizadas após N mídias."""
        if self.copy_speed == 'custom' and self.media_per_pause and self.pause_duration:
            self.media_since_last_pause += media_count
            if self.media_since_last_pause >= self.media_per_pause:
                await countdown_timer(self.pause_duration, reason="Pausa personalizada")
                self.media_since_last_pause = 0
    
    async def _atualizar_indice(self, titulo_topico: str, link_primeira_midia: str) -> None:
        """
        Atualiza a mensagem de índice com paginação automática.
        """
        if not self.config.get('id_topico_indice'):
            return
        
        try:
            num_linha = math.ceil(self.total_midias_copiadas / self.config.get('lote_size', 50))
            nova_linha = f"{num_linha} - [{titulo_topico}]({link_primeira_midia})"
            
            if not self.id_msg_indice:
                # Criar nova mensagem de índice
                cabecalho = f"**ÍNDICE DE MÍDIAS - {self.config['nome_origem']}**\n\n"
                msg = await self.client.send_message(
                    self.destino,
                    message=f"{cabecalho}{nova_linha}",
                    reply_to=self.config['id_topico_indice'],
                    parse_mode='md'
                )
                self.id_msg_indice = msg.id
                self._logger.info("Nova mensagem de índice criada")
            else:
                # Editar mensagem existente
                msg_antiga = await self.client.get_messages(self.destino, ids=self.id_msg_indice)
                
                if not msg_antiga:
                    self.id_msg_indice = None
                    await self._atualizar_indice(titulo_topico, link_primeira_midia)
                    return
                
                novo_texto = f"{msg_antiga.text}\n{nova_linha}"
                
                if len(novo_texto) > TELEGRAM_CHAR_LIMIT:
                    # Criar nova página de índice
                    cabecalho = "**ÍNDICE DE MÍDIAS (Continuação)**\n\n"
                    msg = await self.client.send_message(
                        self.destino,
                        message=f"{cabecalho}{nova_linha}",
                        reply_to=self.config['id_topico_indice'],
                        parse_mode='md'
                    )
                    self.id_msg_indice = msg.id
                else:
                    await self.client.edit_message(
                        self.destino,
                        message=self.id_msg_indice,
                        text=novo_texto,
                        parse_mode='md'
                    )
            
            print_success("Índice atualizado!")
            
        except MessageTooLongError:
            # Criar nova página
            cabecalho = "**ÍNDICE DE MÍDIAS (Continuação)**\n\n"
            msg = await self.client.send_message(
                self.destino,
                message=f"{cabecalho}{nova_linha}",
                reply_to=self.config['id_topico_indice'],
                parse_mode='md'
            )
            self.id_msg_indice = msg.id
            
        except Exception as e:
            print_error(f"Erro ao atualizar índice: {e}")
            self._logger.error(f"Erro ao atualizar índice: {e}")
    
    async def _enviar_lote_com_retry(
        self,
        mensagens: List,
        reply_to: Optional[int] = None
    ) -> bool:
        """
        Envia um lote de mensagens com retry automático.
        
        Returns:
            True se enviou com sucesso
        """
        for attempt in range(self.max_retries):
            try:
                await send_message_with_retry(
                    self.client,
                    self.destino,
                    copy_speed=self.copy_speed,
                    file=[m.media for m in mensagens],
                    reply_to=reply_to
                )
                return True
                
            except FloodWaitError as e:
                await global_limiter.report_flood_wait(e.seconds)
                
            except Exception as e:
                if attempt == self.max_retries - 1:
                    self._logger.error(f"Falha ao enviar lote após {self.max_retries} tentativas: {e}")
                    return False
                
                wait_time = get_retry_delay(attempt)
                self._logger.warning(f"Retry {attempt+1}/{self.max_retries}, aguardando {wait_time:.1f}s")
                await asyncio.sleep(wait_time)
        
        return False
    
    async def run(self) -> None:
        """Ponto de entrada principal para executar a tarefa."""
        if not await self._inicializar_entidades():
            return
        
        self._carregar_progresso()
        
        print_section_header("Iniciando Cópia")
        print_info(f"Origem: {self.config['nome_origem']}")
        print_info(f"Destino: {self.config['nome_destino']}")
        print_info(f"Modo: {self.config.get('modo', 'N/A')}")
        
        self._logger.info(f"Iniciando cópia: {self.config['nome_origem']} -> {self.config['nome_destino']}")
        
        # Cria barra de progresso
        pbar = tqdm(
            initial=0,
            desc="Mídias Copiadas",
            unit=" mídia",
            dynamic_ncols=True
        )
        
        try:
            await self._executar_copia(pbar)
            print_success("\nTarefa de cópia concluída!")
            self._logger.info(f"Cópia concluída: {self.total_midias_copiadas} mídias")
            
        except KeyboardInterrupt:
            print_warning("\nCópia interrompida pelo usuário. Progresso salvo.")
            self._salvar_checkpoint()
            self._logger.info("Cópia interrompida pelo usuário")
            
        except Exception as e:
            print_error(f"\nErro durante a cópia: {e}")
            self._salvar_checkpoint()
            self._logger.error(f"Erro durante cópia: {e}")
            
        finally:
            pbar.close()
