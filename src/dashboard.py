# dashboard.py
# [S5] Dashboard de Progresso em Tempo Real usando Rich

import time
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from rich.live import Live
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeRemainingColumn, TaskProgressColumn
from rich.table import Table
from rich.layout import Layout
from rich.console import Console, Group
from rich.text import Text

console = Console()


class ProgressDashboard:
    """
    Dashboard visual em tempo real para operações longas.
    Mostra progresso, estatísticas e status de conexão.
    """
    
    def __init__(self, title: str = "Operação em Andamento"):
        self.title = title
        self.start_time = time.time()
        
        # Contadores
        self.total_items = 0
        self.processed_items = 0
        self.success_count = 0
        self.error_count = 0
        
        # Status
        self.current_operation = "Iniciando..."
        self.connection_status = "🟢 Conectado"
        self.last_actions = []  # Últimas 5 ações
        
        # ETA
        self._items_per_second = 0.0
        self._last_update_time = time.time()
        self._last_processed = 0
        
        # Rich Progress
        self.progress = Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}"),
            BarColumn(bar_width=40),
            TaskProgressColumn(),
            TextColumn("•"),
            TimeRemainingColumn(),
        )
        self.task_id = None
        
        # Live display
        self._live = None
    
    def start(self, total: int = 0, description: str = "Progresso"):
        """Inicia o dashboard."""
        self.total_items = total
        self.start_time = time.time()
        self.task_id = self.progress.add_task(description, total=total)
        self._live = Live(self._make_layout(), refresh_per_second=2, console=console)
        self._live.start()
    
    def stop(self):
        """Para o dashboard."""
        if self._live:
            self._live.stop()
    
    def update(
        self, 
        advance: int = 1, 
        success: bool = True, 
        operation: str = None,
        action_log: str = None
    ):
        """
        Atualiza o progresso.
        
        Args:
            advance: Quantidade a avançar
            success: Se a operação foi bem-sucedida
            operation: Descrição da operação atual
            action_log: Mensagem para o log de ações
        """
        self.processed_items += advance
        
        if success:
            self.success_count += advance
        else:
            self.error_count += advance
        
        if operation:
            self.current_operation = operation
        
        if action_log:
            self.last_actions.append(f"[{datetime.now().strftime('%H:%M:%S')}] {action_log}")
            self.last_actions = self.last_actions[-5:]  # Mantém últimas 5
        
        # Atualiza velocidade (a cada 2 segundos)
        now = time.time()
        if now - self._last_update_time >= 2:
            elapsed = now - self._last_update_time
            items_diff = self.processed_items - self._last_processed
            self._items_per_second = items_diff / elapsed if elapsed > 0 else 0
            self._last_update_time = now
            self._last_processed = self.processed_items
        
        # Atualiza Rich progress
        if self.task_id is not None:
            self.progress.update(self.task_id, advance=advance)
        
        # Atualiza layout
        if self._live:
            self._live.update(self._make_layout())
    
    def set_connection_status(self, connected: bool, message: str = None):
        """Atualiza status de conexão."""
        if connected:
            self.connection_status = f"🟢 {message or 'Conectado'}"
        else:
            self.connection_status = f"🔴 {message or 'Desconectado'}"
        
        if self._live:
            self._live.update(self._make_layout())
    
    def _make_layout(self) -> Panel:
        """Cria o layout do dashboard."""
        # Cabeçalho
        elapsed = time.time() - self.start_time
        elapsed_str = str(timedelta(seconds=int(elapsed)))
        
        # Estatísticas
        stats_table = Table(show_header=False, box=None, padding=(0, 2))
        stats_table.add_column("Métrica", style="cyan")
        stats_table.add_column("Valor", style="green")
        
        stats_table.add_row("⏱️ Tempo decorrido", elapsed_str)
        stats_table.add_row("📊 Processados", f"{self.processed_items:,} / {self.total_items:,}")
        stats_table.add_row("✅ Sucesso", str(self.success_count))
        stats_table.add_row("❌ Erros", str(self.error_count))
        stats_table.add_row("⚡ Velocidade", f"{self._items_per_second:.1f}/s")
        stats_table.add_row("🌐 Conexão", self.connection_status)
        
        # Log de ações
        actions_text = Text()
        for action in self.last_actions:
            actions_text.append(action + "\n", style="dim")
        if not self.last_actions:
            actions_text.append("Nenhuma ação recente", style="dim italic")
        
        # Combina tudo
        content = Group(
            self.progress,
            Text(),
            stats_table,
            Text("\n📝 Últimas ações:", style="bold"),
            actions_text,
        )
        
        return Panel(
            content,
            title=f"[bold]{self.title}[/bold]",
            subtitle=f"[dim]{self.current_operation}[/dim]",
            border_style="blue"
        )
    
    def get_summary(self) -> Dict[str, Any]:
        """Retorna resumo das estatísticas."""
        elapsed = time.time() - self.start_time
        return {
            'total': self.total_items,
            'processed': self.processed_items,
            'success': self.success_count,
            'errors': self.error_count,
            'elapsed_seconds': elapsed,
            'items_per_second': self.processed_items / elapsed if elapsed > 0 else 0,
        }


def create_summary_panel(
    title: str,
    processed: int,
    total: int,
    elapsed_seconds: float,
    errors: int = 0
) -> Panel:
    """
    Cria um painel de resumo final após conclusão de operação.
    """
    elapsed = timedelta(seconds=int(elapsed_seconds))
    speed = processed / elapsed_seconds if elapsed_seconds > 0 else 0
    success_rate = ((processed - errors) / processed * 100) if processed > 0 else 100
    
    table = Table(show_header=False, box=None)
    table.add_column("", style="cyan")
    table.add_column("", style="bold green")
    
    table.add_row("📊 Total processado", f"{processed:,} / {total:,}")
    table.add_row("⏱️ Tempo total", str(elapsed))
    table.add_row("⚡ Velocidade média", f"{speed:.2f}/segundo")
    table.add_row("✅ Taxa de sucesso", f"{success_rate:.1f}%")
    if errors > 0:
        table.add_row("❌ Erros", f"{errors}")
    
    return Panel(
        table,
        title=f"[bold green]✅ {title} Concluído[/bold green]",
        border_style="green"
    )


# Exemplo de uso simples:
# 
# dashboard = ProgressDashboard("Copiando Mídias")
# dashboard.start(total=100, description="Mídias")
# 
# for i in range(100):
#     await copiar_midia()
#     dashboard.update(advance=1, action_log=f"Mídia {i+1} copiada")
# 
# dashboard.stop()
# console.print(create_summary_panel("Cópia", 100, 100, 300))
