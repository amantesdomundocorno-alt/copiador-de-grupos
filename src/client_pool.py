# client_pool.py
# Sistema de rotação de múltiplas contas para aumentar velocidade de cópia

import asyncio
from telethon import TelegramClient
from .estilo import print_info, print_success, print_warning, print_error
from .limiter import RateLimiter
from . import gerenciador_dados as dados

class ClientPool:
    """
    Gerencia múltiplos clientes Telegram para rotação round-robin.
    Cada cliente tem seu próprio rate limiter independente.
    """
    
    def __init__(self):
        self.clients = []  # Lista de (client, telefone) conectados
        self.limiters = {}  # limiter por telefone
        self.current_index = 0
        self._lock = asyncio.Lock()
    
    async def connect_all_accounts(self):
        """
        Conecta todas as contas disponíveis no settings.json.
        Retorna o número de contas conectadas com sucesso.
        """
        settings = dados.load_settings()
        contas_conectadas = 0
        
        for key, conta_info in settings.items():
            if key == 'ultima_conta' or not isinstance(conta_info, dict):
                continue
            
            telefone = conta_info.get('telefone')
            api_id = conta_info.get('api_id')
            api_hash = conta_info.get('api_hash')
            
            if not all([telefone, api_id, api_hash]):
                continue
            
            try:
                client = await self._connect_single(telefone, api_id, api_hash)
                if client:
                    self.clients.append((client, telefone))
                    # Cada conta tem seu próprio limiter
                    self.limiters[telefone] = RateLimiter(actions_per_minute=18, burst_limit=3)
                    contas_conectadas += 1
                    print_success(f"✅ Conta {telefone} conectada ao pool")
            except Exception as e:
                print_warning(f"⚠️ Não foi possível conectar {telefone}: {e}")
        
        if contas_conectadas > 0:
            print_info(f"🔄 Pool inicializado com {contas_conectadas} conta(s)")
        
        return contas_conectadas
    
    async def _connect_single(self, telefone, api_id, api_hash):
        """Conecta uma única conta."""
        safe_phone = ''.join(c for c in telefone if c.isalnum())
        session_path = f"{dados.CONTAS_DIR}/{safe_phone}"
        
        client = TelegramClient(session_path, int(api_id), api_hash)
        await client.connect()
        
        if not await client.is_user_authorized():
            print_warning(f"Sessão de {telefone} expirou")
            await client.disconnect()
            return None
        
        return client
    
    def get_next_client(self):
        """
        Retorna o próximo cliente na rotação round-robin.
        Retorno: (client, telefone, limiter)
        """
        if not self.clients:
            return None, None, None
        
        client, telefone = self.clients[self.current_index]
        limiter = self.limiters.get(telefone)
        
        self.current_index = (self.current_index + 1) % len(self.clients)
        
        return client, telefone, limiter
    
    def has_multiple_accounts(self):
        """Retorna True se há mais de uma conta no pool."""
        return len(self.clients) > 1
    
    def count(self):
        """Retorna número de contas no pool."""
        return len(self.clients)
    
    async def disconnect_all(self):
        """Desconecta todos os clientes."""
        for client, telefone in self.clients:
            try:
                await client.disconnect()
            except:
                pass
        self.clients = []
        self.limiters = {}
        print_info("Pool de clientes desconectado")


# Instância global
client_pool = ClientPool()
