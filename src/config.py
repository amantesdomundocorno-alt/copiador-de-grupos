# config.py
# [S8] e [S13] Configurações Centralizadas do Copiador Indexador

import os
from dataclasses import dataclass, field
from typing import Dict, Any

@dataclass
class RetryConfig:
    """Configurações de retry para operações de rede."""
    max_retries: int = 5  # [S13] Aumentado de 3 para 5
    base_delay: float = 2.0  # Delay base em segundos
    max_delay: float = 60.0  # Delay máximo
    exponential_base: float = 2.0  # Base para backoff exponencial


@dataclass
class NetworkConfig:
    """Configurações de rede e resiliência."""
    connection_timeout: int = 60  # Timeout de conexão em segundos
    read_timeout: int = 120  # Timeout de leitura em segundos
    ping_interval: int = 30  # Intervalo para verificar conexão
    max_reconnect_attempts: int = 10  # Máximo de tentativas de reconexão


@dataclass
class CopyConfig:
    """Configurações de cópia."""
    max_messages_without_media: int = 1000
    batch_size_forum: int = 50  # Mídias por tópico
    batch_size_simple: int = 10  # Mídias por lote em grupos simples
    telegram_char_limit: int = 4000
    default_pause_min: float = 1.0
    default_pause_max: float = 3.0


@dataclass
class BackupConfig:
    """Configurações de backup."""
    max_backups: int = 7
    backup_dir: str = 'dados/backups'
    auto_backup_on_start: bool = True


@dataclass
class LogConfig:
    """Configurações de logging."""
    log_dir: str = 'dados/logs'
    max_log_size_mb: int = 5
    backup_count: int = 3
    log_level: str = 'INFO'
    log_to_console: bool = True


@dataclass
class AppConfig:
    """Configuração principal da aplicação."""
    retry: RetryConfig = field(default_factory=RetryConfig)
    network: NetworkConfig = field(default_factory=NetworkConfig)
    copy: CopyConfig = field(default_factory=CopyConfig)
    backup: BackupConfig = field(default_factory=BackupConfig)
    log: LogConfig = field(default_factory=LogConfig)
    
    # Versão do app
    version: str = "2.0.0"
    
    def to_dict(self) -> Dict[str, Any]:
        """Converte config para dicionário."""
        return {
            'retry': {
                'max_retries': self.retry.max_retries,
                'base_delay': self.retry.base_delay,
                'max_delay': self.retry.max_delay,
                'exponential_base': self.retry.exponential_base,
            },
            'network': {
                'connection_timeout': self.network.connection_timeout,
                'read_timeout': self.network.read_timeout,
                'ping_interval': self.network.ping_interval,
                'max_reconnect_attempts': self.network.max_reconnect_attempts,
            },
            'copy': {
                'max_messages_without_media': self.copy.max_messages_without_media,
                'batch_size_forum': self.copy.batch_size_forum,
                'batch_size_simple': self.copy.batch_size_simple,
                'telegram_char_limit': self.copy.telegram_char_limit,
            },
            'backup': {
                'max_backups': self.backup.max_backups,
                'backup_dir': self.backup.backup_dir,
                'auto_backup_on_start': self.backup.auto_backup_on_start,
            },
            'log': {
                'log_dir': self.log.log_dir,
                'max_log_size_mb': self.log.max_log_size_mb,
                'backup_count': self.log.backup_count,
                'log_level': self.log.log_level,
            },
            'version': self.version,
        }


# Instância global de configuração
config = AppConfig()


def get_config() -> AppConfig:
    """Retorna a configuração global."""
    return config


def get_retry_delay(attempt: int) -> float:
    """
    Calcula o delay para uma tentativa específica usando backoff exponencial.
    
    Args:
        attempt: Número da tentativa (0-indexed)
        
    Returns:
        Delay em segundos
    """
    delay = config.retry.base_delay * (config.retry.exponential_base ** attempt)
    return min(delay, config.retry.max_delay)
