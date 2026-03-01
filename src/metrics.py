# metrics.py
# [S12] Sistema de Métricas de Performance

import time
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field

from .database import db
from .logger import get_logger

logger = get_logger()


@dataclass
class OperationMetric:
    """Armazena métricas de uma operação."""
    name: str
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    success: bool = True
    items_processed: int = 0
    errors: int = 0
    
    @property
    def duration(self) -> float:
        """Duração em segundos."""
        if self.end_time:
            return self.end_time - self.start_time
        return time.time() - self.start_time
    
    @property
    def items_per_second(self) -> float:
        """Taxa de processamento."""
        if self.duration > 0:
            return self.items_processed / self.duration
        return 0.0
    
    def complete(self, success: bool = True):
        """Marca operação como concluída."""
        self.end_time = time.time()
        self.success = success


class MetricsCollector:
    """
    Coletor de métricas de performance.
    Armazena estatísticas sobre operações do programa.
    """
    
    def __init__(self):
        self._operations: Dict[str, List[OperationMetric]] = {}
        self._session_start = time.time()
        
        # Contadores de sessão
        self.session_midias_copiadas = 0
        self.session_erros = 0
        self.session_grupos_auditados = 0
    
    def start_operation(self, name: str) -> OperationMetric:
        """
        Inicia o tracking de uma operação.
        
        Args:
            name: Nome da operação (ex: 'copiar_midia', 'auditar_grupo')
            
        Returns:
            Objeto OperationMetric para atualização
        """
        metric = OperationMetric(name=name)
        
        if name not in self._operations:
            self._operations[name] = []
        
        self._operations[name].append(metric)
        return metric
    
    def record_success(self, operation_name: str, items: int = 1):
        """Registra sucesso em operação."""
        if operation_name == 'copiar_midia':
            self.session_midias_copiadas += items
        elif operation_name == 'auditar_grupo':
            self.session_grupos_auditados += 1
    
    def record_error(self, operation_name: str, error: str = None):
        """Registra erro em operação."""
        self.session_erros += 1
        logger.warning(f"Erro registrado em {operation_name}: {error}")
    
    def get_operation_stats(self, operation_name: str) -> Dict[str, Any]:
        """
        Retorna estatísticas de uma operação.
        """
        ops = self._operations.get(operation_name, [])
        
        if not ops:
            return {
                'count': 0,
                'success_rate': 100.0,
                'avg_duration': 0,
                'items_per_second': 0,
            }
        
        completed = [op for op in ops if op.end_time]
        successful = [op for op in completed if op.success]
        
        total_items = sum(op.items_processed for op in completed)
        total_duration = sum(op.duration for op in completed)
        
        return {
            'count': len(ops),
            'completed': len(completed),
            'success': len(successful),
            'success_rate': (len(successful) / len(completed) * 100) if completed else 100.0,
            'avg_duration': total_duration / len(completed) if completed else 0,
            'total_items': total_items,
            'items_per_second': total_items / total_duration if total_duration > 0 else 0,
        }
    
    def get_session_summary(self) -> Dict[str, Any]:
        """
        Retorna resumo da sessão atual.
        """
        session_duration = time.time() - self._session_start
        
        return {
            'session_duration_seconds': session_duration,
            'session_duration_formatted': str(timedelta(seconds=int(session_duration))),
            'midias_copiadas': self.session_midias_copiadas,
            'grupos_auditados': self.session_grupos_auditados,
            'erros': self.session_erros,
            'midias_por_minuto': (self.session_midias_copiadas / (session_duration / 60)) if session_duration > 60 else 0,
        }
    
    def get_all_stats(self) -> Dict[str, Any]:
        """Retorna todas as estatísticas coletadas."""
        stats = {
            'session': self.get_session_summary(),
            'operations': {},
        }
        
        for op_name in self._operations:
            stats['operations'][op_name] = self.get_operation_stats(op_name)
        
        return stats


# Instância global
_metrics = MetricsCollector()


def get_metrics() -> MetricsCollector:
    """Retorna o coletor global de métricas."""
    return _metrics


def save_metrics_to_db():
    """
    Salva métricas da sessão no banco de dados.
    Útil para análise histórica.
    """
    summary = _metrics.get_session_summary()
    
    cursor = db.conn.cursor()
    
    # Criar tabela se não existir
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS session_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_date TIMESTAMP,
            duration_seconds REAL,
            midias_copiadas INTEGER,
            grupos_auditados INTEGER,
            erros INTEGER,
            midias_por_minuto REAL
        )
    ''')
    
    # Inserir métricas
    cursor.execute('''
        INSERT INTO session_metrics 
        (session_date, duration_seconds, midias_copiadas, grupos_auditados, erros, midias_por_minuto)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (
        datetime.now(),
        summary['session_duration_seconds'],
        summary['midias_copiadas'],
        summary['grupos_auditados'],
        summary['erros'],
        summary['midias_por_minuto']
    ))
    
    db.conn.commit()
    logger.info("Métricas da sessão salvas no banco de dados")


def get_historical_metrics(days: int = 7) -> List[Dict[str, Any]]:
    """
    Retorna métricas dos últimos N dias.
    """
    cursor = db.conn.cursor()
    
    try:
        cursor.execute('''
            SELECT * FROM session_metrics
            WHERE session_date >= datetime('now', ?)
            ORDER BY session_date DESC
        ''', (f'-{days} days',))
        
        return [dict(row) for row in cursor.fetchall()]
    except Exception:
        return []


def print_metrics_summary():
    """Exibe resumo de métricas no console."""
    from rich.table import Table
    from rich.console import Console
    
    console = Console()
    summary = _metrics.get_session_summary()
    
    table = Table(title="📊 Métricas da Sessão", border_style="blue")
    table.add_column("Métrica", style="cyan")
    table.add_column("Valor", style="green")
    
    table.add_row("⏱️ Tempo de sessão", summary['session_duration_formatted'])
    table.add_row("📦 Mídias copiadas", f"{summary['midias_copiadas']:,}")
    table.add_row("📁 Grupos auditados", str(summary['grupos_auditados']))
    table.add_row("❌ Erros", str(summary['erros']))
    table.add_row("⚡ Velocidade média", f"{summary['midias_por_minuto']:.1f}/min")
    
    console.print(table)
