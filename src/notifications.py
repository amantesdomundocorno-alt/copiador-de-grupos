# notifications.py
# [S10] Sistema de Notificações Telegram

import asyncio
from typing import Optional
from datetime import datetime

from .logger import get_logger

logger = get_logger()


async def send_notification(
    client,
    message: str,
    parse_mode: str = 'md',
    silent: bool = False
) -> bool:
    """
    Envia notificação para "Mensagens Salvas" do próprio usuário.
    
    Args:
        client: TelegramClient conectado
        message: Mensagem a enviar
        parse_mode: Modo de parsing (md, html)
        silent: Se True, não faz som de notificação
        
    Returns:
        True se enviou com sucesso
    """
    try:
        # Envia para "Mensagens Salvas" (o próprio usuário)
        me = await client.get_me()
        await client.send_message(
            me.id,
            message,
            parse_mode=parse_mode,
            silent=silent
        )
        logger.info(f"Notificação enviada: {message[:50]}...")
        return True
    except Exception as e:
        logger.error(f"Erro ao enviar notificação: {e}")
        return False


async def notify_task_complete(
    client,
    task_name: str,
    success_count: int,
    error_count: int,
    elapsed_seconds: float
):
    """
    Notifica conclusão de tarefa.
    """
    hours = int(elapsed_seconds // 3600)
    minutes = int((elapsed_seconds % 3600) // 60)
    
    status_emoji = "✅" if error_count == 0 else "⚠️"
    
    message = f"""
{status_emoji} **Tarefa Concluída**

📋 **Tarefa:** {task_name}
📊 **Processados:** {success_count:,} com sucesso
❌ **Erros:** {error_count}
⏱️ **Tempo:** {hours}h {minutes}min

🕐 {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}
"""
    
    await send_notification(client, message)


async def notify_error(
    client,
    error_description: str,
    task_name: str = None,
    recoverable: bool = True
):
    """
    Notifica erro crítico.
    """
    severity = "⚠️ AVISO" if recoverable else "🚨 ERRO CRÍTICO"
    
    message = f"""
{severity}

"""
    if task_name:
        message += f"📋 **Tarefa:** {task_name}\n"
    
    message += f"""❌ **Erro:** {error_description}

{"O programa continuará tentando..." if recoverable else "Ação manual necessária."}

🕐 {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}
"""
    
    await send_notification(client, message)


async def notify_reconnected(
    client,
    offline_seconds: float
):
    """
    Notifica que a conexão foi restabelecida.
    """
    minutes = int(offline_seconds // 60)
    seconds = int(offline_seconds % 60)
    
    message = f"""
🔄 **Internet Reconectada**

A conexão foi perdida por {minutes}min {seconds}s e agora foi restabelecida.
O programa retomou as operações automaticamente.

🕐 {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}
"""
    
    await send_notification(client, message)


async def send_daily_summary(
    client,
    stats: dict
):
    """
    Envia resumo diário de atividades.
    
    Args:
        stats: Dicionário com estatísticas do dia
    """
    message = f"""
📊 **Resumo do Dia** - {datetime.now().strftime('%d/%m/%Y')}

📦 **Mídias copiadas:** {stats.get('midias_copiadas', 0):,}
📁 **Grupos auditados:** {stats.get('grupos_auditados', 0)}
⏱️ **Tempo ativo:** {stats.get('tempo_ativo', 'N/A')}
❌ **Erros:** {stats.get('erros', 0)}

🔋 **Status:** Operacional
"""
    
    await send_notification(client, message)


class NotificationManager:
    """
    Gerenciador de notificações com rate limiting.
    Evita spam de notificações.
    """
    
    def __init__(self, client, min_interval_seconds: int = 60):
        self.client = client
        self.min_interval = min_interval_seconds
        self._last_notification_time = 0
        self._pending_notifications = []
        self._enabled = True
    
    def enable(self):
        """Habilita notificações."""
        self._enabled = True
    
    def disable(self):
        """Desabilita notificações."""
        self._enabled = False
    
    async def notify(
        self,
        message: str,
        force: bool = False,
        **kwargs
    ) -> bool:
        """
        Envia notificação respeitando rate limiting.
        
        Args:
            message: Mensagem a enviar
            force: Se True, ignora rate limiting
        """
        if not self._enabled:
            return False
        
        now = asyncio.get_event_loop().time()
        
        if not force and (now - self._last_notification_time) < self.min_interval:
            # Guardar para enviar depois
            self._pending_notifications.append((message, kwargs))
            return False
        
        self._last_notification_time = now
        return await send_notification(self.client, message, **kwargs)
    
    async def flush_pending(self):
        """Envia todas as notificações pendentes em uma única mensagem."""
        if not self._pending_notifications:
            return
        
        combined = "📋 **Notificações Pendentes:**\n\n"
        for msg, _ in self._pending_notifications[-5:]:  # Últimas 5
            combined += f"---\n{msg}\n"
        
        await send_notification(self.client, combined)
        self._pending_notifications.clear()
