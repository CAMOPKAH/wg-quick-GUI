#!/usr/bin/env python3
"""
Главный файл приложения WireGuard Manager
Запускает GUI для управления профилями WireGuard
"""

import sys
import os
import argparse
import traceback
import signal
import threading
from pathlib import Path

# Добавляем путь к модулям приложения
sys.path.insert(0, str(Path(__file__).parent))

from wg_manager.logger import setup_logging, get_logger
from wg_manager.ui import WireGuardManagerApp


def setup_global_exception_handler(logger):
    """Установка глобального обработчика неперехваченных исключений"""
    def exception_handler(exc_type, exc_value, exc_traceback):
        # Игнорируем KeyboardInterrupt
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        
        logger.critical(
            "Неперехваченное исключение:",
            exc_info=(exc_type, exc_value, exc_traceback)
        )
        
        # Также выводим в stderr для отладки
        sys.stderr.write("Критическая ошибка! Подробности в логах.\n")
        traceback.print_exception(exc_type, exc_value, exc_traceback, file=sys.stderr)
    
    sys.excepthook = exception_handler


def setup_signal_handlers(logger):
    """Обработка сигналов для корректного завершения"""
    def signal_handler(signum, frame):
        logger.info(f"Получен сигнал {signum}, завершение приложения...")
        sys.exit(0)
    
    try:
        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)
    except Exception as e:
        logger.warning(f"Не удалось установить обработчики сигналов: {e}")


def setup_thread_exception_handler(logger):
    """Обработка неперехваченных исключений в потоках"""
    if hasattr(threading, 'excepthook'):
        original_hook = threading.excepthook
        
        def thread_exception_handler(args):
            # Логируем исключение
            logger.error(
                f"Неперехваченное исключение в потоке {args.thread.name}:",
                exc_info=(args.exc_type, args.exc_value, args.exc_traceback)
            )
            # Вызываем оригинальный обработчик
            original_hook(args)
        
        threading.excepthook = thread_exception_handler
        logger.debug("Обработчик исключений потоков установлен")
    else:
        logger.debug("threading.excepthook не доступен (требуется Python 3.8+)")


def parse_arguments():
    parser = argparse.ArgumentParser(description='WireGuard Profile Manager')
    parser.add_argument('--debug', action='store_true',
                       help='Включить режим отладки (уровень логов DEBUG)')
    parser.add_argument('--log-level',
                       choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
                       default='INFO',
                       help='Уровень логирования (по умолчанию: INFO)')
    parser.add_argument('--no-gui', action='store_true',
                       help='Запуск без GUI (для CI/тестирования)')
    return parser.parse_args()


def main():
    args = parse_arguments()
    
    # Настройка логирования
    log_level = 'DEBUG' if args.debug else args.log_level
    setup_logging(level=log_level, console=not args.no_gui)
    logger = get_logger(__name__)
    
    # Настройка глобальной обработки ошибок
    setup_global_exception_handler(logger)
    setup_signal_handlers(logger)
    setup_thread_exception_handler(logger)
    
    logger.info(f'Запуск WireGuard Manager (GUI: {not args.no_gui})')
    logger.debug(f'Аргументы командной строки: {sys.argv}')
    
    if args.no_gui:
        # Режим без GUI - можно использовать для CI
        logger.info('Режим без GUI активирован')
        # Здесь можно добавить CLI функционал при необходимости
        print('WireGuard Manager в режиме без GUI')
        print('Используйте --help для справки')
        return 0
    
    try:
        # Запуск GTK приложения
        import gi
        gi.require_version('Gtk', '3.0')
        from gi.repository import Gtk
        
        app = WireGuardManagerApp()
        exit_code = app.run(sys.argv)
        logger.info(f'Приложение завершено с кодом {exit_code}')
        return exit_code
    except ImportError as e:
        logger.critical(f'Ошибка импорта GTK: {e}')
        print('Ошибка: не удалось импортировать GTK. Установите python3-gi')
        print('sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0')
        return 1
    except Exception as e:
        logger.critical(f'Неожиданная ошибка: {e}', exc_info=True)
        print(f'Критическая ошибка: {e}')
        return 1


if __name__ == '__main__':
    sys.exit(main())