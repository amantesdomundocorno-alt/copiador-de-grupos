# estilo.py
# Módulo centralizado para estilização da interface com a biblioteca Rich.

import asyncio
import time
import os
from rich.console import Console
from rich.theme import Theme
from rich.panel import Panel
from rich.text import Text
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn
from rich.prompt import Prompt
import pyfiglet

# --- Configuração Central do Console e Tema ---

# Paleta de cores moderna e profissional
custom_theme = Theme({
    "success": "bold green",
    "error": "bold red",
    "warning": "bold yellow",
    "info": "bold cyan",
    "accent": "bold magenta",
    "dim": "dim",
})

# Objeto Console global para ser usado em todo o programa
console = Console(theme=custom_theme)

# --- Funções de Estilo ---

def print_banner():
    """Imprime um banner estiloso usando pyfiglet e um painel Rich."""
    os.system('cls' if os.name == 'nt' else 'clear')
    figlet_text = pyfiglet.figlet_format("Copiador de Midias", font="smslant")
    
    text = Text(figlet_text, justify="center", style="accent")
    subtitle = Text("Modernizado por Gemini", justify="center", style="dim")
    
    panel_content = Text.assemble(text, "\n", subtitle)
    
    console.print(Panel(
        panel_content,
        title="[bold]✨ Clonador e Catalogador v5.0 ✨[/bold]",
        border_style="accent",
        padding=(1, 4)
    ))

def print_section_header(title: str):
    """Imprime um cabeçalho de seção destacado."""
    console.print(Panel(
        Text(f"🚀 {title.upper()}", justify="center", style="bold"),
        border_style="info",
        padding=(0, 2),
    ))

def print_success(message: str):
    console.print(f"✅ [success]{message}[/success]")

def print_error(message: str):
    console.print(f"❌ [error]ERRO: {message}[/error]")

def print_warning(message: str):
    console.print(f"⚠️ [warning]{message}[/warning]")

def print_info(message: str):
    console.print(f"ℹ️ [info]{message}[/info]")

# --- Funções de Feedback Visual ---

async def countdown_timer(total_seconds: int, reason: str = "FloodWait"):
    """Mostra uma barra de progresso como cronômetro de contagem regressiva."""
    print_warning(f"{reason}: O Telegram solicitou uma pausa. Aguardando...")
    
    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(bar_width=None, style="accent", complete_style="accent"),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TextColumn("•"),
        TextColumn("[yellow]{task.fields[remaining]}s restantes"),
        console=console,
        transient=True
    ) as progress:
        task = progress.add_task(
            f"[dim]Aguardando...", 
            total=total_seconds,
            remaining=total_seconds
        )
        for i in range(total_seconds):
            await asyncio.sleep(1)
            progress.update(task, advance=1, remaining=total_seconds - i - 1)
            
    print_info("Tempo de espera concluído. Retomando a tarefa...")

def get_spinner(text: str = "Processando..."):
    """Retorna um objeto Spinner para ser usado com 'with'."""
    return console.status(f"[bold blue]{text}[/bold blue]", spinner="dots12")