# logger.py
# [S7] Sistema de Logging Profissional para Arquivo

import os
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime

# Diretório de logs
LOGS_DIR = 'dados/logs'

# Configurações
MAX_LOG_SIZE = 5 * 1024 * 1024  # 5MB por arquivo
BACKUP_COUNT = 3  # Mantém 3 arquivos de backup


def setup_logger(name='copiador', level=logging.INFO):
    """
    Configura e retorna um logger com:
    - Saída para arquivo rotativo
    - Formato estruturado
    - Sanitização de dados sensíveis
    """
    # Criar diretório de logs se não existir
    os.makedirs(LOGS_DIR, exist_ok=True)
    
    logger = logging.getLogger(name)
    
    # Evitar configurar múltiplas vezes
    if logger.handlers:
        return logger
    
    logger.setLevel(level)
    
    # Formato do log
    formatter = logging.Formatter(
        '%(asctime)s | %(levelname)-8s | %(module)s:%(lineno)d | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Handler para arquivo rotativo
    log_file = os.path.join(LOGS_DIR, 'copiador.log')
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=MAX_LOG_SIZE,
        backupCount=BACKUP_COUNT,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    
    # Handler para console (apenas warnings e erros)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.WARNING)
    console_handler.setFormatter(formatter)
    
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    logger.info("="*60)
    logger.info(f"Sessão iniciada em {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("="*60)
    
    return logger


def sanitize_log_message(message, sensitive_fields=None):
    """
    Remove ou mascara dados sensíveis de mensagens de log.
    
    Args:
        message: Mensagem a ser sanitizada
        sensitive_fields: Lista de campos a mascarar (ex: ['api_hash', 'password'])
    """
    if sensitive_fields is None:
        sensitive_fields = ['api_hash', 'password', 'token', 'secret']
    
    sanitized = str(message)
    
    for field in sensitive_fields:
        # Mascara valores após o campo
        import re
        pattern = rf"({field}['\"]?\s*[:=]\s*['\"]?)([^'\"]+)(['\"]?)"
        sanitized = re.sub(pattern, rf'\1{"*" * 8}\3', sanitized, flags=re.IGNORECASE)
    
    return sanitized


def log_operation(logger, operation_name, success=True, details=None, error=None):
    """
    Helper para logar operações de forma padronizada.
    
    Args:
        logger: Logger configurado
        operation_name: Nome da operação (ex: 'copiar_midia', 'criar_topico')
        success: Se a operação foi bem sucedida
        details: Dict com detalhes adicionais
        error: Exceção ocorrida (se houver)
    """
    if success:
        msg = f"✅ {operation_name}"
        if details:
            msg += f" | {details}"
        logger.info(msg)
    else:
        msg = f"❌ {operation_name}"
        if details:
            msg += f" | {details}"
        if error:
            msg += f" | Erro: {str(error)}"
        logger.error(msg)


# Logger global pré-configurado
main_logger = setup_logger()


def get_logger():
    """Retorna o logger principal configurado."""
    return main_logger
