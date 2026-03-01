# network_resilience.py
# [S1] Sistema Anti-Queda de Internet
# Detecta perda de conexão, salva checkpoint, reconecta e resume

import asyncio
import socket
import time
from typing import Callable, Any, Optional
from functools import wraps

from .logger import get_logger
from .config import get_config, get_retry_delay
from .estilo import print_warning, print_info, print_success, print_error, countdown_timer

logger = get_logger()
config = get_config()


class NetworkError(Exception):
    """Exceção customizada para erros de rede."""
    pass


class ConnectionLostError(NetworkError):
    """Conexão com internet perdida."""
    pass


class ReconnectionFailedError(NetworkError):
    """Falha ao reconectar após múltiplas tentativas."""
    pass


async def check_internet_connection(timeout: float = 5.0) -> bool:
    """
    Verifica se há conexão com a internet.
    Tenta conectar com servidores DNS confiáveis.
    
    Returns:
        True se conectado, False caso contrário
    """
    # Lista de servidores DNS para testar
    dns_servers = [
        ("8.8.8.8", 53),      # Google DNS
        ("1.1.1.1", 53),       # Cloudflare DNS
        ("208.67.222.222", 53) # OpenDNS
    ]
    
    for host, port in dns_servers:
        try:
            # Tenta conexão TCP rápida
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=timeout
            )
            writer.close()
            await writer.wait_closed()
            return True
        except (asyncio.TimeoutError, OSError, ConnectionRefusedError):
            continue
    
    return False


async def wait_for_internet(max_wait_seconds: int = 300, check_interval: int = 5) -> bool:
    """
    Aguarda até que a conexão com internet seja restabelecida.
    
    Args:
        max_wait_seconds: Tempo máximo de espera (default: 5 minutos)
        check_interval: Intervalo entre verificações (default: 5 segundos)
        
    Returns:
        True se reconectou, False se timeout
    """
    start_time = time.time()
    attempt = 0
    
    print_warning("\n⚠️ Conexão com internet perdida!")
    print_info("Aguardando reconexão...")
    
    while (time.time() - start_time) < max_wait_seconds:
        attempt += 1
        elapsed = int(time.time() - start_time)
        remaining = max_wait_seconds - elapsed
        
        print(f"\r   ⏳ Tentativa {attempt} | Tempo aguardando: {elapsed}s | Restante: {remaining}s   ", end='', flush=True)
        
        if await check_internet_connection():
            print()  # Nova linha após \r
            print_success("✅ Conexão restabelecida!")
            logger.info(f"Internet reconectada após {elapsed} segundos e {attempt} tentativas")
            return True
        
        await asyncio.sleep(check_interval)
    
    print()
    print_error(f"❌ Timeout: Não foi possível reconectar em {max_wait_seconds} segundos")
    logger.error(f"Falha na reconexão após {max_wait_seconds}s")
    return False


class NetworkResilientOperation:
    """
    Wrapper para operações que precisam sobreviver a quedas de conexão.
    
    Uso:
        async with NetworkResilientOperation(checkpoint_fn) as op:
            result = await op.execute(my_async_operation)
    """
    
    def __init__(
        self,
        checkpoint_callback: Optional[Callable] = None,
        max_retries: int = None,
        on_reconnect: Optional[Callable] = None
    ):
        """
        Args:
            checkpoint_callback: Função para salvar estado atual antes de tentar reconectar
            max_retries: Número máximo de tentativas de reconexão
            on_reconnect: Callback executado após reconexão bem-sucedida
        """
        self.checkpoint_callback = checkpoint_callback
        self.max_retries = max_retries or config.network.max_reconnect_attempts
        self.on_reconnect = on_reconnect
        self._is_connected = True
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass
    
    async def execute(
        self,
        operation: Callable,
        *args,
        operation_name: str = "operação",
        **kwargs
    ) -> Any:
        """
        Executa uma operação com proteção contra queda de internet.
        
        Args:
            operation: Função async a ser executada
            operation_name: Nome para logs
            *args, **kwargs: Argumentos para a operação
            
        Returns:
            Resultado da operação
            
        Raises:
            ReconnectionFailedError: Se não conseguir reconectar
        """
        attempt = 0
        last_error = None
        
        while attempt < self.max_retries:
            try:
                # Verifica conexão antes (evita espera desnecessária)
                if attempt > 0 and not await check_internet_connection(timeout=2.0):
                    raise ConnectionLostError("Sem conexão com internet")
                
                # Executa a operação com timeout
                result = await asyncio.wait_for(
                    operation(*args, **kwargs),
                    timeout=config.network.read_timeout
                )
                
                # Sucesso - reseta estado
                if attempt > 0:
                    logger.info(f"Operação '{operation_name}' bem-sucedida após {attempt} retries")
                
                return result
                
            except (asyncio.TimeoutError, OSError, ConnectionError) as e:
                last_error = e
                attempt += 1
                
                logger.warning(f"Erro de conexão em '{operation_name}': {e} (tentativa {attempt}/{self.max_retries})")
                
                # Salva checkpoint antes de tentar reconectar
                if self.checkpoint_callback:
                    try:
                        logger.info("Salvando checkpoint...")
                        self.checkpoint_callback()
                    except Exception as cp_error:
                        logger.error(f"Erro ao salvar checkpoint: {cp_error}")
                
                # Tenta reconectar
                if not await wait_for_internet():
                    raise ReconnectionFailedError(
                        f"Falha ao reconectar após {self.max_retries} tentativas"
                    )
                
                # Callback de reconexão (ex: reconectar cliente Telegram)
                if self.on_reconnect:
                    try:
                        await self.on_reconnect()
                    except Exception as rc_error:
                        logger.error(f"Erro no callback de reconexão: {rc_error}")
                
                # Backoff antes de tentar novamente
                delay = get_retry_delay(attempt)
                await asyncio.sleep(delay)
        
        raise ReconnectionFailedError(
            f"Operação '{operation_name}' falhou após {self.max_retries} tentativas. Último erro: {last_error}"
        )


def with_network_resilience(checkpoint_fn: Callable = None, operation_name: str = "operação"):
    """
    Decorator para adicionar resiliência de rede a funções async.
    
    Uso:
        @with_network_resilience(checkpoint_fn=salvar_progresso)
        async def copiar_midia():
            ...
    """
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            resilient_op = NetworkResilientOperation(checkpoint_callback=checkpoint_fn)
            return await resilient_op.execute(
                func,
                *args,
                operation_name=operation_name or func.__name__,
                **kwargs
            )
        return wrapper
    return decorator


async def reconnect_telegram_client(client) -> bool:
    """
    Reconecta um cliente Telegram após perda de conexão.
    
    Args:
        client: Instância do TelegramClient
        
    Returns:
        True se reconectou, False caso contrário
    """
    try:
        if client.is_connected():
            await client.disconnect()
        
        print_info("Reconectando cliente Telegram...")
        
        await client.connect()
        
        if await client.is_user_authorized():
            print_success("Cliente Telegram reconectado!")
            logger.info("Cliente Telegram reconectado com sucesso")
            return True
        else:
            logger.error("Cliente Telegram não está autorizado após reconexão")
            return False
            
    except Exception as e:
        logger.error(f"Erro ao reconectar cliente Telegram: {e}")
        return False
