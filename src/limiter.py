import asyncio
import time
from .estilo import print_warning, print_info, countdown_timer

class RateLimiter:
    """
    Gerenciador de Taxa para evitar FloodWait.
    Implementa um sistema de 'Token Bucket' adaptativo.
    
    IMPORTANTE: O Telegram tem limite de ~20 mensagens/minuto para grupos.
    Cada mídia em um álbum conta como mensagem separada.
    """
    def __init__(self, actions_per_minute=18, burst_limit=3):
        self.rate = actions_per_minute / 60.0  # Ações por segundo (~0.3/s)
        self.burst = burst_limit
        self.tokens = burst_limit
        self.last_update = time.time()
        self.consecutive_errors = 0
        self.total_sent = 0  # Contador para log
    
    async def wait(self, cost=1):
        """
        Espera até ter tokens suficientes para realizar uma ação.
        O 'cost' deve ser o número de mídias individuais sendo enviadas.
        """
        # Pausa mínima obrigatória proporcional ao custo
        # 0.3s por mídia garante máximo de ~200/min (com margem de segurança)
        min_pause = cost * 0.3
        if min_pause > 0:
            await asyncio.sleep(min_pause)
        
        while True:
            now = time.time()
            # Regenera tokens
            elapsed = now - self.last_update
            self.tokens = min(self.burst, self.tokens + elapsed * self.rate)
            self.last_update = now
            
            if self.tokens >= 1:  # Sempre gasta 1 token por operação
                self.tokens -= 1
                self.total_sent += cost
                return
            
            # Se não tem tokens, espera o tempo necessário
            wait_time = (1 - self.tokens) / self.rate
            if wait_time > 0.1:
                # Se a espera for longa, avisa (mas sem spam)
                if wait_time > 5:
                    print_info(f"⏳ Rate Limiter: Pausando por {wait_time:.1f}s para evitar FloodWait...")
                await asyncio.sleep(wait_time)

    async def report_flood_wait(self, seconds):
        """
        Informa ao limiter que ocorreu um FloodWait.
        Ele ajusta a taxa para ser mais conservador.
        """
        print_warning(f"⚠️ FloodWait detectado ({seconds}s). Reduzindo velocidade...")
        await countdown_timer(seconds + 2, reason="FloodWait Cooldown")
        
        # Reduz a taxa em 30% (mais agressivo)
        self.rate *= 0.7
        self.consecutive_errors += 1
        
        if self.consecutive_errors > 3:
            print_warning("Múltiplos FloodWaits consecutivos. Forçando pausa longa de segurança.")
            await asyncio.sleep(120)
            self.consecutive_errors = 0

    def report_success(self):
        """Informa sucesso para gradualmente restaurar a velocidade."""
        self.consecutive_errors = 0
        # Aumenta a taxa muito levemente (0.5% por sucesso, máx 0.35/s = 21/min)
        max_rate = 21 / 60.0
        if self.rate < max_rate:
            self.rate *= 1.005

# Instância global para ser usada em todo o app
# 18 ações/min com burst de 3 = conservador para evitar FloodWait
global_limiter = RateLimiter(actions_per_minute=18, burst_limit=3)
