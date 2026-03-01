import os
import shutil
import stat
import inquirer
from .estilo import print_section_header, print_success, print_warning, print_error, print_info
from .database import DB_FILE, db

def on_rm_error(func, path, exc_info):
    """
    Handler de erro para shutil.rmtree.
    Tenta dar permissão de escrita se o arquivo for read-only (comum no Windows).
    """
    try:
        os.chmod(path, stat.S_IWRITE)
        os.unlink(path)
    except Exception:
        pass # Se falhar novamente, deixa o erro original propagar ou ser ignorado

def perform_factory_reset():
    """Executa a restauração de fábrica com opções de preservar contas."""
    print_section_header("⚠️  RESTAURAÇÃO DE FÁBRICA  ⚠️")
    
    print_warning("Esta ação irá APAGAR todos os dados do programa!")
    print_warning("- Histórico de auditorias")
    print_warning("- Progresso de tarefas")
    print_warning("- Configurações salvas")
    
    questions = [
        inquirer.List('mode',
                      message="Como deseja prosseguir?",
                      choices=[
                          ('🧹 Resetar TUDO (Manter apenas as contas logadas)', 'keep_accounts'),
                          ('☢️  Resetar TUDO + Deletar Contas (Zero absoluto)', 'full_wipe'),
                          ('❌ Cancelar', 'cancel')
                      ])
    ]
    answer = inquirer.prompt(questions)
    
    if not answer or answer['mode'] == 'cancel':
        print_info("Operação cancelada.")
        return

    # Confirmação Final
    confirm = inquirer.prompt([
        inquirer.Confirm('confirm', 
                         message="Tem CERTEZA ABSOLUTA? Esta ação não pode ser desfeita.", 
                         default=False)
    ])
    
    if not confirm or not confirm['confirm']:
        print_info("Operação cancelada.")
        return

    print_info("\nIniciando limpeza...")

    # 1. Deletar Banco de Dados
    if os.path.exists(DB_FILE):
        try:
            # Fecha a conexão antes de deletar
            db.close_connection()
            
            # Tenta remover o arquivo
            if os.path.exists(DB_FILE):
                os.remove(DB_FILE)
                print_success("Banco de dados removido.")
        except Exception as e:
            print_error(f"Erro ao remover banco de dados: {e}")

    # 2. Deletar Arquivos JSON Antigos (Limpeza de Legado)
    dados_dir = 'dados'
    arquivos_json = [
        'progresso_copia.json', 
        'tarefas_salvas.json', 
        'settings.json'
    ]
    
    # Remove arquivos soltos
    for f in arquivos_json:
        path = os.path.join(dados_dir, f)
        if os.path.exists(path):
            try:
                os.remove(path)
                print_success(f"Arquivo removido: {f}")
            except Exception as e:
                print_error(f"Erro ao remover {f}: {e}")

    # Remove pastas de cache/auditoria
    pastas_a_limpar = [
        os.path.join(dados_dir, 'auditorias'),
        # Outras pastas de cache se houver
    ]
    
    # Remove caches de tópicos (cache_topicos_*.json)
    if os.path.exists(dados_dir):
        for f in os.listdir(dados_dir):
            if f.startswith('cache_topicos_') and f.endswith('.json'):
                try:
                    os.remove(os.path.join(dados_dir, f))
                except: pass

    for pasta in pastas_a_limpar:
        if os.path.exists(pasta):
            try:
                shutil.rmtree(pasta, onerror=on_rm_error)
                os.makedirs(pasta, exist_ok=True) # Recria vazia
                print_success(f"Pasta limpa: {pasta}")
            except Exception as e:
                print_error(f"Erro ao limpar pasta {pasta}: {e}")

    # 3. Deletar Contas (Se solicitado)
    if answer['mode'] == 'full_wipe':
        contas_dir = 'contas'
        if os.path.exists(contas_dir):
            try:
                # Remove todos os arquivos de sessão
                for f in os.listdir(contas_dir):
                    os.remove(os.path.join(contas_dir, f))
                print_success("Todas as contas foram desconectadas e removidas.")
            except Exception as e:
                print_error(f"Erro ao remover contas: {e}")
    else:
        print_info("As contas logadas foram preservadas.")

    print_success("\n✅ Restauração de fábrica concluída!")
    print_info("Por favor, reinicie o programa para aplicar todas as alterações.")
    input("\nPressione Enter para sair...")
    import sys
    sys.exit()
