9# main.py (VERSÃO ATUALIZADA COM MODO INTELIGENTE E SQLITE)

import inquirer
import asyncio
import os
import sys

# [S7] Inicializa o sistema de logging antes de tudo
from src.logger import get_logger, log_operation
logger = get_logger()

# Importa de nossos outros arquivos
from src import gerenciador_dados as dados
from src.gerenciador_contas import GerenciadorContas
from src import interface
from src.copiador_inteligente import CopiadorInteligente
from src.copiador_de_topicos import CopiadorDeTopicos
from src.auditoria import AuditoriaGrupo, deletar_auditoria_salva
from src.factory_reset import perform_factory_reset
from src import utils
from src.config import get_config
from src.client_pool import client_pool  # Pool de múltiplas contas

async def verificar_retomada(client):
    """Verifica se há tarefas interrompidas e oferece retomada."""
    tarefas_ativas = dados.get_active_tasks()
    
    if not tarefas_ativas:
        return

    print("\n" + "="*60)
    interface.print_warning(f"⚠️ DETECTADAS {len(tarefas_ativas)} TAREFA(S) INTERROMPIDA(S)!")
    print("="*60)
    
    perguntas = [
        inquirer.List('acao',
                      message="O que deseja fazer?",
                      choices=[
                          ('✅ Retomar última tarefa interrompida', 'retomar'),
                          ('❌ Ignorar e ir para o menu principal', 'ignorar'),
                          ('🗑️ Cancelar/Remover flag de "executando"', 'limpar')
                      ])
    ]
    resp = inquirer.prompt(perguntas)
    
    if resp['acao'] == 'retomar':
        # Pega a última
        tarefa = tarefas_ativas[-1]
        task_config = tarefa['config']
        task_key = tarefa['key']
        
        interface.print_info(f"Retomando: {task_config['nome_origem']} -> {task_config['nome_destino']}")
        
        # Lógica de decisão de qual copiador usar
        if task_config.get('tipo') == 'clonagem':
            from src.clonador_completo import ClonadorCompleto
            try:
                grupo_origem = await client.get_entity(task_config['id_origem'])
                grupo_destino = await client.get_entity(task_config['id_destino']) if task_config.get('id_destino') else None
                copiador_task = ClonadorCompleto(
                    client,
                    grupo_origem,
                    task_config.get('copiar_legendas', True),
                    destino_existente=grupo_destino,
                    auditar_destino=task_config.get('auditar_destino', False)
                )
                copiador_task.lote_size = task_config.get('lote_size', 10)
                copiador_task.pausa_segundos = task_config.get('pausa_segundos', 15)
                copiador_task.album_mode = task_config.get('album_mode', 'copy_origin')
                copiador_task.album_size = task_config.get('album_size', 10)
                if task_config.get('nome_grupo_customizado'):
                    copiador_task.nome_grupo_customizado = task_config['nome_grupo_customizado']
                copiador_task.task_key = task_key
            except Exception as e:
                interface.print_error(f"Erro ao preparar retomada de clonagem: {e}")
                return
        else:
            copiador_task = CopiadorInteligente(client, task_config, task_key)
        
        await copiador_task.run()
        input("\nPressione Enter para ir ao menu principal...")

    elif resp['acao'] == 'limpar':
        for t in tarefas_ativas:
            dados.set_task_active(t['key'], False)
        interface.print_success("Status das tarefas limpo.")

