"""
Criador de Índice Melhorado - Versão 2.0
Funcion com mais opções de personalização e estatísticas
"""

import re
import asyncio
from typing import List, Dict, Optional
import inquirer

from src.interface import get_all_forum_topics
from src.estilo import (
    print_success, print_error, print_warning, print_info,
    print_section_header, console
)


class CriadorIndiceMelhorado:
    """Criador de índice com recursos avançados"""
    
    def __init__(self, client, forum):
        self.client = client
        self.forum = forum
        self.topicos = []
        self.topicos_selecionados = []
        self.config = {
            'formato': 'numerado',  # 'numerado', 'bullets', 'emojis'
            'incluir_stats': False,
            'titulo_customizado': None,
            'agrupar_por': None,  # None, 'numero', 'letra'
            'ordem': 'numero'  # 'numero', 'alfabetico', 'data'
        }
    
    async def executar(self, topico_indice_id=None):
        """Executa o processo de criação de índice"""
        print_section_header("🎨 Criador de Índice Melhorado")
        
        # 1. Carregar tópicos
        if not await self._carregar_topicos():
            return False
        
        # 2. Configurar opções
        if not await self._configurar_opcoes():
            return False
        
        # 3. Selecionar tópicos
        if not await self._selecionar_topicos():
            return False
        
        # 4. Buscar estatísticas (se solicitado)
        if self.config['incluir_stats']:
            await self._buscar_estatisticas()
        
        # 4.5. Buscar mensagens personalizadas para links (se configurado)
        await self._buscar_mensagens_para_links()
        
        # 5. Gerar índice
        textos = self._gerar_textos_indice()
        
        # 6. Enviar índice
        await self._enviar_indice(textos, topico_indice_id)
        
        return True
    
    async def _carregar_topicos(self):
        """Carrega todos os tópicos do fórum"""
        print_info("📋 Carregando tópicos do fórum...")
        
        try:
            topicos = await get_all_forum_topics(self.client, self.forum, force_refresh=True)
            
            if not topicos:
                print_warning("Nenhum tópico encontrado")
                return False
            
            # Filtrar tópico General (ID 1) e tópicos de índice
            self.topicos = []
            for t in topicos:
                if t.id == 1:
                    continue
                nome_lower = t.title.lower()
                if 'índice' in nome_lower or 'indice' in nome_lower:
                    continue
                self.topicos.append(t)
            
            print_success(f"✅ {len(self.topicos)} tópicos carregados")
            return True
            
        except Exception as e:
            print_error(f"Erro ao carregar tópicos: {e}")
            return False
    
    async def _configurar_opcoes(self):
        """Configura opções de formatação e conteúdo"""
        print_info("\n⚙️ Configurações do Índice")
        
        # Formato do índice
        formato_resp = inquirer.prompt([
            inquirer.List('formato',
                         message="Formato do índice:",
                         choices=[
                             ('1️⃣ Numerado (1, 2, 3...)', 'numerado'),
                             ('• Bullets (• Item)', 'bullets'),
                             ('📁 Com emojis (📁 Item)', 'emojis'),
                             ('🔢 Número do tópico (Se tiver no nome)', 'numero_topico')
                         ])
        ])
        
        if not formato_resp:
            return False
        
        self.config['formato'] = formato_resp['formato']
        
        # Incluir estatísticas
        stats_resp = inquirer.prompt([
            inquirer.Confirm('stats',
                            message="Incluir estatísticas de mídias por tópico? (📸 fotos + 🎬 vídeos)",
                            default=False)
        ])
        
        if stats_resp:
            self.config['incluir_stats'] = stats_resp['stats']
        
        # Título customizado
        titulo_resp = inquirer.prompt([
            inquirer.Text('titulo',
                         message="Título do índice (Enter para padrão '📋 ÍNDICE DE TÓPICOS'):",
                         default="")
        ])
        
        if titulo_resp and titulo_resp['titulo']:
            self.config['titulo_customizado'] = titulo_resp['titulo']
        
        # Ordem
        ordem_resp = inquirer.prompt([
            inquirer.List('ordem',
                         message="Ordem dos tópicos:",
                         choices=[
                             ('🔢 Numérica (se tiver número no nome)', 'numero'),
                             ('🔤 Alfabética', 'alfabetico'),
                             ('📅 Por data de criação', 'data')
                         ])
        ])
        
        if ordem_resp:
            self.config['ordem'] = ordem_resp['ordem']
        
        # Qual mensagem usar no link
        msg_link_resp = inquirer.prompt([
            inquirer.Text('msg_numero',
                         message="Qual mensagem de cada tópico usar no link? (1=primeira, 2=segunda, etc. 0=tópico inteiro)",
                         default="0",
                         validate=lambda _, x: x.isdigit() and int(x) >= 0)
        ])
        
        if msg_link_resp:
            self.config['msg_link_numero'] = int(msg_link_resp['msg_numero'])
            if self.config['msg_link_numero'] > 0:
                print_info(f"✅ Links apontarão para a mensagem #{self.config['msg_link_numero']} de cada tópico")
            else:
                print_info("✅ Links apontarão para o tópico inteiro")
        else:
            self.config['msg_link_numero'] = 0
        
        return True
    
    async def _selecionar_topicos(self):
        """Permite selecionar quais tópicos incluir no índice"""
        print_info("\n📝 Seleção de Tópicos")
        
        selecao_resp = inquirer.prompt([
            inquirer.List('modo',
                         message="Quais tópicos incluir?",
                         choices=[
                             ('✅ Todos os tópicos', 'todos'),
                             ('🎯 Selecionar manualmente', 'manual'),
                             ('🔍 Filtrar por palavra-chave', 'filtro')
                         ])
        ])
        
        if not selecao_resp:
            return False
        
        modo = selecao_resp['modo']
        
        if modo == 'todos':
            self.topicos_selecionados = self.topicos.copy()
        
        elif modo == 'manual':
            # Permitir seleção manual com checkbox
            choices = [(t.title, t) for t in self.topicos]
            
            manual_resp = inquirer.prompt([
                inquirer.Checkbox('topicos',
                                 message="Selecione os tópicos (Espaço para marcar/desmarcar)",
                                 choices=choices)
            ])
            
            if not manual_resp or not manual_resp['topicos']:
                print_warning("Nenhum tópico selecionado")
                return False
            
            self.topicos_selecionados = manual_resp['topicos']
        
        elif modo == 'filtro':
            # Filtrar por palavra-chave
            filtro_resp = inquirer.prompt([
                inquirer.Text('keyword',
                             message="Palavra-chave para filtrar (deixe vazio para incluir 'sem palavra'):")
            ])
            
            if not filtro_resp:
                return False
            
            keyword = filtro_resp['keyword'].lower()
            
            if keyword:
                self.topicos_selecionados = [
                    t for t in self.topicos 
                    if keyword in t.title.lower()
                ]
            else:
                self.topicos_selecionados = self.topicos.copy()
            
            print_info(f"✅ {len(self.topicos_selecionados)} tópicos encontrados com '{keyword}'")
        
        if not self.topicos_selecionados:
            print_warning("Nenhum tópico selecionado")
            return False
        
        # Ordenar
        self._ordenar_topicos()
        
        print_success(f"✅ {len(self.topicos_selecionados)} tópicos serão incluídos no índice")
        return True
    
    def _ordenar_topicos(self):
        """Ordena os tópicos selecionados"""
        if self.config['ordem'] == 'alfabetico':
            self.topicos_selecionados.sort(key=lambda t: t.title.lower())
        
        elif self.config['ordem'] == 'numero':
            def extrair_numero(titulo):
                match = re.match(r'^(\d+)', titulo.strip())
                if match:
                    return (0, int(match.group(1)), titulo)
                return (1, 0, titulo)
            
            self.topicos_selecionados.sort(key=lambda t: extrair_numero(t.title))
        
        elif self.config['ordem'] == 'data':
            # Ordenar por ID (aproxima ordem de criação)
            self.topicos_selecionados.sort(key=lambda t: t.id)
    
    async def _buscar_estatisticas(self):
        """Busca quantidade de mídias (fotos/vídeos) por tópico"""
        print_info("\n📊 Buscando estatísticas de mídias...")
        
        for i, topico in enumerate(self.topicos_selecionados):
            try:
                # Contar apenas mídias (fotos e vídeos)
                count_fotos = 0
                count_videos = 0
                
                async for msg in self.client.iter_messages(self.forum, reply_to=topico.id, limit=None):
                    if msg.media:
                        # Verificar se é foto
                        if msg.photo:
                            count_fotos += 1
                        # Verificar se é vídeo
                        elif msg.video or (msg.document and msg.document.mime_type and 'video' in msg.document.mime_type):
                            count_videos += 1
                
                total_midias = count_fotos + count_videos
                topico.media_count = total_midias
                topico.foto_count = count_fotos
                topico.video_count = count_videos
                
                # Exibir progresso com emoji apropriado
                if count_fotos > count_videos:
                    emoji = "📸"
                elif count_videos > 0:
                    emoji = "🎬"
                else:
                    emoji = "📁"
                
                print(f"   [{i+1}/{len(self.topicos_selecionados)}] {topico.title}: {total_midias} mídias {emoji}", end='\r')
            
            except Exception as e:
                topico.media_count = 0
                topico.foto_count = 0
                topico.video_count = 0
                print_warning(f"\n   Erro ao contar {topico.title}: {e}")
        
        print()
        print_success("✅ Estatísticas de mídias carregadas")
    
    async def _buscar_mensagens_para_links(self):
        """Busca a N-ésima mensagem de cada tópico para usar nos links"""
        msg_numero = self.config.get('msg_link_numero', 0)
        
        if msg_numero == 0:
            # Usar ID do tópico (padrão)
            return
        
        print_info(f"\n🔗 Buscando mensagem #{msg_numero} de cada tópico para os links...")
        
        for i, topico in enumerate(self.topicos_selecionados, 1):
            try:
                # Buscar as primeiras N mensagens do tópico
                mensagens = []
                async for msg in self.client.iter_messages(self.forum, reply_to=topico.id, limit=msg_numero):
                    if msg:
                        mensagens.append(msg)
                
                if mensagens:
                    # Reverter para ordem cronológica (mais antiga primeiro)
                    mensagens.reverse()
                    
                    # Pegar a N-ésima ou a última disponível
                    if len(mensagens) >= msg_numero:
                        topico.link_msg_id = mensagens[msg_numero - 1].id
                    else:
                        # Tópico tem menos mensagens, usar a última
                        topico.link_msg_id = mensagens[-1].id
                        print_warning(f"   ⚠️ [{i}/{len(self.topicos_selecionados)}] {topico.title}: só tem {len(mensagens)} msgs, usando última")
                else:
                    # Tópico vazio, usar ID do tópico
                    topico.link_msg_id = topico.id
                    print_warning(f"   ⚠️ [{i}/{len(self.topicos_selecionados)}] {topico.title}: vazio, usando tópico")
                
                print(f"   [{i}/{len(self.topicos_selecionados)}] {topico.title}", end='\r')
                
            except Exception as e:
                # Em caso de erro, usar ID do tópico
                topico.link_msg_id = topico.id
                print_warning(f"\n   ⚠️ Erro ao buscar mensagens de {topico.title}: {e}")
        
        print()
        print_success(f"✅ Links configurados para mensagem #{msg_numero}")
    
    def _gerar_textos_indice(self):
        """Gera os textos do índice (pode dividir em múltiplas mensagens)"""
        # Título
        titulo = self.config['titulo_customizado'] or "📋 **ÍNDICE DE TÓPICOS**"
        
        linhas = [f"{titulo}\n"]
        
        # Adicionar informações
        if self.config['incluir_stats']:
            total_midias = sum(getattr(t, 'media_count', 0) for t in self.topicos_selecionados)
            total_fotos = sum(getattr(t, 'foto_count', 0) for t in self.topicos_selecionados)
            total_videos = sum(getattr(t, 'video_count', 0) for t in self.topicos_selecionados)
            linhas.append(f"📊 **{len(self.topicos_selecionados)} tópicos | {total_midias:,} mídias** (📸 {total_fotos:,} | 🎬 {total_videos:,})\n")
        else:
            linhas.append(f"📊 **{len(self.topicos_selecionados)} tópicos**\n")
        
        # Gerar linhas de tópicos
        for i, topico in enumerate(self.topicos_selecionados, 1):
            # Usar link personalizado se disponível, senão usar ID do tópico
            msg_id = getattr(topico, 'link_msg_id', topico.id)
            
            # Formato correto para abrir DENTRO do tópico (funciona no mobile)
            # https://t.me/c/{chat_id}/{msg_id}?thread={topic_id}
            link = f"https://t.me/c/{self.forum.id}/{msg_id}?thread={topico.id}"
            
            # Formato da linha
            if self.config['formato'] == 'numerado':
                prefixo = f"{i}."
            elif self.config['formato'] == 'bullets':
                prefixo = "•"
            elif self.config['formato'] == 'emojis':
                prefixo = "📁"
            elif self.config['formato'] == 'numero_topico':
                # Tentar extrair número do título
                match = re.match(r'^(\d+)', topico.title.strip())
                if match:
                    prefixo = f"{match.group(1)}."
                else:
                    prefixo = f"{i}."
            else:
                prefixo = f"{i}."
            
            # Montar linha
            nome = topico.title.upper()
            
            if self.config['incluir_stats']:
                fotos = getattr(topico, 'foto_count', 0)
                videos = getattr(topico, 'video_count', 0)
                
                # Formato: (📸 X | 🎬 Y)
                linha = f"{prefixo} [{nome}]({link}) `(📸 {fotos} | 🎬 {videos})`"
            else:
                linha = f"{prefixo} [{nome}]({link})"
            
            linhas.append(linha)
        
        # Dividir em mensagens se necessário
        MAX_CHARS = 3800  # Margem de segurança maior
        mensagens = []
        parte = 1
        
        # Começar com cabeçalho
        if parte == 1:
            texto_atual = linhas[0] + "\n"  # Título
            if len(linhas) > 1:
                texto_atual += linhas[1] + "\n"  # Estatísticas
            inicio_linhas = 2
        else:
            texto_atual = f"{titulo} (Parte {parte})\n\n"
            inicio_linhas = 0
        
        # Processar linhas de tópicos
        for i in range(inicio_linhas, len(linhas)):
            linha = linhas[i]
            linha_com_quebra = linha + "\n"
            
            # Verificar se adicionar esta linha ultrapassa o limite
            if len(texto_atual) + len(linha_com_quebra) > MAX_CHARS and i > inicio_linhas:
                # Salvar mensagem atual
                mensagens.append(texto_atual.rstrip())
                
                # Começar nova mensagem
                parte += 1
                texto_atual = f"{titulo} (Parte {parte})\n\n"
            
            # Adicionar linha à mensagem atual
            texto_atual += linha_com_quebra
        
        # Adicionar última mensagem
        if texto_atual.strip():
            mensagens.append(texto_atual.rstrip())
        
        return mensagens
    
    async def _enviar_indice(self, textos, topico_indice_id):
        """Envia as mensagens de índice"""
        from telethon.errors import FloodWaitError
        
        print_section_header("📤 Enviando Índice")
        
        print_info(f"📝 Enviando {len(textos)} mensagem(ns)...")
        
        for i, texto in enumerate(textos, 1):
            enviado = False
            tentativa = 0
            
            while not enviado and tentativa < 3:
                try:
                    await self.client.send_message(
                        self.forum,
                        texto,
                        reply_to=topico_indice_id,
                        link_preview=False,
                        parse_mode='md'
                    )
                    print_success(f"   ✅ Mensagem {i}/{len(textos)} enviada")
                    enviado = True
                    
                    # Pausa entre mensagens (evita FloodWait)
                    if i < len(textos):
                        await asyncio.sleep(3.0)  # Aumentado de 1.5s para 3s
                
                except FloodWaitError as e:
                    tentativa += 1
                    print_warning(f"   ⏳ FloodWait: aguardando {e.seconds}s...")
                    await asyncio.sleep(e.seconds + 2)  # +2 segundos de margem
                    print_info(f"   🔄 Tentando reenviar mensagem {i}...")
                
                except Exception as e:
                    print_error(f"   ❌ Erro na mensagem {i}: {e}")
                    tentativa += 1
                    if tentativa < 3:
                        print_info(f"   🔄 Tentando novamente em 3s...")
                        await asyncio.sleep(3)
            
            if not enviado:
                print_error(f"   ❌ Falha ao enviar mensagem {i} após 3 tentativas")
                return False
        
        print_success(f"\n✅ Índice criado com sucesso!")
        print_info(f"   📋 {len(self.topicos_selecionados)} tópicos indexados")
        
        return True


async def criar_indice_melhorado(client, forum, topico_indice_id=None):
    """
    Interface principal para criar índice melhorado
    """
    criador = CriadorIndiceMelhorado(client, forum)
    return await criador.executar(topico_indice_id)
