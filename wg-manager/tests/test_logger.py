"""
Тесты системы логирования
"""

import pytest
import sys
import os
import logging
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

# Добавляем путь к модулям
sys.path.insert(0, str(Path(__file__).parent.parent))

from wg_manager.logger import (
    setup_logging,
    get_logger,
    Timer,
    export_logs,
    ColoredFormatter,
    ContextFilter
)


class TestColoredFormatter:
    """Тесты форматировщика с цветами"""
    
    def test_format_with_color(self):
        """Тест форматирования с цветами"""
        formatter = ColoredFormatter('%(message)s')
        
        record = logging.LogRecord(
            name='test',
            level=logging.INFO,
            pathname='test.py',
            lineno=1,
            msg='Test message',
            args=(),
            exc_info=None
        )
        
        # Добавляем атрибут use_color
        record.use_color = True
        
        formatted = formatter.format(record)
        
        # Проверяем, что форматирование работает
        assert 'Test message' in formatted
    
    def test_format_without_color(self):
        """Тест форматирования без цветов"""
        formatter = ColoredFormatter('%(message)s')
        
        record = logging.LogRecord(
            name='test',
            level=logging.INFO,
            pathname='test.py',
            lineno=1,
            msg='Test message',
            args=(),
            exc_info=None
        )
        
        # Нет атрибута use_color
        formatted = formatter.format(record)
        
        assert formatted == 'Test message'


class TestContextFilter:
    """Тесты фильтра контекста"""
    
    def test_filter_adds_context(self):
        """Тест добавления контекстной информации"""
        filter_obj = ContextFilter()
        
        record = logging.LogRecord(
            name='test',
            level=logging.INFO,
            pathname='test.py',
            lineno=1,
            msg='Test message',
            args=(),
            exc_info=None
        )
        
        result = filter_obj.filter(record)
        
        assert result is True
        assert hasattr(record, 'user')
        assert hasattr(record, 'hostname')
        assert hasattr(record, 'execution_time')


class TestSetupLogging:
    """Тесты настройки логирования"""
    
    def setup_method(self):
        """Настройка перед каждым тестом"""
        self.temp_dir = tempfile.mkdtemp()
        
        # Мокаем Path.home()
        self.home_patcher = patch('wg_manager.logger.Path.home')
        self.mock_home = self.home_patcher.start()
        self.mock_home.return_value = Path(self.temp_dir)
        
        # Мокаем logging.handlers.RotatingFileHandler
        self.handler_patcher = patch('wg_manager.logger.logging.handlers.RotatingFileHandler')
        self.mock_handler_class = self.handler_patcher.start()
        self.mock_handler = Mock()
        self.mock_handler_class.return_value = self.mock_handler
    
    def teardown_method(self):
        """Очистка после каждого теста"""
        self.home_patcher.stop()
        self.handler_patcher.stop()
        
        # Очищаем временную директорию
        import shutil
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
    
    def test_setup_logging_creates_directory(self):
        """Тест создания директории для логов"""
        with patch('wg_manager.logger.Path.mkdir') as mock_mkdir:
            setup_logging(log_dir=self.temp_dir, console=False)
            
            mock_mkdir.assert_called_once_with(parents=True, exist_ok=True)
    
    def test_setup_logging_configures_handlers(self):
        """Тест настройки обработчиков логирования"""
        with patch('wg_manager.logger.logging.getLogger') as mock_get_logger:
            mock_logger = Mock()
            mock_get_logger.return_value = mock_logger
            
            setup_logging(log_dir=self.temp_dir, console=False)
            
            # Проверяем, что обработчики были добавлены
            assert mock_logger.handlers.clear.called
            assert mock_logger.addFilter.called
            assert mock_logger.addHandler.call_count >= 2
    
    def test_setup_logging_with_console(self):
        """Тест настройки логирования с выводом в консоль"""
        with patch('wg_manager.logger.logging.getLogger') as mock_get_logger, \
             patch('wg_manager.logger.logging.StreamHandler') as mock_stream_handler:
            
            mock_logger = Mock()
            mock_get_logger.return_value = mock_logger
            mock_stream_handler.return_value = Mock()
            
            setup_logging(log_dir=self.temp_dir, console=True)
            
            # Проверяем, что StreamHandler был добавлен
            mock_stream_handler.assert_called_once()
    
    def test_setup_logging_different_levels(self):
        """Тест настройки логирования с разными уровнями"""
        test_cases = [
            ('DEBUG', logging.DEBUG),
            ('INFO', logging.INFO),
            ('WARNING', logging.WARNING),
            ('ERROR', logging.ERROR),
            ('CRITICAL', logging.CRITICAL)
        ]
        
        for level_name, expected_level in test_cases:
            with patch('wg_manager.logger.logging.getLogger') as mock_get_logger:
                mock_logger = Mock()
                mock_get_logger.return_value = mock_logger
                
                setup_logging(level=level_name, log_dir=self.temp_dir, console=False)
                
                # Проверяем уровень логирования
                mock_logger.setLevel.assert_called_with(expected_level)


