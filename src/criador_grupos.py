import asyncio
from telethon.tl.functions.channels import CreateChannelRequest, EditAdminRequest, EditBannedRequest, ToggleForumRequest, UpdateUsernameRequest
from telethon.tl.types import ChatBannedRights, ChatAdminRights
from telethon.errors import FloodWaitError
import time
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn

console = Console()

def print_info(msg):
    console.print(f"[bold blue]ℹ️ {msg}[/bold blue]")

def print_success(msg):
    console.print(f"[bold green]✅ {msg}[/bold green]")

def print_warning(msg):
    console.print(f"[bold yellow]⚠️ {msg}[/bold yellow]")

def print_error(msg):
    console.print(f"[bold red]❌ {msg}[/bold red]")

class CriadorGrupos:
    def __init__(self, client):
        self.client = client

    async def criar_grupos_em_massa(self, nome_base, quantidade, tipo='forum'):
        """
        Cria múltiplos grupos (Forums ou Tradicionais) com configurações padronizadas de segurança.
        """
        
        # Configurações de Permissão (Banned Rights)
        # O padrão solicitado é: NENHUMA permissão para membros
        # True = Proibido (Telethon logic)
        banned_rights = ChatBannedRights(
            until_date=None,
            view_messages=False, # Podem ver (se False)
            send_messages=True,  # NÃO podem enviar
            send_media=True,
            send_stickers=True,
            send_gifs=True,
            send_games=True,
            send_inline=True,
            embed_links=True,
            send_polls=True,
            change_info=True,
            invite_users=True,
            pin_messages=True
        )

        print_info(f"Iniciando criação de {quantidade} grupos do tipo '{tipo.upper()}'...")
        print_info(f"Nome base: '{nome_base}'")

        sucessos = 0
        falhas = 0

        with Progress(
            SpinnerColumn(),
            TextColumn("[bold cyan]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TextColumn("•"),
            TextColumn("[green]{task.completed}/{task.total}[/green]"),
            console=console
        ) as progress:
            
            task_id = progress.add_task("Criando grupos...", total=quantidade)

            for i in range(1, quantidade + 1):
                nome_atual = f"{i} - {nome_base}"
                progress.update(task_id, description=f"Criando: {nome_atual}")

                try:
                    # 1. Criar Canal (Megagroup/Supergroup)
                    # No Telethon, CreateChannelRequest com megagroup=True cria um Supergrupo
                    created = await self.client(CreateChannelRequest(
                        title=nome_atual,
                        about="Grupo criado automaticamente.",
                        megagroup=True,
                        broadcast=False
                    ))
                    
                    chat = created.chats[0]
                    
                    # 2. Configurar como Fórum (se solicitado)
                    if tipo == 'forum':
                        await self.client(ToggleForumRequest(
                            channel=chat,
                            enabled=True
                        ))
                    
                    # 3. Restringir Salvar Conteúdo (NoForwards)
                    # Isso geralmente é feito via EditChatDefaultBannedRights ou ToggleNoForwards (se disponível)
                    # Telethon raw API para noforwards:
                    from telethon.tl.functions.messages import ToggleNoForwardsRequest
                    await self.client(ToggleNoForwardsRequest(
                        peer=chat,
                        enabled=True
                    ))

                    # 4. Aplicar Permissões (Restrict All)
                    # Usando EditChatDefaultBannedRights para garantir alteração das permissões padrão
                    from telethon.tl.functions.messages import EditChatDefaultBannedRightsRequest
                    
                    await self.client(EditChatDefaultBannedRightsRequest(
                        peer=chat,
                        banned_rights=banned_rights
                    ))

                    # 5. Histórico Visível
                    # Supergrupos (megagroup=True) já tem histórico visível por padrão se não forem privados legacy.
                    # Mas podemos garantir atualizando default banned rights (view_messages=False significa permitido ver)
                    # O código acima no banned_rights já garante view_messages=False.
                    
                    # Atualizar Username (Opcional, não pedido, mas mantemos privado)
                    
                    sucessos += 1
                    progress.update(task_id, advance=1)
                    
                    # Pequena pausa para evitar FloodWait agressivo na criação
                    await asyncio.sleep(2)

                except FloodWaitError as e:
                    print_warning(f"FloodWait de {e.seconds}s. Aguardando...")
                    await asyncio.sleep(e.seconds)
                    # Tentar novamente este índice?
                    # Por simplicidade, vamos pular e logging o erro, ou poderia retry. 
                    # Vamos fazer um retry simples:
                    try:
                        await asyncio.sleep(1)
                        # Re-tentar a lógica seria complexo sem refatorar em função. 
                        # Vamos assumir que se esperou, o próximo loop funciona. 
                        # Mas esse grupo específico falhou.
                        print_error(f"Falha ao criar '{nome_atual}' após FloodWait.")
                        falhas += 1
                    except:
                        pass
                except Exception as e:
                    print_error(f"Erro ao criar '{nome_atual}': {e}")
                    falhas += 1
                    progress.update(task_id, advance=1)
        
        print_success(f"\nOperação finalizada!")
        print_info(f"✅ Criados: {sucessos}")
        if falhas > 0:
            print_error(f"❌ Falhas: {falhas}")
