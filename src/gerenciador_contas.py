# gerenciador_contas.py

import os
import getpass
import shutil
import inquirer
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors.rpcerrorlist import (
    SessionPasswordNeededError, PhoneCodeInvalidError,
    ApiIdInvalidError, AuthKeyError
)

# Importa de nossos outros arquivos
from . import gerenciador_dados as dados
from .estilo import print_success, print_error, print_warning, print_section_header

class GerenciadorContas:
    def __init__(self):
        self.contas_dir = dados.CONTAS_DIR
        self.client = None
        self.telefone_logado = None

    def _get_session_path(self, telefone):
        """Retorna o caminho padrão para o arquivo de sessão."""
        # Remove caracteres inválidos para nome de arquivo
        safe_phone = ''.join(c for c in telefone if c.isalnum())
        return os.path.join(self.contas_dir, safe_phone)

    async def _conectar_cliente(self, telefone, api_id, api_hash):
        """Tenta conectar com uma conta específica."""
        session_path = self._get_session_path(telefone)
        
        # O api_id é um int, mas o api_hash é uma string.
        client = TelegramClient(session_path, int(api_id), api_hash)
        
        await client.connect()
        
        if not await client.is_user_authorized():
            print_warning(f"Sessão para {telefone} expirou ou é inválida. Autenticação necessária.")
            try:
                await client.send_code_request(telefone)
                code = input(f"Digite o código enviado para {telefone}: ").strip()
                await client.sign_in(telefone, code)
            except PhoneCodeInvalidError:
                print_error("Código inválido.")
                await client.disconnect()
                return None
            except SessionPasswordNeededError:
                password = getpass.getpass("Conta protegida por 2FA. Digite sua senha: ")
                await client.sign_in(password=password)
        
        me = await client.get_me()
        print_success(f"Login bem-sucedido como {me.first_name} (@{me.username})!")
        return client

    async def login_automatico(self):
        """Tenta logar automaticamente na última conta usada."""
        print("Tentando login automático...")
        settings = dados.load_settings()
        ultima_conta_info = settings.get('ultima_conta')

        if not ultima_conta_info:
            print_warning("Nenhuma conta salva para login automático.")
            return None, None

        telefone = ultima_conta_info.get('telefone')
        api_id = ultima_conta_info.get('api_id')
        api_hash = ultima_conta_info.get('api_hash')

        if not all([telefone, api_id, api_hash]):
            print_warning("Dados da última conta estão incompletos.")
            return None, None

        try:
            self.client = await self._conectar_cliente(telefone, api_id, api_hash)
            if self.client:
                self.telefone_logado = telefone
                return self.client, self.telefone_logado
        except Exception as e:
            if "int() with base 10" in str(e) and str(api_hash) in str(e):
                print_error(f"Erro de configuração: API HASH salvo ({api_hash}) parece inválido.")
            else:
                print_error(f"Falha no login automático: {e}")
            return None, None
        
        return None, None

    async def menu_de_login(self):
        """Mostra o menu principal de login (manual)."""
        while True:
            os.system('cls' if os.name == 'nt' else 'clear')
            print_section_header("Menu de Login")
            
            # Nomes dos arquivos de sessão (ex: '5521999999999')
            contas_salvas = [f.split('.')[0] for f in os.listdir(self.contas_dir) if f.endswith('.session')]
            
            choices = []
            settings = dados.load_settings()
            
            # --- INÍCIO DA CORREÇÃO DO MENU DUPLICADO ---
            
            # Cria um set de telefones (formato 'safe') que já estão no settings.json
            phones_in_settings_safe = set()

            # 1. Adiciona contas com detalhes do settings.json
            for conta_key, conta_info in settings.items():
                if conta_key == 'ultima_conta' or not isinstance(conta_info, dict):
                    continue
                
                telefone = conta_info['telefone']
                choices.append((f"👤 {telefone}", telefone))
                
                # Adiciona a versão "safe" (sem '+') ao set
                safe_phone = ''.join(c for c in telefone if c.isalnum())
                phones_in_settings_safe.add(safe_phone)

            # 2. Adiciona contas que têm sessão mas não estão no settings
            for session_file_phone in contas_salvas:
                # session_file_phone já é o formato "safe" (ex: 5521999999999)
                
                # Só adiciona se o formato "safe" não foi encontrado no settings
                if session_file_phone not in phones_in_settings_safe:
                     # Mostra o telefone "safe" pois não temos o com '+'
                     choices.append((f"❓ {session_file_phone} (Sessão existe)", session_file_phone))
            
            # --- FIM DA CORREÇÃO ---

            choices.append(("➕ Adicionar Nova Conta", "adicionar"))
            choices.append(("➖ Remover Conta", "remover"))
            choices.append(("🚪 Sair do Programa", "sair"))
            
            perguntas = [
                inquirer.List('acao',
                              message="Selecione uma conta ou ação:",
                              choices=choices,
                              carousel=True),
            ]
            resposta = inquirer.prompt(perguntas)
            if not resposta or resposta['acao'] == 'sair':
                return None, None
            
            acao = resposta['acao']
            
            if acao == 'adicionar':
                await self.adicionar_conta()
            elif acao == 'remover':
                await self.remover_conta()
            else:
                # Tentativa de login com conta selecionada
                telefone_selecionado = acao
                settings = dados.load_settings()
                
                # Busca a conta no settings.json pelo telefone (que pode ter '+' ou não)
                conta_info = settings.get(telefone_selecionado)
                
                # Se não achou (ex: selecionou '5521...'), tenta achar a que tem '+'
                if not conta_info:
                    telefone_selecionado_safe = ''.join(c for c in telefone_selecionado if c.isalnum())
                    for key, info in settings.items():
                        if isinstance(info, dict) and ''.join(c for c in info.get('telefone', '') if c.isalnum()) == telefone_selecionado_safe:
                            conta_info = info
                            telefone_selecionado = info['telefone'] # Pega o telefone correto com '+'
                            break

                if not conta_info:
                    print_error(f"Não foi possível encontrar os dados (API ID/HASH) para {telefone_selecionado}. Tente removê-la e adicioná-la novamente.")
                    input("Pressione Enter para continuar...")
                    continue
                
                try:
                    self.client = await self._conectar_cliente(telefone_selecionado, conta_info['api_id'], conta_info['api_hash'])
                    if self.client:
                        self.telefone_logado = telefone_selecionado
                        # Salva como a última conta logada
                        settings['ultima_conta'] = settings.get(telefone_selecionado)
                        dados.save_settings(settings)
                        return self.client, self.telefone_logado
                except (ApiIdInvalidError, AuthKeyError):
                    print_error("API ID ou API Hash inválidos para esta conta.")
                except Exception as e:
                    print_error(f"Erro ao conectar: {e}")
                
                input("Pressione Enter para continuar...")
    
    async def adicionar_conta(self):
        """Fluxo para adicionar uma nova conta."""
        print_section_header("Adicionar Nova Conta")
        try:
            respostas = inquirer.prompt([
                inquirer.Text('telefone', message="Digite o telefone (formato +5521...)"),
                inquirer.Text('api_id', message="Digite a API ID", validate=lambda _, x: x.isdigit()),
                inquirer.Text('api_hash', message="Digite a API HASH"),
            ])
            if not respostas or not all(respostas.values()):
                print_warning("Cadastro cancelado."); return

            telefone = respostas['telefone']
            api_id = int(respostas['api_id']) # Convertido aqui
            api_hash = respostas['api_hash'] # Permanece string

            client_temp = await self._conectar_cliente(telefone, api_id, api_hash)
            
            if client_temp:
                settings = dados.load_settings()
                settings[telefone] = {"telefone": telefone, "api_id": api_id, "api_hash": api_hash}
                dados.save_settings(settings)
                print_success(f"Conta {telefone} adicionada e logada com sucesso!")
                await client_temp.disconnect()
            else:
                print_error("Não foi possível logar e salvar a sessão da nova conta.")
        
        except (KeyboardInterrupt, TypeError):
            print_warning("\nOperação cancelada.")
        except Exception as e:
            print_error(f"Erro ao adicionar conta: {e}")
        input("Pressione Enter para continuar...")

    async def remover_conta(self):
        """Fluxo para remover uma conta."""
        print_section_header("Remover Conta")
        settings = dados.load_settings()
        
        contas = []
        for key, value in settings.items():
            if isinstance(value, dict) and 'telefone' in value:
                contas.append(value['telefone'])
        
        if not contas:
            print_warning("Nenhuma conta configurada para remover.")
            input("Pressione Enter para continuar..."); return

        perguntas = [
            inquirer.List('telefone', message="Selecione a conta para remover", choices=contas + ["Cancelar"])
        ]
        resposta = inquirer.prompt(perguntas)

        if not resposta or resposta['telefone'] == "Cancelar":
            print_warning("Remoção cancelada."); return
        
        telefone_para_remover = resposta['telefone']

        if inquirer.prompt([inquirer.Confirm('confirm', message=f"Tem certeza que quer remover {telefone_para_remover}?", default=False)]).get('confirm'):
            # Remove do settings.json
            settings.pop(telefone_para_remover, None)
            if settings.get('ultima_conta', {}).get('telefone') == telefone_para_remover:
                settings.pop('ultima_conta', None) 
            dados.save_settings(settings)
            
            session_path = self._get_session_path(telefone_para_remover)
            session_file_path = session_path + ".session"
            if os.path.exists(session_file_path):
                os.remove(session_file_path)
            
            print_success(f"Conta {telefone_para_remover} removida com sucesso.")
        else:
            print_warning("Remoção cancelada.")
        input("Pressione Enter para continuar...")