class TestGetLogger:
    """Тесты функции get_logger"""
    
    def test_get_logger_returns_logger(self):
        """Тест получения логгера"""
        logger = get_logger('test.module')
        
        assert isinstance(logger, logging.Logger)
        assert logger.name == 'test.module'


class TestTimer:
    """Тесты контекстного менеджера Timer"""
    
    def test_timer_context_manager(self):
        """Тест использования Timer как контекстного менеджера"""
        mock_logger = Mock()
        
        with Timer('test operation', mock_logger) as timer:
            assert timer.operation == 'test operation'
            assert timer.logger == mock_logger
            assert timer.start_time is not None
        
        # Проверяем, что логирование было вызвано
        assert mock_logger.debug.call_count >= 1
    
    def test_timer_with_exception(self):
        """Тест Timer с исключением внутри контекста"""
        mock_logger = Mock()
        
        try:
            with Timer('test operation', mock_logger):
                raise ValueError('Test error')
        except ValueError:
            pass
        
        # Проверяем, что было залогировано сообщение об ошибке
        mock_logger.error.assert_called()
    
    def test_get_elapsed_ms(self):
        """Тест получения прошедшего времени"""
        import time
        
        with Timer('test operation') as timer:
            time.sleep(0.01)  # 10 мс
            elapsed = timer.get_elapsed_ms()
            
            assert elapsed > 0
            assert elapsed < 100  # Должно быть меньше 100 мс


class TestExportLogs:
    """Тесты экспорта логов"""
    
    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        
        # Мокаем Path.home()
        self.home_patcher = patch('wg_manager.logger.Path.home')
        self.mock_home = self.home_patcher.start()
        self.mock_home.return_value = Path(self.temp_dir)
    
    def teardown_method(self):
        self.home_patcher.stop()
        
        import shutil
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
    
    def test_export_logs_success(self):
        """Тест успешного экспорта логов"""
        # Создаем тестовый файл логов
        log_dir = Path(self.temp_dir) / '.local' / 'share' / 'wg-manager'
        log_dir.mkdir(parents=True, exist_ok=True)
        
        log_file = log_dir / 'wg-manager.log'
        with open(log_file, 'w', encoding='utf-8') as f:
            for i in range(150):
                f.write(f'Test log line {i}\n')
        
        # Экспортируем логи
        output_file = Path(self.temp_dir) / 'export.log'
        success = export_logs(str(output_file), lines=100)
        
        assert success is True
        assert output_file.exists()
        
        # Проверяем содержимое
        with open(output_file, 'r', encoding='utf-8') as f:
            content = f.read()
            assert 'Экспорт логов' in content
            assert 'Test log line' in content
    
    def test_export_logs_file_not_exists(self):
        """Тест экспорта при отсутствии файла логов"""
        output_file = Path(self.temp_dir) / 'export.log'
        success = export_logs(str(output_file), lines=100)
        
        assert success is False
        assert not output_file.exists()
    
    def test_export_logs_io_error(self):
        """Тест экспорта с ошибкой ввода-вывода"""
        # Создаем файл логов
        log_dir = Path(self.temp_dir) / '.local' / 'share' / 'wg-manager'
        log_dir.mkdir(parents=True, exist_ok=True)
        
        log_file = log_dir / 'wg-manager.log'
        with open(log_file, 'w', encoding='utf-8') as f:
            f.write('Test log\n')
        
        # Мокаем open для вызова ошибки
        with patch('builtins.open', side_effect=IOError('Permission denied')):
            output_file = Path(self.temp_dir) / 'export.log'
            success = export_logs(str(output_file), lines=100)
            
            assert success is False


def test_logger_integration():
    """Интеграционный тест системы логирования"""
    import logging
    
    # Создаем временную директорию
    with tempfile.TemporaryDirectory() as temp_dir:
        # Настраиваем логирование
        setup_logging(level='DEBUG', log_dir=temp_dir, console=False)
        
        # Получаем логгер
        logger = get_logger('test.integration')
        
        # Записываем сообщения разных уровней
        logger.debug('Debug message')
        logger.info('Info message')
        logger.warning('Warning message')
        logger.error('Error message')
        logger.critical('Critical message')
        
        # Проверяем, что файлы созданы
        log_dir = Path(temp_dir)
        main_log = log_dir / 'wg-manager.log'
        error_log = log_dir / 'errors.log'
        
        assert main_log.exists()
        assert error_log.exists()
        
        # Проверяем содержимое основного лога
        with open(main_log, 'r', encoding='utf-8') as f:
            content = f.read()
            assert 'Debug message' in content
            assert 'Info message' in content
            assert 'Warning message' in content
        
        # Проверяем содержимое лога ошибок
        with open(error_log, 'r', encoding='utf-8') as f:
            content = f.read()
            assert 'Error message' in content
            assert 'Critical message' in content
            # Ошибки не должны содержать сообщения низких уровней
            assert 'Debug message' not in content
            assert 'Info message' not in content