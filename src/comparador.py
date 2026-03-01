# comparador.py
# Compara auditorias de ORIGEM vs DESTINO e identifica mídias pendentes
# NOVO: Detecção híbrida usando file_unique_id + signature para pegar duplicatas manuais

import json
import os
from collections import defaultdict
from .database import db
from .interface import print_success, print_error, print_warning, print_info, print_section_header


class ComparadorMidias:
    """
    Compara auditorias usando múltiplos métodos:
    1. file_unique_id - Detecta mesma mídia mesmo se inserida manualmente
    2. signature (MD5 de metadados) - Fallback quando file_unique_id não disponível
    """
    
    def __init__(self, auditoria_origem, auditoria_destino):
        """
        auditoria_origem: objeto AuditoriaGrupo do grupo origem
        auditoria_destino: objeto AuditoriaGrupo do grupo destino
        """
        self.origem = auditoria_origem
        self.destino = auditoria_destino
        
        # Resultados
        self.midias_pendentes = []
        self.estatisticas = {}
    
    def comparar(self):
        """
        Realiza a comparação híbrida:
        1. Primeiro verifica por file_unique_id (detecta duplicatas manuais)
        2. Depois verifica por signature (fallback)
        """
        print_section_header("Comparando Origem vs Destino")
        
        origem_id = self.origem.grupo_id
        destino_id = self.destino.grupo_id
        
        print_info("🔍 Carregando identificadores do destino...")
        
        # Carregar file_unique_ids existentes no destino (para detectar duplicatas manuais)
        destino_file_ids = db.get_existing_file_unique_ids(destino_id)
        print_info(f"   {len(destino_file_ids):,} file_unique_ids no destino")
        
        # Carregar signatures existentes no destino (fallback)
        destino_signatures = db.get_existing_signatures(destino_id)
        print_info(f"   {len(destino_signatures):,} signatures no destino")
        
        print_info("🔄 Comparando mídias da origem...")
        
        # Query para pegar todas as mídias da origem
        cursor = db.conn.cursor()
        cursor.execute('''
            SELECT message_id, file_unique_id, signature 
            FROM media_log 
            WHERE channel_id = ?
            ORDER BY message_id
        ''', (origem_id,))
        
        pendentes_ids = []
        duplicadas_por_file_id = 0
        duplicadas_por_signature = 0
        sem_identificador = 0
        
        for row in cursor.fetchall():
            msg_id = row['message_id']
            file_id = row['file_unique_id']
            signature = row['signature']
            
            # Verificação 1: Por file_unique_id (mais confiável)
            if file_id and file_id in destino_file_ids:
                duplicadas_por_file_id += 1
                continue  # Já existe no destino
            
            # Verificação 2: Por signature (fallback)
            if signature and signature in destino_signatures:
                duplicadas_por_signature += 1
                continue  # Já existe no destino
            
            # Se não tem nenhum identificador, considerar como pendente
            if not file_id and not signature:
                sem_identificador += 1
            
            # Mídia não encontrada no destino - adicionar à lista de pendentes
            pendentes_ids.append(msg_id)
        
        self.midias_pendentes = sorted(pendentes_ids)
        
        # Estatísticas
        total_origem = db.count_media(origem_id)
        total_destino = db.count_media(destino_id)
        ja_copiadas = total_origem - len(self.midias_pendentes)
        
        self.estatisticas = {
            'total_origem': total_origem,
            'total_destino': total_destino,
            'ja_copiadas': ja_copiadas,
            'duplicadas_por_file_id': duplicadas_por_file_id,
            'duplicadas_por_signature': duplicadas_por_signature,
            'sem_identificador': sem_identificador,
            'pendentes': len(self.midias_pendentes),
            'percentual_completo': (ja_copiadas / total_origem * 100) if total_origem > 0 else 0
        }
        
        self._exibir_resultados()
        
        return self.midias_pendentes
    
    def _exibir_resultados(self):
        """Exibe um resumo visual da comparação."""
        print("\n" + "="*60)
        print_section_header("Resultado da Comparação")
        print("="*60 + "\n")
        
        print(f"📊 {self.origem.nome_grupo} (ORIGEM)")
        print(f"   Total de mídias: {self.estatisticas['total_origem']:,}")
        print()
        
        print(f"📊 {self.destino.nome_grupo} (DESTINO)")
        print(f"   Total de mídias: {self.estatisticas['total_destino']:,}")
        print()
        
        print_success(f"✅ Mídias já copiadas: {self.estatisticas['ja_copiadas']:,}")
        
        # Detalhes da detecção
        if self.estatisticas['duplicadas_por_file_id'] > 0:
            print_info(f"   └─ Detectadas por file_id: {self.estatisticas['duplicadas_por_file_id']:,} (inclui manuais)")
        if self.estatisticas['duplicadas_por_signature'] > 0:
            print_info(f"   └─ Detectadas por signature: {self.estatisticas['duplicadas_por_signature']:,}")
        
        if self.estatisticas['pendentes'] > 0:
            print_warning(f"❌ Mídias pendentes: {self.estatisticas['pendentes']:,}")
            if self.estatisticas['sem_identificador'] > 0:
                print_warning(f"   └─ Sem identificador: {self.estatisticas['sem_identificador']:,} (podem gerar duplicatas)")
        else:
            print_success("🎉 TODAS as mídias já foram copiadas!")
        
        print()
        print(f"📈 Progresso: {self.estatisticas['percentual_completo']:.2f}% completo")
        
        total_barras = 50
        barras_completas = int(total_barras * self.estatisticas['percentual_completo'] / 100)
        barra = "█" * barras_completas + "░" * (total_barras - barras_completas)
        print(f"   [{barra}]")
        print()
    
    def salvar_lista_pendentes(self, task_key):
        """Salva a lista como parte do progresso (compatibilidade)."""
        # A lista é gerenciada pelo copiador_inteligente
        return True

    @staticmethod
    def carregar_lista_pendentes(task_key):
        """Método deprecado - progresso carrega do DB."""
        return []
