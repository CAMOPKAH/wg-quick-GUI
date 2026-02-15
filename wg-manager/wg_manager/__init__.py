"""
Пакет WireGuard Manager
"""

from .core import WireGuardManager, ProfileStatus, ProfileInfo, get_manager
from .logger import setup_logging, get_logger, Timer, export_logs
from .ui import WireGuardManagerApp

__version__ = '1.0.0'
__all__ = [
    'WireGuardManager',
    'ProfileStatus',
    'ProfileInfo',
    'get_manager',
    'setup_logging',
    'get_logger',
    'Timer',
    'export_logs',
    'WireGuardManagerApp'
]