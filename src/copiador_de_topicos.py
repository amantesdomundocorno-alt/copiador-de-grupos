# copiador_de_topicos.py

import asyncio
import time
import os
import sys
import math
import re
import inquirer
from tqdm.asyncio import tqdm
from telethon import functions
from telethon.tl.types import ForumTopicDeleted
from telethon.errors.rpcerrorlist import MessageTooLongError, FloodWaitError

from . import gerenciador_dados as dados
from .estilo import (
    print_success, print_error, print_warning, print_info,
    print_section_header,
    countdown_timer
)
from .interface import send_message_with_retry, get_all_forum_topics
from .auditoria import AuditoriaGrupo
from .comparador import ComparadorMidias

# Constantes
LOTE_MIDIAS = 10
TELEGRAM_CHAR_LIMIT = 4000
MAX_MENSAGENS_SEM_MIDIA = 1000

class CopiadorDeTopicos:
    def __init__(self, client, config):
        self.client = client
        self.config = config
        
        self.origem = None
        self.destino = None
        
        self.task_key = f"topicos_{config['id_origem']}_{config['id_destino']}"
        self.progress_data = {}
        self.id_msg_indice = None
        self.numero_indice_atual = 0
        
        # Cache de tópicos do destino para verificação inteligente
        self.topicos_destino_cache = {} # { "nome_normalizado": id_topico }
        self.mapa_nomes_reais_destino = {} # { id_topico: "Nome Real" }

    def _normalizar_nome_topico(self, nome):
        """
        Normaliza o nome para comparação inteligente.
        1. Remove números e traços do início (ex: "450 - Arthur" -> "Arthur")
        2. Remove espaços extras.
        3. Converte para minúsculo.
        """
        if not nome: return ""
        # Remove padrão "123 - " ou "123-" ou "123 " do início
        nome_limpo = re.sub(r'^\d+\s*[-]?\s*', '', nome)
        return nome_limpo.strip().lower()

    async def _inicializar_entidades(self):
        """Busca e valida as entidades e mapeia tópicos existentes."""
        try:
            print_info("Buscando entidades de origem e destino...")
            self.origem = await self.client.get_entity(self.config['id_origem'])
            self.destino = await self.client.get_entity(self.config['id_destino'])
            
            # Mapeamento Inteligente dos tópicos existentes no destino
            print_info("Mapeando tópicos existentes no destino para comparação...")
            topicos_existentes = await get_all_forum_topics(self.client, self.destino)
            
            for t in topicos_existentes:
                if isinstance(t, ForumTopicDeleted) or isinstance(t, dict): continue # Ignora deletados ou dicts simples
                
                nome_norm = self._normalizar_nome_topico(t.title)
                self.topicos_destino_cache[nome_norm] = t.id
                self.mapa_nomes_reais_destino[t.id] = t.title
            
            print_success(f"Mapeados {len(self.topicos_destino_cache)} tópicos existentes no destino.")
            return True
        except Exception as e:
            print_error(f"Erro fatal ao buscar grupos: {e}")
            print_error("Verifique se você ainda está nos dois grupos e tente novamente.")
            return False

    def _carregar_ou_criar_progresso(self):
        """Carrega o progresso salvo ou cria um novo se não existir."""
        self.progress_data = dados.get_task_progress(self.task_key)
        if not self.progress_data:
            print_warning("Nenhum progresso encontrado. Iniciando do zero.")
            self.progress_data = {'topicos_concluidos': [], 'progresso_topicos': {}, 'id_msg_indice': None}
        
        self.id_msg_indice = self.progress_data.get('id_msg_indice')
        self.numero_indice_atual = self.config.get('numero_indice_inicio', 1)

    def _salvar_progresso(self):
        """Salva todo o estado atual do progresso."""
        self.progress_data['id_msg_indice'] = self.id_msg_indice
        dados.save_progress(self.task_key, self.progress_data)
        # print_info("Progresso salvo com segurança.")

    async def _atualizar_indice_geral(self, nome_topico_novo, link_primeira_midia, qtd_midias):
        """Adiciona uma nova entrada ao tópico de índice geral."""
        if not self.config.get('id_topico_indice'):
            return

        try:
            texto_novo_item = f"{self.numero_indice_atual} - [{nome_topico_novo}]({link_primeira_midia}) - {qtd_midias} 🎬"
            self.numero_indice_atual += 1

            if not self.id_msg_indice:
                print_info("Criando nova mensagem de índice geral...")
                cabecalho = f"**ÍNDICE GERAL - {self.config['nome_origem']}**\n\n"
                msg_enviada = await self.client.send_message(
                    self.destino,
                    message=f"{cabecalho}{texto_novo_item}",
                    reply_to=self.config['id_topico_indice'],
                    parse_mode='md'
                )
                self.id_msg_indice = msg_enviada.id
            else:
                msg_antiga = await self.client.get_messages(self.destino, ids=self.id_msg_indice)
                if not msg_antiga:
                    print_warning("Mensagem de índice não encontrada. Criando uma nova.")
                    self.id_msg_indice = None
                    await self._atualizar_indice_geral(nome_topico_novo, link_primeira_midia, qtd_midias)
                    return

                novo_texto = f"{msg_antiga.text}\n{texto_novo_item}"
                if len(novo_texto) > TELEGRAM_CHAR_LIMIT:
                    print_warning("Índice cheio. Criando nova página de índice...")
                    self.id_msg_indice = None
                    await self._atualizar_indice_geral(nome_topico_novo, link_primeira_midia, qtd_midias)
                else:
                    await self.client.edit_message(self.destino, self.id_msg_indice, novo_texto, parse_mode='md')
            
            print_success(f"Índice geral atualizado para o tópico '{nome_topico_novo}'.")
            self._salvar_progresso()

        except Exception as e:
            print_error(f"Falha CRÍTICA ao atualizar índice geral: {e}")
            self.id_msg_indice = None # Desativa o índice para evitar mais erros

    async def _copiar_topico_inteligente(self, id_origem, nome_origem, id_destino, nome_destino):
        """
        Executa a cópia inteligente (auditada) para um par de tópicos.
        """
        print_section_header(f"CÓPIA INTELIGENTE: {nome_origem} -> {nome_destino}")
        
        # Determinar política de cache
        modo_auditoria = self.config.get('modo_auditoria', 'cache')
        force_refresh = False
        
        if modo_auditoria == 'force':
            force_refresh = True
            print_info("Modo 'Forçar Auditoria' ativo: Ignorando cache existente.")
        elif modo_auditoria == 'ask':
            q = [inquirer.List('refresh', 
                              message=f"Deseja re-auditar (atualizar dados) o tópico '{nome_origem}'?",
                              choices=[('Sim, fazer nova auditoria', True), ('Não, usar cache se existir', False)])]
            ans = inquirer.prompt(q)
            force_refresh = ans['refresh'] if ans else False

        # 1. Auditar Origem
        print_info(f"🔍 Auditando tópico de origem: {nome_origem}")
        auditor_origem = AuditoriaGrupo(self.client, self.origem, self.config['nome_origem'], topico_id=id_origem)
        
        # Passamos force_refresh=force_refresh. Se for False, o próprio auditoria.py ainda pode perguntar se não achar cache,
        # mas queremos controlar o comportamento "Sempre usar cache" vs "Sempre atualizar".
        # O auditoria.py por padrão pergunta se achar cache. Precisamos suprimir a pergunta lá se a decisão já foi tomada aqui.
        # Vamos passar force_refresh. Se True, ele refaz. Se False, ele tenta carregar.
        
        if not await auditor_origem.auditar_completo(force_refresh=force_refresh):
            print_error("Falha na auditoria da origem.")
            return

        # 2. Auditar Destino
        print_info(f"🔍 Auditando tópico de destino: {nome_destino}")
        auditor_destino = AuditoriaGrupo(self.client, self.destino, self.config['nome_destino'], topico_id=id_destino)
        
        # Para o destino, geralmente queremos os dados mais frescos possíveis para evitar duplicatas,
        # mas respeitaremos a configuração do usuário.
        if not await auditor_destino.auditar_completo(force_refresh=force_refresh): 
            print_error("Falha na auditoria do destino.")
            return

        # 3. Comparar
        print_info("Comparando mídias...")
        comparador = ComparadorMidias(auditor_origem, auditor_destino)
        ids_pendentes = comparador.comparar()

        if not ids_pendentes:
            print_success("✅ Tópico já está sincronizado! Nenhuma mídia nova para copiar.")
            return

        # 4. Copiar Pendentes
        # Ordenação
        if self.config.get('ordem') == 'decrescente':
            ids_pendentes.reverse()
        else:
             # Comparador geralmente devolve ordenado por ID, mas garantimos crescente se for o caso
             ids_pendentes.sort()

        print_info(f"🚀 Iniciando cópia de {len(ids_pendentes)} mídias pendentes...")
        
        lote_atual = []
        midias_copiadas = 0
        midias_desde_pausa = 0
        link_primeira_midia = None

        pbar = tqdm(total=len(ids_pendentes), desc=f"Sincronizando '{nome_destino}'", unit=" mídia", dynamic_ncols=True, file=sys.stderr)

        for i, msg_id in enumerate(ids_pendentes):
            try:
                msg = await self.client.get_messages(self.origem, ids=msg_id)
                if not msg or not msg.media: continue
                
                lote_atual.append(msg)

                if len(lote_atual) >= LOTE_MIDIAS or i == len(ids_pendentes) - 1:
                    await send_message_with_retry(
                        self.client, self.destino, file=[m.media for m in lote_atual], reply_to=id_destino
                    )
                    
                    if not link_primeira_midia:
                        primeira_msg_album = (await self.client.get_messages(self.destino, reply_to=id_destino, limit=1))[0]
                        link_primeira_midia = f"https://t.me/c/{self.destino.id}/{id_destino}/{primeira_msg_album.id}"

                    qtd = len(lote_atual)
                    midias_copiadas += qtd
                    midias_desde_pausa += qtd
                    pbar.update(qtd)
                    lote_atual = []
                    
                    if self.config['pausa_a_cada'] > 0 and midias_desde_pausa >= self.config['pausa_a_cada']:
                            await countdown_timer(self.config['tempo_pausa_segundos'], "Pausa programada")
                            midias_desde_pausa = 0

            except Exception as e:
                print_error(f"Erro ao processar mensagem {msg_id}: {e}")
        
        pbar.close()
        
        if midias_copiadas > 0:
            if not link_primeira_midia:
                link_primeira_midia = f"https://t.me/c/{self.destino.id}/{id_destino}"
            
            # Atualiza índice (opcional, já que é update, mas bom informar no índice geral que houve update)
            # await self._atualizar_indice_geral(nome_destino, link_primeira_midia, midias_copiadas)
            print_success(f"Sincronização concluída. {midias_copiadas} novas mídias adicionadas.")

    async def _copiar_um_topico(self, id_topico_origem, nome_topico_origem):
        """Copia um único tópico do início ao fim, com auditoria e pausas."""
        print_section_header(f"PROCESSANDO: {nome_topico_origem}")
        
        id_topico_destino = None
        
        # --- Lógica de Correspondência Inteligente ---
        nome_origem_norm = self._normalizar_nome_topico(nome_topico_origem)
        id_existente = self.topicos_destino_cache.get(nome_origem_norm)
        
        acao = 'new'
        modo_colisao = self.config.get('modo_colisao', 'ask')

        if id_existente and modo_colisao != 'new':
            nome_existente = self.mapa_nomes_reais_destino.get(id_existente, "Desconhecido")
            print_info(f"🔍 Correspondência encontrada: '{nome_topico_origem}' (Origem) ≈ '{nome_existente}' (Destino)")
            
            if modo_colisao == 'update':
                acao = 'update'
            elif modo_colisao == 'ask':
                # Pergunta ao usuário
                q = [inquirer.List('acao', 
                                  message=f"Deseja atualizar o tópico existente '{nome_existente}' ou criar um novo?",
                                  choices=[('Atualizar Existente', 'update'), ('Criar Novo', 'new')])]
                resp = inquirer.prompt(q)
                acao = resp['acao'] if resp else 'new'

        # --- Execução da Ação (Criar ou Usar Existente) ---
        
        if acao == 'update' and id_existente:
            id_topico_destino = id_existente
            nome_destino_real = self.mapa_nomes_reais_destino.get(id_existente, nome_topico_origem)
            print_success(f"Modo UPDATE ativado para '{nome_destino_real}'. Iniciando auditoria...")
            
            # >>> CHAMA O MÉTODO INTELIGENTE <<<
            await self._copiar_topico_inteligente(id_topico_origem, nome_topico_origem, id_topico_destino, nome_destino_real)
            
            self.progress_data['topicos_concluidos'].append(id_topico_origem)
            self._salvar_progresso()
            return # Sai da função, pois já resolveu

        else:
            # --- MODO DE CRIAÇÃO (CÓPIA SIMPLES) ---
            # Preparar nome (Maiúsculo ou Original)
            titulo_novo = nome_topico_origem
            if self.config.get('force_uppercase'):
                titulo_novo = titulo_novo.upper()
                
            try:
                print_info(f"Criando NOVO tópico de destino: '{titulo_novo}'...")
                updates = await self.client(functions.channels.CreateForumTopicRequest(
                    channel=self.destino,
                    title=titulo_novo,
                    random_id=int.from_bytes(os.urandom(8), 'big', signed=True)
                ))
                id_topico_destino = updates.updates[0].id
                
                # Atualiza cache para evitar duplicatas futuras na mesma execução
                novo_nome_norm = self._normalizar_nome_topico(titulo_novo)
                self.topicos_destino_cache[novo_nome_norm] = id_topico_destino
                self.mapa_nomes_reais_destino[id_topico_destino] = titulo_novo
                
            except FloodWaitError as e:
                await countdown_timer(e.seconds + 5, f"Criação do tópico '{titulo_novo}'")
                return await self._copiar_um_topico(id_topico_origem, nome_topico_origem)
            except Exception as e:
                print_error(f"Não foi possível criar o tópico: {e}. Pulando este tópico.")
                return

            # 2. Preparar iteração de mensagens (Modo Simples)
            ultimo_id_copiado = self.progress_data['progresso_topicos'].get(id_topico_origem, 0)
            reverse_flag = self.config['ordem'] == 'crescente'
            
            iter_kwargs = {'reverse': reverse_flag, 'limit': None, 'reply_to': id_topico_origem}
            if reverse_flag and ultimo_id_copiado > 0:
                iter_kwargs['min_id'] = ultimo_id_copiado
            elif not reverse_flag and ultimo_id_copiado > 0:
                iter_kwargs['offset_id'] = ultimo_id_copiado

            iterador = self.client.iter_messages(self.origem, **iter_kwargs)
            
            # 3. Loop de cópia
            lote_atual = []
            midias_copiadas_no_topico = 0
            midias_desde_pausa = 0
            link_primeira_midia = None
            mensagens_sem_midia_consecutivas = 0
            ultimo_id_processado = ultimo_id_copiado

            pbar = tqdm(desc=f"Copiando mídias", unit=" mídia", dynamic_ncols=True, file=sys.stderr)
            
            try:
                async for message in iterador:
                    ultimo_id_processado = message.id
                    if not message.media:
                        mensagens_sem_midia_consecutivas += 1
                        if mensagens_sem_midia_consecutivas >= MAX_MENSAGENS_SEM_MIDIA:
                            print_warning(f"Atingido o limite de {MAX_MENSAGENS_SEM_MIDIA} mensagens sem mídia. Finalizando tópico.")
                            break
                        continue
                    
                    mensagens_sem_midia_consecutivas = 0
                    lote_atual.append(message)

                    # Se o lote estiver cheio, envia
                    if len(lote_atual) >= LOTE_MIDIAS:
                        try:
                            await send_message_with_retry(
                                self.client, self.destino, file=[m.media for m in lote_atual], reply_to=id_topico_destino
                            )
                            # Salva link da primeira mensagem do PRIMEIRO lote
                            if not link_primeira_midia:
                                primeira_msg_album = (await self.client.get_messages(self.destino, reply_to=id_topico_destino, limit=1))[0]
                                link_primeira_midia = f"https://t.me/c/{self.destino.id}/{id_topico_destino}/{primeira_msg_album.id}"

                            midias_enviadas = len(lote_atual)
                            pbar.update(midias_enviadas)
                            midias_copiadas_no_topico += midias_enviadas
                            midias_desde_pausa += midias_enviadas
                            
                            self.progress_data['progresso_topicos'][id_topico_origem] = ultimo_id_processado
                            self._salvar_progresso()
                            lote_atual = []

                            # Lógica de Pausa
                            if self.config['pausa_a_cada'] > 0 and midias_desde_pausa >= self.config['pausa_a_cada']:
                                await countdown_timer(self.config['tempo_pausa_segundos'], "Pausa programada")
                                midias_desde_pausa = 0

                        except Exception as e:
                            print_error(f"Erro ao enviar lote no tópico '{nome_topico_origem}': {e}. O lote será ignorado.")
                            lote_atual = [] # Descarta o lote problemático


                # Envia o lote final, se houver
                if lote_atual:
                    await send_message_with_retry(
                        self.client, self.destino, file=[m.media for m in lote_atual], reply_to=id_topico_destino
                    )
                    if not link_primeira_midia:
                        primeira_msg_album = (await self.client.get_messages(self.destino, reply_to=id_topico_destino, limit=1))[0]
                        link_primeira_midia = f"https://t.me/c/{self.destino.id}/{id_topico_destino}/{primeira_msg_album.id}"
                    
                    pbar.update(len(lote_atual))
                    midias_copiadas_no_topico += len(lote_atual)

            finally:
                pbar.close()

            # 4. Finalização e Indexação
            if midias_copiadas_no_topico > 0:
                self.progress_data['topicos_concluidos'].append(id_topico_origem)
                self.progress_data['progresso_topicos'][id_topico_origem] = ultimo_id_processado
                
                if not link_primeira_midia: # Fallback de link
                    link_primeira_midia = f"https://t.me/c/{self.destino.id}/{id_topico_destino}"

                await self._atualizar_indice_geral(nome_topico_origem, link_primeira_midia, midias_copiadas_no_topico)
            
            self._salvar_progresso()
            print_success(f"Tópico '{nome_topico_origem}' concluído. Total de mídias copiadas: {midias_copiadas_no_topico}.")

    async def run(self):
        """Ponto de entrada principal para executar a tarefa."""
        if not await self._inicializar_entidades():
            return
        
        self._carregar_ou_criar_progresso()
        
        # Filtra tópicos já concluídos
        todos_selecionados = self.config['topicos_selecionados']
        topicos_concluidos = self.progress_data.get('topicos_concluidos', [])
        
        topicos_para_copiar = [
            (tid, self.config['nomes_topicos_selecionados'][tid])
            for tid in todos_selecionados
            if tid not in topicos_concluidos
        ]

        # Se todos já foram copiados, pergunta se quer forçar
        if not topicos_para_copiar and todos_selecionados:
            print_warning("Todos os tópicos selecionados constam como CONCLUÍDOS no histórico.")
            q = [inquirer.Confirm('reprocessar', message="Deseja processá-los novamente mesmo assim? (Isso ativará a verificação de atualização)", default=True)]
            resp = inquirer.prompt(q)
            
            if resp and resp['reprocessar']:
                print_info("Ignorando histórico de conclusão. Processando tudo...")
                topicos_para_copiar = [
                    (tid, self.config['nomes_topicos_selecionados'][tid])
                    for tid in todos_selecionados
                ]
            else:
                print_success("Operação cancelada. Nenhum tópico novo para copiar.")
                return

        print_info(f"{len(topicos_para_copiar)} de {len(todos_selecionados)} tópicos na fila para processar.")
        
        for id_topico, nome_topico in topicos_para_copiar:
            try:
                await self._copiar_um_topico(id_topico, nome_topico)
            except Exception as e:
                print_error(f"Erro fatal ao processar o tópico '{nome_topico}': {e}. Pulando para o próximo.")
                import traceback
                traceback.print_exc()

        print_section_header("TAREFA CONCLUÍDA")
        print_success("Todos os tópicos selecionados foram processados.")
