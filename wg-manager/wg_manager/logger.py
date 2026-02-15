"""
Профессиональная система логирования для WireGuard Manager
Поддерживает ротацию, цветной вывод в консоль, раздельные файлы логов
"""

import os
import sys
import logging
import logging.handlers
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any


class ColoredFormatter(logging.Formatter):
    """Форматировщик логов с цветами для консоли"""
    
    COLORS = {
        'DEBUG': '\033[36m',     # Cyan
        'INFO': '\033[32m',      # Green
        'WARNING': '\033[33m',   # Yellow
        'ERROR': '\033[31m',     # Red
        'CRITICAL': '\033[41m',  # Red background
    }
    RESET = '\033[0m'
    
    def format(self, record: logging.LogRecord) -> str:
        """Форматирует запись лога с цветами для консоли"""
        # Создаем базовую форматированную строку
        formatted = super().format(record)
        
        # Добавляем цвета только если вывод в консоль
        if sys.stderr.isatty() and getattr(record, 'use_color', False):
            level_color = self.COLORS.get(record.levelname, '')
            return f"{level_color}{formatted}{self.RESET}"
        return formatted


class ContextFilter(logging.Filter):
    """Фильтр для добавления контекстной информации в логи"""
    
    def filter(self, record: logging.LogRecord) -> bool:
        # Добавляем информацию о пользователе и хосте
        record.user = os.environ.get('USER', 'unknown')
        record.hostname = os.uname().nodename if hasattr(os, 'uname') else 'unknown'
        
        # Добавляем время выполнения (будет установлено позже)
        if not hasattr(record, 'execution_time'):
            record.execution_time = ''
        
        return True


def setup_logging(
    level: str = 'INFO',
    console: bool = True,
    log_dir: Optional[str] = None
) -> None:
    """
    Настройка системы логирования
    
    Args:
        level: Уровень логирования (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        console: Включить вывод в консоль
        log_dir: Директория для логов (по умолчанию ~/.local/share/wg-manager/)
    """
    log_dir_path: Path
    if log_dir is None:
        log_dir_path = Path.home() / '.local' / 'share' / 'wg-manager'
    else:
        log_dir_path = Path(log_dir)
    
    log_dir_path.mkdir(parents=True, exist_ok=True)
    
    # Основной файл логов
    main_log = log_dir_path / 'wg-manager.log'
    # Файл ошибок
    error_log = log_dir_path / 'errors.log'
    
    # Настраиваем корневой логгер
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level))
    
    # Очищаем существующие обработчики
    root_logger.handlers.clear()
    
    # Добавляем фильтр контекста
    context_filter = ContextFilter()
    root_logger.addFilter(context_filter)
    
    # Форматтеры
    file_formatter = logging.Formatter(
        '[%(asctime)s] [%(levelname)s] [%(module)s:%(lineno)d] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    console_formatter = ColoredFormatter(
        '[%(asctime)s] [%(levelname)s] [%(module)s:%(lineno)d] %(message)s',
        datefmt='%H:%M:%S'
    )
    
    # Обработчик для основного файла логов (ротация по размеру и времени)
    main_handler = logging.handlers.RotatingFileHandler(
        main_log,
        maxBytes=10 * 1024 * 1024,  # 10 МБ
        backupCount=7,              # 7 дней (файлов)
        encoding='utf-8'
    )
    main_handler.setLevel(getattr(logging, level))
    main_handler.setFormatter(file_formatter)
    main_handler.addFilter(lambda record: record.levelno < logging.ERROR)
    root_logger.addHandler(main_handler)
    
    # Обработчик для ошибок (только ERROR и CRITICAL)
    error_handler = logging.handlers.RotatingFileHandler(
        error_log,
        maxBytes=5 * 1024 * 1024,   # 5 МБ
        backupCount=30,             # 30 дней
        encoding='utf-8'
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(file_formatter)
    root_logger.addHandler(error_handler)
    
    # Обработчик для консоли (только если console=True)
    if console:
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(getattr(logging, level))
        console_handler.setFormatter(console_formatter)
        
        # Добавляем атрибут use_color для цветного вывода
        def add_color_attribute(record):
            record.use_color = True
            return True
        
        console_handler.addFilter(add_color_attribute)
        root_logger.addHandler(console_handler)
    
    # Логирование информации о запуске
    logger = get_logger(__name__)
    logger.info('=' * 60)
    logger.info(f'Настройка логирования завершена (уровень: {level})')
    logger.info(f'Основной лог: {main_log}')
    logger.info(f'Лог ошибок: {error_log}')
    logger.info('=' * 60)


def get_logger(name: str) -> logging.Logger:
    """
    Получить логгер с заданным именем
    
    Args:
        name: Имя логгера (обычно __name__)
    
    Returns:
        Настроенный логгер
    """
    return logging.getLogger(name)


class Timer:
    """Контекстный менеджер для измерения времени выполнения"""
    
    def __init__(self, operation: str, logger: Optional[logging.Logger] = None):
        self.operation = operation
        self.logger = logger or get_logger(__name__)
        self.start_time: Optional[datetime] = None
    
    def __enter__(self):
        self.start_time = datetime.now()
        self.logger.debug(f'Начало операции: {self.operation}')
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.start_time:
            elapsed = (datetime.now() - self.start_time).total_seconds() * 1000
            if exc_type is None:
                self.logger.debug(f'Операция завершена: {self.operation} ({elapsed:.2f} мс)')
            else:
                self.logger.error(
                    f'Операция завершена с ошибкой: {self.operation} '
                    f'({elapsed:.2f} мс): {exc_val}'
                )
    
    def get_elapsed_ms(self) -> float:
        """Получить прошедшее время в миллисекундах"""
        if not self.start_time:
            return 0.0
        return (datetime.now() - self.start_time).total_seconds() * 1000


def export_logs(output_path: str, lines: int = 1000) -> bool:
    """
    Экспортировать последние записи логов в файл
    
    Args:
        output_path: Путь для сохранения логов
        lines: Количество строк для экспорта
    
    Returns:
        True если успешно, False в случае ошибки
    """
    try:
        log_dir = Path.home() / '.local' / 'share' / 'wg-manager'
        main_log = log_dir / 'wg-manager.log'
        
        if not main_log.exists():
            return False
        
        # Читаем последние строки из лога
        with open(main_log, 'r', encoding='utf-8') as f:
            all_lines = f.readlines()
        
        last_lines = all_lines[-lines:] if len(all_lines) > lines else all_lines
        
        # Записываем в выходной файл
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(f'Экспорт логов WireGuard Manager\n')
            f.write(f'Время экспорта: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n')
            f.write(f'Всего строк в логе: {len(all_lines)}\n')
            f.write(f'Экспортировано строк: {len(last_lines)}\n')
            f.write('=' * 80 + '\n')
            f.writelines(last_lines)
        
        logger = get_logger(__name__)
        logger.info(f'Логи экспортированы в {output_path} ({len(last_lines)} строк)')
        return True
    except Exception as e:
        logger = get_logger(__name__)
        logger.error(f'Ошибка при экспорте логов: {e}')
        return False


# Инициализация модуля
__all__ = ['setup_logging', 'get_logger', 'Timer', 'export_logs']