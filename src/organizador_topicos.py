"""
Organizador de Tópicos - Transforma grupo tradicional em grupo fórum organizado

Funcionalidades:
- Cria fórum novo com configurações específicas
- Organiza mídias em tópicos (X mídias por tópico)
- Cria índice final com hyperlinks
- Envia em álbuns de 10 mídias
- Proteção FloodWait
"""

import asyncio
from datetime import datetime
from telethon import functions
from telethon.tl.types import InputChannel, ChatBannedRights
from telethon.errors import FloodWaitError, ChatAdminRequiredError

from src.database import db
from src.auditoria import AuditoriaGrupo
from src.utils import print_info, print_success, print_error, print_warning, print_section_header


class OrganizadorTopicos:
    """Organiza mídias de um grupo tradicional em tópicos de um fórum."""
    
    def __init__(self, client, config, account_phone=None):
        self.client = client
        self.config = config
        self.account_phone = account_phone
        
        # Configurações
        self.midias_por_topico = config.get('midias_por_topico', 1000)
        self.numero_inicio_indice = config.get('numero_inicio_indice', 1)
        self.pausar_segundos = config.get('pausar_segundos', 5)
        self.pausar_a_cada = config.get('pausar_a_cada', 100)
        self.tipos_arquivo = config.get('tipos_arquivo', ['photo', 'video', 'document', 'audio', 'gif'])
        
        # Estado
        self.origem = None
        self.destino = None
        self.topicos_criados = []  # Lista de {'id': int, 'nome': str, 'link': str}
        self.total_copiado = 0
        self.midias_para_copiar = []
        
    async def executar(self):
        """Executa o processo completo de organização."""
        try:
            # 1. Resolver entidades
            if not await self._resolver_entidades():
                return False
            
            # 2. Buscar mídias da origem
            if not await self._buscar_midias_origem():
                return False
            
            # 3. Verificar se destino é fórum
            if not await self._verificar_destino_forum():
                return False
            
            # 4. Executar cópia organizada
            if not await self._executar_copia_organizada():
                return False
            
            # 5. Criar índice
            await self._criar_indice()
            
            print_success(f"\n✅ Organização concluída!")
            print_info(f"   📁 {len(self.topicos_criados)} tópicos criados")
            print_info(f"   📊 {self.total_copiado:,} mídias organizadas")
            
            return True
            
        except Exception as e:
            print_error(f"Erro na organização: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    async def _resolver_entidades(self):
        """Resolve as entidades de origem e destino."""
        try:
            self.origem = await self.client.get_entity(self.config['id_origem'])
            self.destino = await self.client.get_entity(self.config['id_destino'])
            return True
        except Exception as e:
            print_error(f"Erro ao resolver entidades: {e}")
            return False
    
    async def _buscar_midias_origem(self):
        """Busca mídias do grupo de origem usando auditoria."""
        print_section_header("Fase 1: Buscando Mídias da Origem")
        
        # Verificar se já tem auditoria
        metadata = db.get_audit_metadata(self.config['id_origem'])
        
        if metadata and metadata['total_media_count'] > 0:
            print_success(f"✅ Auditoria existente encontrada: {metadata['total_media_count']:,} mídias")
        else:
            print_info("Fazendo auditoria do grupo de origem...")
            auditor = AuditoriaGrupo(
                self.client, 
                self.origem, 
                self.config['nome_origem'],
                self.account_phone
            )
            await auditor.auditar(modo='full')
        
        # Buscar mídias do banco
        todas_midias = db.get_all_media(self.config['id_origem'])
        
        # Filtrar por tipo
        self.midias_para_copiar = [
            m for m in todas_midias 
            if m.get('media_type') in self.tipos_arquivo
        ]
        
        # Ordenar por message_id (ordem cronológica)
        self.midias_para_copiar.sort(key=lambda x: x.get('message_id', 0))
        
        print_info(f"📊 {len(self.midias_para_copiar):,} mídias para organizar")
        return len(self.midias_para_copiar) > 0
    
    async def _verificar_destino_forum(self):
        """Verifica se o destino é um grupo fórum."""
        try:
            if hasattr(self.destino, 'forum') and self.destino.forum:
                print_success(f"✅ Destino é um grupo fórum: {self.destino.title}")
                return True
            else:
                print_error("❌ O grupo de destino não é um fórum!")
                print_info("   Selecione um grupo com modo Fórum ativado.")
                return False
        except Exception as e:
            print_error(f"Erro ao verificar destino: {e}")
            return False
    
    async def _executar_copia_organizada(self):
        """Executa a cópia organizando em tópicos."""
        print_section_header("Fase 2: Organizando em Tópicos")
        
        total_midias = len(self.midias_para_copiar)
        num_topicos = (total_midias + self.midias_por_topico - 1) // self.midias_por_topico
        
        print_info(f"📁 Serão criados {num_topicos} tópicos com ~{self.midias_por_topico} mídias cada")
        
        numero_topico = self.numero_inicio_indice
        
        for i in range(0, total_midias, self.midias_por_topico):
            # Calcular range deste tópico
            inicio = i + 1
            fim = min(i + self.midias_por_topico, total_midias)
            
            # Nome do tópico (maiúsculas)
            nome_topico = f"{numero_topico} - DO {inicio} AO {fim}"
            
            # Criar tópico
            print_info(f"\n📁 Criando tópico: {nome_topico}")
            topico_id, primeiro_msg_id = await self._criar_topico(nome_topico)
            
            if not topico_id:
                print_error(f"Falha ao criar tópico {nome_topico}")
                continue
            
            # Gerar link do tópico
            link = f"https://t.me/c/{self.destino.id}/{primeiro_msg_id}"
            
            self.topicos_criados.append({
                'id': topico_id,
                'nome': nome_topico,
                'link': link,
                'numero': numero_topico
            })
            
            # Pegar mídias deste tópico
            midias_topico = self.midias_para_copiar[i:i + self.midias_por_topico]
            
            # Copiar mídias em lotes de 10
            await self._copiar_midias_para_topico(topico_id, midias_topico)
            
            numero_topico += 1
        
        return True
    
    async def _criar_topico(self, nome):
        """Cria um novo tópico no fórum."""
        try:
            updates = await self.client(functions.channels.CreateForumTopicRequest(
                channel=self.destino,
                title=nome,
                random_id=int(datetime.now().timestamp() * 1000)
            ))
            
            # Extrair ID do tópico e da primeira mensagem
            topico_id = None
            primeiro_msg_id = None
            
            for update in updates.updates:
                if hasattr(update, 'message') and hasattr(update.message, 'reply_to'):
                    if hasattr(update.message.reply_to, 'reply_to_top_id'):
                        topico_id = update.message.reply_to.reply_to_top_id
                    primeiro_msg_id = update.message.id
                    break
            
            if not topico_id:
                # Tentar pegar de outra forma
                for update in updates.updates:
                    if hasattr(update, 'id'):
                        topico_id = update.id
                        primeiro_msg_id = update.id
                        break
            
            print_success(f"   ✅ Tópico criado (ID: {topico_id})")
            return topico_id, primeiro_msg_id
            
        except FloodWaitError as e:
            print_warning(f"⏳ FloodWait: Aguardando {e.seconds}s...")
            await asyncio.sleep(e.seconds)
            return await self._criar_topico(nome)
        except Exception as e:
            print_error(f"Erro ao criar tópico: {e}")
            return None, None
    
    async def _copiar_midias_para_topico(self, topico_id, midias):
        """Copia mídias para um tópico específico em lotes de 10."""
        from telethon.tl.types import InputPeerChannel
        import random
        
        total = len(midias)
        copiados = 0
        
        # Processar em lotes de 10
        for i in range(0, total, 10):
            lote = midias[i:i + 10]
            
            try:
                # Buscar mensagens originais
                msg_ids = [m['message_id'] for m in lote]
                mensagens = await self.client.get_messages(self.origem, ids=msg_ids)
                
                # Filtrar mensagens válidas
                mensagens_validas = [m for m in mensagens if m and m.media]
                
                if mensagens_validas:
                    # Usar ForwardMessagesRequest com top_msg_id para enviar ao tópico
                    await self.client(functions.messages.ForwardMessagesRequest(
                        from_peer=self.origem,
                        id=[m.id for m in mensagens_validas],
                        to_peer=self.destino,
                        top_msg_id=topico_id,  # ID do tópico
                        random_id=[random.randint(0, 2**63) for _ in mensagens_validas],
                        drop_author=False,
                        drop_media_captions=False
                    ))
                    
                    copiados += len(mensagens_validas)
                    self.total_copiado += len(mensagens_validas)
                    
                    print(f"   📤 Copiadas {copiados}/{total} mídias...", end='\r')
                
                # Pausa periódica
                if copiados > 0 and copiados % self.pausar_a_cada == 0:
                    print_info(f"\n   ⏸️ Pausando {self.pausar_segundos}s...")
                    await asyncio.sleep(self.pausar_segundos)
                    
            except FloodWaitError as e:
                print_warning(f"\n   ⏳ FloodWait: Aguardando {e.seconds}s...")
                await asyncio.sleep(e.seconds)
            except Exception as e:
                print_error(f"\n   ❌ Erro ao copiar lote: {e}")
                continue
        
        print(f"   ✅ Copiadas {copiados}/{total} mídias     ")
    
    async def _criar_indice(self):
        """Cria o tópico de índice com hyperlinks."""
        print_section_header("Fase 3: Criando Índice")
        
        # Perguntar onde criar o índice
        topico_indice_id = self.config.get('topico_indice_id')
        
        if not topico_indice_id:
            # Criar tópico de índice
            print_info("📋 Criando tópico de índice...")
            topico_indice_id, _ = await self._criar_topico("📋 ÍNDICE")
        
        if not topico_indice_id:
            print_error("Falha ao criar tópico de índice")
            return
        
        # Montar texto do índice
        linhas = ["📋 **ÍNDICE DE MÍDIAS**\n"]
        
        for topico in self.topicos_criados:
            # Formato: 1 - [Do 1 ao 1000](link)
            linha = f"{topico['numero']} - [{topico['nome'].split(' - ')[1]}]({topico['link']})"
            linhas.append(linha)
        
        texto_indice = "\n".join(linhas)
        
        # Enviar mensagem de índice
        try:
            await self.client.send_message(
                self.destino,
                texto_indice,
                reply_to=topico_indice_id,
                link_preview=False
            )
            print_success("✅ Índice criado com sucesso!")
        except Exception as e:
            print_error(f"Erro ao criar índice: {e}")


async def criar_forum_novo(client, nome, usuario_admin_id=None):
    """
    Cria um novo grupo fórum com as configurações especificadas.
    
    Configurações:
    - Privado
    - Histórico visível para novos membros
    - Restringir salvar conteúdo
    - Modo fórum ativado
    """
    try:
        print_info(f"📁 Criando grupo fórum: {nome}")
        
        # 1. Criar supergrupo
        result = await client(functions.channels.CreateChannelRequest(
            title=nome,
            about="Grupo organizado automaticamente",
            megagroup=True,
            forum=True  # Já cria como fórum
        ))
        
        canal = result.chats[0]
        canal_id = canal.id
        
        print_success(f"   ✅ Grupo criado (ID: {canal_id})")
        
        # 2. Configurar privacidade e restrições
        try:
            # Tornar privado (remover username público se houver)
            # Nota: Por padrão já é privado se não definir username
            
            # Restringir salvar conteúdo
            await client(functions.messages.ToggleNoForwardsRequest(
                peer=canal,
                enabled=True
            ))
            print_success("   ✅ Restrição de salvar conteúdo ativada")
            
        except Exception as e:
            print_warning(f"   ⚠️ Algumas configurações podem precisar ser feitas manualmente: {e}")
        
        return canal
        
    except FloodWaitError as e:
        print_warning(f"⏳ FloodWait: Aguardando {e.seconds}s...")
        await asyncio.sleep(e.seconds)
        return await criar_forum_novo(client, nome, usuario_admin_id)
    except Exception as e:
        print_error(f"Erro ao criar fórum: {e}")
        return None


async def criar_indice_topicos(client, forum, topico_indice_id=None):
    """
    Cria ou atualiza o índice de tópicos de um fórum.
    
    - Lê todos os tópicos existentes
    - Ordena (numérico se tiver números, senão alfabético)
    - Cria mensagem(ns) de índice com hyperlinks
    - Se passar de 4096 chars, divide em várias mensagens
    """
    import re
    from src.interface import get_all_forum_topics
    
    print_section_header("Criar/Atualizar Índice de Tópicos")
    
    try:
        # 1. Buscar todos os tópicos
        print_info("📋 Buscando todos os tópicos do fórum...")
        topicos = await get_all_forum_topics(client, forum, force_refresh=True)
        
        if not topicos:
            print_warning("Nenhum tópico encontrado no fórum.")
            return False
        
        print_success(f"✅ Encontrados {len(topicos)} tópicos")
        
        # 2. Filtrar tópico de índice da lista (não queremos ele no índice)
        topicos_filtrados = []
        for t in topicos:
            nome = t.title.lower()
            # Ignorar tópicos de índice
            if 'índice' in nome or 'indice' in nome or t.id == topico_indice_id:
                continue
            # Ignorar tópico General (ID 1)
            if t.id == 1:
                continue
            topicos_filtrados.append(t)
        
        if not topicos_filtrados:
            print_warning("Nenhum tópico para indexar (apenas índice encontrado).")
            return False
        
        # 3. Ordenar tópicos
        def extrair_numero(titulo):
            """Extrai número do início do título para ordenação."""
            match = re.match(r'^(\d+)', titulo.strip())
            if match:
                return (0, int(match.group(1)), titulo)  # 0 = tem número (vem primeiro)
            return (1, 0, titulo)  # 1 = não tem número (ordenar alfabeticamente)
        
        topicos_ordenados = sorted(topicos_filtrados, key=lambda t: extrair_numero(t.title))
        
        print_info(f"📊 {len(topicos_ordenados)} tópicos para indexar")
        
        # 4. Montar texto do índice
        linhas = ["📋 **ÍNDICE DE TÓPICOS**\n"]
        
        for t in topicos_ordenados:
            # Link do tópico: https://t.me/c/CHANNEL_ID/TOPIC_ID
            link = f"https://t.me/c/{forum.id}/{t.id}"
            linha = f"• [{t.title.upper()}]({link})"
            linhas.append(linha)
        
        texto_completo = "\n".join(linhas)
        
        # 5. Dividir em mensagens se necessário (limite 4096 chars)
        MAX_CHARS = 4000  # Margem de segurança
        mensagens = []
        
        if len(texto_completo) <= MAX_CHARS:
            mensagens.append(texto_completo)
        else:
            # Dividir por linhas
            texto_atual = "📋 **ÍNDICE DE TÓPICOS** (Parte 1)\n"
            parte = 1
            
            for linha in linhas[1:]:  # Pular o título
                if len(texto_atual) + len(linha) + 1 > MAX_CHARS:
                    mensagens.append(texto_atual)
                    parte += 1
                    texto_atual = f"📋 **ÍNDICE DE TÓPICOS** (Parte {parte})\n"
                texto_atual += linha + "\n"
            
            if texto_atual.strip():
                mensagens.append(texto_atual)
        
        print_info(f"📝 Índice terá {len(mensagens)} mensagem(ns)")
        
        # 6. Enviar mensagens de índice
        for i, texto in enumerate(mensagens):
            try:
                await client.send_message(
                    forum,
                    texto,
                    reply_to=topico_indice_id,
                    link_preview=False
                )
                print_success(f"   ✅ Mensagem {i+1}/{len(mensagens)} enviada")
            except Exception as e:
                print_error(f"   ❌ Erro ao enviar mensagem {i+1}: {e}")
        
        print_success(f"\n✅ Índice criado/atualizado com {len(topicos_ordenados)} tópicos!")
        return True
        
    except Exception as e:
        print_error(f"Erro ao criar índice: {e}")
        import traceback
        traceback.print_exc()
        return False


async def deletar_topicos(client, forum, topicos_ids):
    """
    Deleta tópicos de um fórum.
    
    Args:
        client: Cliente Telethon
        forum: Entidade do fórum
        topicos_ids: Lista de IDs dos tópicos a deletar
    """
    deletados = 0
    erros = 0
    
    for topico_id in topicos_ids:
        try:
            await client(functions.channels.DeleteTopicHistoryRequest(
                channel=forum,
                top_msg_id=topico_id
            ))
            deletados += 1
            print_success(f"   ✅ Tópico {topico_id} deletado")
            await asyncio.sleep(0.5)  # Pequena pausa para evitar flood
            
        except FloodWaitError as e:
            print_warning(f"   ⏳ FloodWait: Aguardando {e.seconds}s...")
            await asyncio.sleep(e.seconds)
            # Tentar novamente
            try:
                await client(functions.channels.DeleteTopicHistoryRequest(
                    channel=forum,
                    top_msg_id=topico_id
                ))
                deletados += 1
                print_success(f"   ✅ Tópico {topico_id} deletado")
            except Exception as e2:
                print_error(f"   ❌ Erro ao deletar tópico {topico_id}: {e2}")
                erros += 1
                
        except Exception as e:
            print_error(f"   ❌ Erro ao deletar tópico {topico_id}: {e}")
            erros += 1
    
    print_info(f"\n📊 Resultado: {deletados} deletados, {erros} erros")
    return deletados, erros


async def testar_copia_saved_messages(client, origem, destino, quantidade=5):
    """
    Testa cópia de mídias usando Saved Messages como intermediário.
    
    Fluxo:
    1. Salva mídia nos "Mensagens Salvas" (permitido mesmo com proteção)
    2. Encaminha dos Saved Messages para o destino
    3. Deleta dos Saved Messages
    """
    print_section_header("Teste: Cópia via Saved Messages")
    
    print_info(f"📤 Origem: {origem.title}")
    print_info(f"📥 Destino: {destino.title}")
    print_info(f"📊 Quantidade: {quantidade}")
    
    # Buscar mensagens com mídia
    print_info("\n🔍 Buscando mídias na origem...")
    mensagens_com_midia = []
    
    async for msg in client.iter_messages(origem, limit=100):
        if msg.media:
            mensagens_com_midia.append(msg)
            if len(mensagens_com_midia) >= quantidade:
                break
    
    print_success(f"✅ Encontradas {len(mensagens_com_midia)} mídias para testar")
    
    # Pegar "me" (Saved Messages)
    me = await client.get_me()
    
    copiadas = 0
    erros = 0
    
    for i, msg in enumerate(mensagens_com_midia):
        try:
            print(f"\n[{i+1}/{len(mensagens_com_midia)}] Mídia (msg_id: {msg.id})...")
            
            # Passo 1: Salvar nos Saved Messages
            print("   1️⃣ Salvando em Mensagens Salvas...", end='')
            saved_msg = await client.forward_messages(me, msg)
            print(" ✅")
            
            # Passo 2: Encaminhar para destino
            print("   2️⃣ Encaminhando para destino...", end='')
            await client.forward_messages(destino, saved_msg)
            print(" ✅")
            
            # Passo 3: Deletar dos Saved Messages
            print("   3️⃣ Limpando Saved Messages...", end='')
            await client.delete_messages(me, saved_msg)
            print(" ✅")
            
            copiadas += 1
            await asyncio.sleep(0.3)
            
        except FloodWaitError as e:
            print(f" ⏳ FloodWait {e.seconds}s...")
            await asyncio.sleep(e.seconds)
        except Exception as e:
            print(f" ❌ {e}")
            erros += 1
    
    print("\n" + "="*60)
    print_info(f"📊 RESULTADO: {copiadas} copiadas, {erros} erros")
    
    if erros > 0 and copiadas == 0:
        print_warning("\n⚠️ Todos falharam. Grupo bloqueia até Saved Messages.")
        print_info("   Única opção: download + re-upload.")
    elif erros > 0:
        print_warning(f"\n⚠️ Alguns erros. Funciona parcialmente.")
    else:
        print_success("\n✅ Método funciona perfeitamente!")
    
    return copiadas, erros