async def main():
    interface.print_banner()
    
    # 1. Garante que as pastas existam
    dados.criar_pastas_necessarias()
    
    # 1.5 NOVO: Backup automático diário
    utils.criar_backup()

    # 2. Gerenciador de Contas
    contas_manager = GerenciadorContas()

    # 3. Tenta Login Automático
    client, telefone = await contas_manager.login_automatico()
    
    if not client:
        # 4. Falhou? Vai para o Menu de Login Manual
        client, telefone = await contas_manager.menu_de_login()
        if not client:
            interface.print_warning("\nSaindo do programa. Até logo!")
            sys.exit()
            
    # --- NOVO: Verifica retomada ---
    await verificar_retomada(client)
    
    # --- Loop do Menu Principal ---
    while True:
        escolha_menu = interface.prompt_menu_principal(telefone)
        
        if escolha_menu == 'nova_tarefa':
            # Chama o assistente de configuração
            task_config = await interface.prompt_nova_tarefa(client)
            if task_config:
                task_key = f"{task_config['id_origem']}_{task_config['id_destino']}"
                
                # Salva a tarefa se o usuário pediu
                if task_config.pop('salvar_tarefa', False):
                    dados.save_task(task_key, task_config)
                    interface.print_success("Tarefa salva com sucesso!")
                
                # Marca como ativa no DB
                dados.set_task_active(task_key, True)

                try:
                    # Pergunta filtro de tipo de arquivo
                    file_type_filter = await interface.prompt_file_filter()
                    
                    # NOVO: Perguntar sobre rotação de contas
                    pool_ativo = None
                    usar_rotacao = inquirer.prompt([
                        inquirer.Confirm('rotacao',
                                        message="🔄 Usar ROTAÇÃO DE CONTAS? (dobra velocidade se 2+ contas cadastradas)",
                                        default=False)
                    ])
                    
                    if usar_rotacao and usar_rotacao['rotacao']:
                        # Conectar todas as contas disponíveis
                        interface.print_info("Conectando contas adicionais...")
                        num_contas = await client_pool.connect_all_accounts()
                        if num_contas > 1:
                            interface.print_success(f"✅ Rotação ativada com {num_contas} contas!")
                            pool_ativo = client_pool
                        else:
                            interface.print_warning("⚠️ Apenas 1 conta disponível. Continuando sem rotação.")
                    
                    # Sempre usa modo inteligente (persistência garantida)
                    interface.print_info("🧠 Usando Modo Inteligente (persistência ativada)")
                    copiador_task = CopiadorInteligente(client, task_config, task_key, file_type_filter, telefone, client_pool=pool_ativo)
                    await copiador_task.run()
                finally:
                    # Remove flag de ativa ao terminar (ou erro tratado internamente)
                    dados.set_task_active(task_key, False)
                    # Desconectar pool se foi usado
                    if pool_ativo:
                        await client_pool.disconnect_all()
            
            input("\nPressione Enter para voltar ao menu...")
        
        elif escolha_menu == 'clonar_completo':
            # FUNÇÃO: Clonar Grupo Completo
            from src.clonador_completo import ClonadorCompleto
            import os
            
            interface.print_section_header("CLONAR GRUPO COMPLETO")
            
            # Verificar se há progresso salvo
            arquivo_progresso = 'dados/clonagem_progresso.json'
            tem_progresso = os.path.exists(arquivo_progresso)
            
            if tem_progresso:
                interface.print_success("✅ Encontrado progresso de clonagem anterior!")
                
                modo_resp = inquirer.prompt([
                    inquirer.List('modo',
                                  message="O que deseja fazer?",
                                  choices=[
                                      ('🔄 RETOMAR clonagem anterior', 'retomar'),
                                      ('🆕 COMEÇAR DO ZERO (nova clonagem)', 'novo'),
                                      ('🗑️ APAGAR progresso e voltar', 'apagar'),
                                      ('⬅️ Voltar', 'voltar')
                                  ])
                ])
                
                if not modo_resp or modo_resp['modo'] == 'voltar':
                    continue
                
                if modo_resp['modo'] == 'apagar':
                    os.remove(arquivo_progresso)
                    interface.print_success("Progresso apagado!")
                    continue
                
                if modo_resp['modo'] == 'retomar':
                    # Carregar progresso e retomar
                    import json
                    with open(arquivo_progresso, 'r', encoding='utf-8') as f:
                        prog = json.load(f)
                    
                    try:
                        grupo_origem = await client.get_entity(prog['origem_id'])
                        interface.print_info(f"Origem: {prog['origem_nome']}")
                        
                        # Perguntar auditoria
                        auditoria_resp = inquirer.prompt([
                            inquirer.Confirm('auditoria', 
                                            message="Auditar destino? (verifica mídias já copiadas)", 
                                            default=True)
                        ])
                        auditar = auditoria_resp['auditoria'] if auditoria_resp else True
                        
                        clonador = ClonadorCompleto(client, grupo_origem, True, auditar_destino=auditar)
                        await clonador.run()
                        input("\nPressione Enter para voltar ao menu...")
                        continue
                        
                    except Exception as e:
                        interface.print_error(f"Erro ao retomar: {e}")
                        continue
            
            # NOVA CLONAGEM
            interface.print_info("Esta função irá:")
            interface.print_info("  1. Copiar APENAS fotos e vídeos")
            interface.print_info("  2. Pausar entre lotes (configurável)")
            interface.print_info("  3. Salvar progresso para retomada")
            print()
            
            # 1. Configurar pausas e lotes
            config_pausa = inquirer.prompt([
                inquirer.Text('lote_size',
                             message="Quantas mídias copiar antes de pausar?",
                             default="10",
                             validate=lambda _, x: x.isdigit() and int(x) > 0),
                inquirer.Text('pausa_segundos',
                             message="Quantos segundos pausar entre lotes?",
                             default="15",
                             validate=lambda _, x: x.isdigit() and int(x) >= 0)
            ])
            
            if not config_pausa:
                continue
            
            lote_size = int(config_pausa['lote_size'])
            pausa_segundos = int(config_pausa['pausa_segundos'])
            
            interface.print_success(f"✅ Configurado: Pausar {pausa_segundos}s a cada {lote_size} mídias")
            print()
            
            # 2. Selecionar grupo origem
            grupo_origem = await interface.selecionar_grupo(client, "Selecione o grupo de ORIGEM", 'any')
            if not grupo_origem:
                continue
            
            # 2. Escolher destino: criar novo ou usar existente
            destino_resp = inquirer.prompt([
                inquirer.List('destino',
                              message="Onde as mídias serão copiadas?",
                              choices=[
                                  ('🆕 CRIAR novo grupo', 'criar'),
                                  ('📁 USAR grupo existente', 'existente')
                              ])
            ])
            
            if not destino_resp:
                continue
            
            grupo_destino = None
            nome_grupo = None
            
            if destino_resp['destino'] == 'criar':
                # Perguntar nome do grupo
                nome_resp = inquirer.prompt([
                    inquirer.Text('nome',
                                  message="Nome do novo grupo (Enter para usar o original)",
                                  default=grupo_origem.title)
                ])
                nome_grupo = nome_resp['nome'] if nome_resp else grupo_origem.title
                
            else:
                # Selecionar grupo existente
                grupo_destino = await interface.selecionar_grupo(client, "Selecione o grupo DESTINO", 'any')
                if not grupo_destino:
                    continue
                
                if grupo_destino.id == grupo_origem.id:
                    interface.print_error("Origem e destino não podem ser o mesmo!")
                    continue
            
            # 3. Perguntar sobre legendas
            legendas_resp = inquirer.prompt([
                inquirer.Confirm('legendas', 
                                message="Copiar LEGENDAS das mídias?", 
                                default=True)
            ])
            copiar_legendas = legendas_resp['legendas'] if legendas_resp else True
            
            # 4. Perguntar sobre modo de álbum
            album_resp = inquirer.prompt([
                inquirer.List('album_mode',
                             message="Como deseja agrupar as mídias?",
                             choices=[
                                 ('📸 Copiar exatamente como está na origem (mantém álbuns originais)', 'copy_origin'),
                                 ('🎨 Criar álbuns personalizados (escolher tamanho)', 'manual')
                             ])
            ])
            
            if not album_resp:
                continue
            
            album_mode = album_resp['album_mode']
            album_size = 10  # Valor padrão
            
            if album_mode == 'manual':
                # Perguntar tamanho do álbum
                album_size_resp = inquirer.prompt([
                    inquirer.Text('album_size',
                                 message="Quantas mídias por álbum? (1-10)",
                                 default="10",
                                 validate=lambda _, x: x.isdigit() and 1 <= int(x) <= 10)
                ])
                
                if not album_size_resp:
                    continue
                
                album_size = int(album_size_resp['album_size'])
                interface.print_info(f"✅ Álbuns de {album_size} mídias")
            else:
                interface.print_info("✅ Mantendo estrutura de álbuns original")
            
            # 5. Perguntar sobre auditoria
            auditoria_resp = inquirer.prompt([
                inquirer.Confirm('auditoria', 
                                message="Auditar destino? (verifica duplicatas, mais lento)", 
                                default=False)
            ])
            auditar_destino = auditoria_resp['auditoria'] if auditoria_resp else False
            
            # 5. Confirmar
            if grupo_destino:
                interface.print_warning(f"\n⚠️ Mídias serão copiadas para: '{grupo_destino.title}'")
            else:
                interface.print_warning(f"\n⚠️ Será criado novo grupo: '{nome_grupo}'")
            
            confirmar = inquirer.prompt([
                inquirer.Confirm('confirmar', message="Confirma?", default=True)
            ])
            
            if not confirmar or not confirmar['confirmar']:
                interface.print_info("Operação cancelada.")
                continue
            
            # 6. Perguntar se deseja salvar como tarefa
            salvar_resp = inquirer.prompt([
                inquirer.Confirm('salvar', 
                                message="Salvar como Tarefa Rápida? (poderá retomar depois)", 
                                default=True)
            ])
            
            # Montar configuração da tarefa
            task_config = {
                'tipo': 'clonagem',  # NOVO: Tipo de tarefa
                'id_origem': grupo_origem.id,
                'nome_origem': grupo_origem.title,
                'id_destino': grupo_destino.id if grupo_destino else None,
                'nome_destino': grupo_destino.title if grupo_destino else nome_grupo,
                'copiar_legendas': copiar_legendas,
                'auditar_destino': auditar_destino,
                'nome_grupo_customizado': nome_grupo if not grupo_destino else None,
                'modo': 'Clonagem Completa',
                'lote_size': lote_size,
                'pausa_segundos': pausa_segundos,
                'album_mode': album_mode,
                'album_size': album_size
            }
            
            # Gerar chave única
            task_key = f"clonagem_{grupo_origem.id}_{grupo_destino.id if grupo_destino else 'novo'}"
            
            # Salvar se solicitado
            if salvar_resp and salvar_resp['salvar']:
                dados.save_task(task_key, task_config)
                interface.print_success("✅ Tarefa salva! Você pode retomá-la em 'Executar Tarefa Salva'")
            
            # 7. Executar clonagem
            clonador = ClonadorCompleto(
                client, 
                grupo_origem, 
                copiar_legendas, 
                destino_existente=grupo_destino,
                auditar_destino=auditar_destino
            )
            
            # Configurar parâmetros personalizados
            clonador.lote_size = lote_size
            clonador.pausa_segundos = pausa_segundos
            clonador.album_mode = album_mode
            clonador.album_size = album_size
            
            # Se for criar novo grupo com nome personalizado
            if nome_grupo and nome_grupo != grupo_origem.title:
                clonador.nome_grupo_customizado = nome_grupo
            
            # Definir task_key para progresso
            clonador.task_key = task_key
            
            await clonador.run()
            
            input("\nPressione Enter para voltar ao menu...")
        
        elif escolha_menu == 'copiar_topicos':
            while True:
                config = await interface.prompt_copiar_topicos(client)
                if not config:
                    break # Volta para o menu principal

                copiador_task = CopiadorDeTopicos(client, config)
                await copiador_task.run()

                # Pergunta se quer continuar
                
                continuar = inquirer.prompt([
                    inquirer.Confirm('continue', message="Deseja realizar uma nova cópia de tópicos?", default=False)
                ])
                if not continuar or not continuar['continue']:
                    break # Volta para o menu principal

        elif escolha_menu == 'criar_indice':
            await interface.prompt_criar_indice(client)
            input("\nPressione Enter para voltar ao menu...")

        elif escolha_menu == 'deletar_topicos':
            await interface.prompt_deletar_topicos(client)
            input("\nPressione Enter para voltar ao menu...")

        elif escolha_menu == 'criar_grupos':
            await interface.prompt_criar_grupos_massa(client)
            input("\nPressione Enter para voltar ao menu...")

        elif escolha_menu == 'tarefa_salva':
            # Menu de Executar Tarefa Salva
            from src.clonador_completo import ClonadorCompleto
            
            tarefas = dados.load_tasks()
            if not tarefas:
                interface.print_warning("Nenhuma tarefa salva encontrada.")
                input("\nPressione Enter para voltar ao menu...")
                continue
            
            # Montar lista de escolhas com indicador de tipo
            choices = []
            from datetime import datetime
            for key, cfg in tarefas.items():
                tipo = cfg.get('tipo', 'copia')
                
                created_str = cfg.get('_created_at', '')
                if created_str:
                    try:
                        dt_c = datetime.fromisoformat(created_str.split('.')[0])
                        created_str = dt_c.strftime('%d/%m %H:%M')
                    except: pass
                
                updated_str = cfg.get('_updated_at', '')
                if updated_str:
                    try:
                        dt_u = datetime.fromisoformat(updated_str.split('.')[0])
                        updated_str = dt_u.strftime('%d/%m %H:%M')
                    except: pass
                
                status_raw = cfg.get('_status', 'stopped')
                status_str = "(▶️ Em Andamento)" if status_raw == 'running' else "(⏸️ Pausado)"
                
                time_info = f" [Início: {created_str} | Parou: {updated_str}]" if created_str and updated_str else ""
                
                if tipo == 'clonagem':
                    label = f"🔄 [CLONAGEM] {cfg['nome_origem']} -> {cfg['nome_destino']}{time_info} {status_str}"
                else:
                    label = f"📋 [CÓPIA] {cfg['nome_origem']} -> {cfg['nome_destino']}{time_info} {status_str}"
                
                choices.append((label, key))
            
            choices.append(('🗑️ Deletar tarefa', 'deletar'))
            choices.append(('⬅️ Voltar', None))
            
            selecao = inquirer.prompt([
                inquirer.List('tarefa',
                              message="Selecione a tarefa para executar:",
                              choices=choices)
            ])
            
            if not selecao or not selecao['tarefa']:
                continue
            
            if selecao['tarefa'] == 'deletar':
                # Submenu de deletar
                del_choices = [(f"{cfg['nome_origem']} -> {cfg['nome_destino']}", key) for key, cfg in tarefas.items()]
                del_choices.append(('⬅️ Voltar', None))
                
                del_sel = inquirer.prompt([
                    inquirer.List('del_tarefa', message="Qual tarefa deletar?", choices=del_choices)
                ])
                
                if del_sel and del_sel['del_tarefa']:
                    dados.delete_task(del_sel['del_tarefa'])
                    interface.print_success("Tarefa deletada!")
                continue
            
            task_key = selecao['tarefa']
            task_config = tarefas[task_key]
            interface.print_info(f"Carregando tarefa: '{task_config['nome_origem']}' -> '{task_config['nome_destino']}'")
            
            # Verificar tipo de tarefa
            if task_config.get('tipo') == 'clonagem':
                # EXECUTAR CLONAGEM
                interface.print_info("🔄 Tipo: Clonagem Completa")
                
                try:
                    # Obter grupo origem
                    grupo_origem = await client.get_entity(task_config['id_origem'])
                    
                    # Obter grupo destino se existir
                    grupo_destino = None
                    if task_config.get('id_destino'):
                        try:
                            grupo_destino = await client.get_entity(task_config['id_destino'])
                        except Exception:
                            interface.print_warning("Grupo destino não encontrado, será criado novo")
                    
                    # Perguntar auditoria
                    auditoria_resp = inquirer.prompt([
                        inquirer.Confirm('auditoria', 
                                        message="Auditar destino? (verifica duplicatas)", 
                                        default=True)
                    ])
                    auditar = auditoria_resp['auditoria'] if auditoria_resp else True
                    
                    # Executar clonador
                    clonador = ClonadorCompleto(
                        client, 
                        grupo_origem, 
                        task_config.get('copiar_legendas', True),
                        destino_existente=grupo_destino,
                        auditar_destino=auditar
                    )
                    
                    # Configurar parâmetros personalizados (usa valores salvos ou padrão)
                    clonador.lote_size = task_config.get('lote_size', 10)
                    clonador.pausa_segundos = task_config.get('pausa_segundos', 15)
                    clonador.album_mode = task_config.get('album_mode', 'copy_origin')
                    clonador.album_size = task_config.get('album_size', 10)
                    
                    # Nome customizado
                    if task_config.get('nome_grupo_customizado'):
                        clonador.nome_grupo_customizado = task_config['nome_grupo_customizado']
                    
                    clonador.task_key = task_key
                    await clonador.run()
                    
                except Exception as e:
                    interface.print_error(f"Erro ao executar clonagem: {e}")
            else:
                # EXECUTAR CÓPIA NORMAL
                interface.print_info("🧠 Tipo: Cópia Inteligente")
                
                dados.set_task_active(task_key, True)
                try:
                    file_type_filter = await interface.prompt_file_filter()
                    copiador_task = CopiadorInteligente(client, task_config, task_key, file_type_filter, telefone)
                    await copiador_task.run()
                finally:
                    dados.set_task_active(task_key, False)
            
            input("\nPressione Enter para voltar ao menu...")

        elif escolha_menu == 'auditoria':
            # ... (código existente de auditoria) ...
            while True:
                acao_auditoria = interface.prompt_menu_auditoria()
                grupo = None

                if acao_auditoria == 'nova':
                    grupo = await interface.selecionar_grupo(client, "Selecione o grupo para criar uma NOVA auditoria", 'any')
                    if grupo:
                        auditor = AuditoriaGrupo(client, grupo, grupo.title, telefone)
                        await auditor.auditar_completo(force_refresh=True)
                    input("\nPressione Enter para voltar ao menu...")

                elif acao_auditoria == 'atualizar':
                    # Como listar auditorias agora busca do DB ou falha graciosa, vamos ver
                    # Se listar_auditorias_salvas retornar vazio, ele avisa
                    grupo = await interface.selecionar_grupo_com_auditoria(client, "Selecione a auditoria para ATUALIZAR")
                    if grupo:
                        auditor = AuditoriaGrupo(client, grupo, grupo.title, telefone)
                        await auditor.auditar_reverso_incremental()
                    input("\nPressione Enter para voltar ao menu...")

                elif acao_auditoria == 'ver_detalhes':
                    await interface.prompt_ver_detalhes_auditoria(client)
                    input("\nPressione Enter para voltar ao menu...")
                
                elif acao_auditoria == 'deletar':
                    # Selecionar qual auditoria deletar
                    grupo = await interface.selecionar_grupo_com_auditoria(client, "Selecione a auditoria para DELETAR")
                    if grupo:
                        confirmar = inquirer.prompt([
                            inquirer.Confirm('confirmar', 
                                             message=f"Tem certeza que deseja deletar a auditoria de '{grupo.title}'? Esta ação não pode ser desfeita!",
                                             default=False)
                        ])
                        if confirmar and confirmar['confirmar']:
                            deletar_auditoria_salva(grupo.id)
                        else:
                            interface.print_info("Operação cancelada.")
                    input("\nPressione Enter para voltar...")
                    
                elif acao_auditoria == 'voltar':
                    break

        elif escolha_menu == 'backup':
            interface.print_section_header("Backup Manual")
            utils.criar_backup()
            input("\nPressione Enter para voltar ao menu...")

        elif escolha_menu == 'contas':
            # Submenu de Contas
            while True:
                escolha_contas = interface.prompt_menu_contas()
                if escolha_contas == 'adicionar':
                    await contas_manager.adicionar_conta()
                elif escolha_contas == 'remover':
                    await contas_manager.remover_conta()
                elif escolha_contas == 'trocar':
                    await client.disconnect()
                    interface.print_info("Sessão desconectada. Indo para o Menu de Login...")
                    await asyncio.sleep(1)
                    client, telefone = await contas_manager.menu_de_login()
                    if not client:
                        interface.print_warning("\nSaindo do programa. Até logo!")
                        sys.exit()
                    break
                elif escolha_contas == 'voltar':
                    break
        
        elif escolha_menu == 'estatisticas':
            # NOVO: Menu de Estatísticas
            utils.exibir_estatisticas()
            input("\nPressione Enter para voltar ao menu...")
        
        elif escolha_menu == 'ver_falhas':
            # NOVO: Menu de Falhas
            utils.exibir_falhas()
            
            # Perguntar se quer marcar como resolvidas
            falhas_count = utils.contar_falhas_pendentes()
            if falhas_count > 0:
                resolver = inquirer.prompt([
                    inquirer.Confirm('resolver', 
                                     message=f"Marcar todas as {falhas_count} falhas como resolvidas?", 
                                     default=False)
                ])
                if resolver and resolver['resolver']:
                    utils.marcar_todas_resolvidas()
            
            input("\nPressione Enter para voltar ao menu...")
        
        elif escolha_menu == 'factory_reset':
            perform_factory_reset()

        elif escolha_menu == 'sair':
            break

    # --- Fim do Programa ---
    if client and client.is_connected():
        await client.disconnect()
    
    interface.print_success("\nPrograma finalizado com segurança. Até a próxima!")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        interface.print_warning("\nPrograma interrompido pelo usuário.")