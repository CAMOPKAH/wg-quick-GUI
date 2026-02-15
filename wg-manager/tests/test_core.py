"""
Тесты бизнес-логики WireGuard Manager
"""

import pytest
import sys
import os
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path

# Добавляем путь к модулям
sys.path.insert(0, str(Path(__file__).parent.parent))

from wg_manager.core import (
    WireGuardManager,
    ProfileStatus,
    ProfileInfo,
    get_manager
)


class TestWireGuardManager:
    """Тесты класса WireGuardManager"""
    
    def setup_method(self):
        """Настройка перед каждым тестом"""
        # Мокаем subprocess.run
        self.subprocess_patcher = patch('wg_manager.core.subprocess.run')
        self.mock_subprocess_run = self.subprocess_patcher.start()
        
        # Мокаем Path.exists для конфигурационных файлов
        self.path_patcher = patch('wg_manager.core.Path')
        self.mock_path = self.path_patcher.start()
        
        # Настраиваем мок для конфигурационных файлов
        self.mock_config_dir = Mock()
        self.mock_path.return_value = self.mock_config_dir
        self.mock_config_dir.exists.return_value = True
        # Добавляем магические методы для Path
        self.mock_config_dir.__truediv__ = Mock(return_value=self.mock_config_dir)
        
        # Мокаем logger
        self.logger_patcher = patch('wg_manager.core.get_logger')
        self.mock_logger = self.logger_patcher.start()
        self.mock_logger_instance = Mock()
        self.mock_logger.return_value = self.mock_logger_instance
        
        # Создаем менеджер после моков, чтобы Path был замокан
        self.manager = WireGuardManager()
        
        # Мокаем _run_command_with_retry, чтобы использовать уже замоканный _run_command
        self.retry_patcher = patch.object(self.manager, '_run_command_with_retry')
        self.mock_run_command_with_retry = self.retry_patcher.start()
        # По умолчанию перенаправляем вызовы в _run_command
        self.mock_run_command_with_retry.side_effect = self.manager._run_command
    
    def teardown_method(self):
        """Очистка после каждого теста"""
        self.subprocess_patcher.stop()
        self.path_patcher.stop()
        self.logger_patcher.stop()
        if hasattr(self, 'retry_patcher'):
            self.retry_patcher.stop()
    
    def test_check_profile_exists_true(self):
        """Тест проверки существования профиля (существует)"""
        self.mock_config_dir.exists.return_value = True
        
        # Используем нестандартный профиль, чтобы проверить вызов exists
        result = self.manager.check_profile_exists('NonExistentProfile')
        
        assert result is True
        self.mock_config_dir.exists.assert_called_once()
    
    def test_check_profile_exists_false(self):
        """Тест проверки существования профиля (не существует)"""
        self.mock_config_dir.exists.return_value = False
        
        result = self.manager.check_profile_exists('NonExistent')
        
        assert result is False
        self.mock_config_dir.exists.assert_called_once()
    
    def test_validate_profile_valid(self):
        """Тест валидации корректного профиля"""
        self.mock_config_dir.exists.return_value = True
        self.mock_config_dir.read_text.return_value = '[Interface]\nPrivateKey = xxx'
        
        valid, message = self.manager.validate_profile('App')
        
        assert valid is True
        assert message == 'OK'
        self.mock_config_dir.read_text.assert_called_once_with(encoding='utf-8')
    
    def test_validate_profile_not_exists(self):
        """Тест валидации несуществующего профиля"""
        self.mock_config_dir.exists.return_value = False
        
        valid, message = self.manager.validate_profile('NonExistent')
        
        assert valid is False
        assert 'не существует' in message
    
    def test_validate_profile_invalid_config(self):
        """Тест валидации профиля с некорректной конфигурацией"""
        self.mock_config_dir.exists.return_value = True
        self.mock_config_dir.read_text.return_value = 'Invalid config'
        
        valid, message = self.manager.validate_profile('App')
        
        assert valid is False
        assert 'Отсутствует секция' in message
    
    def test_get_active_profile_success(self):
        """Тест получения активного профиля (успех)"""
        # Мокаем _run_command_with_retry для возврата вывода wg show
        with patch.object(self.manager, '_run_command_with_retry') as mock_run:
            mock_run.return_value = (True, 'interface: wg0\npublic key: xxx')
            
            result = self.manager.get_active_profile()
            
            assert result is None  # Не соответствует именам профилей
            
            mock_run.assert_called_once_with(
                ['wg', 'show'],
                timeout=self.manager.timeout_wg_show
            )
    
    def test_get_active_profile_with_matching_interface(self):
        """Тест получения активного профиля с совпадающим именем интерфейса"""
        with patch.object(self.manager, '_run_command_with_retry') as mock_run:
            mock_run.return_value = (True, 'interface: wg-bombox\npublic key: xxx')
            
            result = self.manager.get_active_profile()
            
            assert result == 'bomBox'
    
    def test_get_active_profile_failure(self):
        """Тест получения активного профиля (ошибка)"""
        with patch.object(self.manager, '_run_command_with_retry') as mock_run:
            mock_run.return_value = (False, 'Ошибка выполнения')
            
            result = self.manager.get_active_profile()
            
            assert result is None
            self.mock_logger_instance.warning.assert_called()
    
    def test_get_profile_status_active(self):
        """Тест получения статуса профиля (активен)"""
        with patch.object(self.manager, 'get_active_profile') as mock_active:
            mock_active.return_value = 'App'
            self.mock_config_dir.exists.return_value = True
            
            status = self.manager.get_profile_status('App')
            
            assert status == ProfileStatus.ACTIVE
    
    def test_get_profile_status_inactive(self):
        """Тест получения статуса профиля (неактивен)"""
        with patch.object(self.manager, 'get_active_profile') as mock_active:
            mock_active.return_value = 'bomBox'
            self.mock_config_dir.exists.return_value = True
            
            status = self.manager.get_profile_status('App')
            
            assert status == ProfileStatus.INACTIVE
    
    def test_get_profile_status_error(self):
        """Тест получения статуса профиля (ошибка)"""
        with patch.object(self.manager, 'get_active_profile') as mock_active:
            mock_active.return_value = None
            self.mock_config_dir.exists.return_value = False
            
            status = self.manager.get_profile_status('NonExistent')
            
            assert status == ProfileStatus.ERROR
    
    def test_turn_off_all_success(self):
        """Тест отключения всех профилей (успех)"""
        with patch.object(self.manager, '_deactivate_profile') as mock_deactivate:
            mock_deactivate.return_value = (True, 'Success')
            
            success, message = self.manager.turn_off_all()
            
            assert success is True
            assert 'Все профили отключены' in message
            assert mock_deactivate.call_count == 3
    
    def test_turn_off_all_partial_failure(self):
        """Тест отключения всех профилей (частичный сбой)"""
        with patch.object(self.manager, '_deactivate_profile') as mock_deactivate:
            mock_deactivate.side_effect = [
                (True, 'Success'),
                (False, 'Ошибка'),
                (True, 'Success')
            ]
            
            success, message = self.manager.turn_off_all()
            
            assert success is False
            assert 'Ошибки при отключении' in message
    
    def test_activate_profile_already_active(self):
        """Тест активации уже активного профиля"""
        with patch.object(self.manager, 'check_profile_exists') as mock_exists, \
             patch.object(self.manager, 'validate_profile') as mock_validate, \
             patch.object(self.manager, 'get_profile_status') as mock_status:
            
            mock_exists.return_value = True
            mock_validate.return_value = (True, 'OK')
            mock_status.return_value = ProfileStatus.ACTIVE
            
            success, message = self.manager.activate_profile('App')
            
            assert success is True
            assert 'уже активен' in message
            self.mock_logger_instance.warning.assert_called()
    
    def test_activate_profile_success(self):
        """Тест успешной активации профиля"""
        with patch.object(self.manager, 'check_profile_exists') as mock_exists, \
             patch.object(self.manager, 'validate_profile') as mock_validate, \
             patch.object(self.manager, 'get_profile_status') as mock_status, \
             patch.object(self.manager, '_deactivate_profile') as mock_deactivate, \
             patch.object(self.manager, '_activate_profile') as mock_activate:
            
            mock_exists.return_value = True
            mock_validate.return_value = (True, 'OK')
            mock_status.side_effect = [ProfileStatus.INACTIVE, ProfileStatus.INACTIVE, ProfileStatus.INACTIVE]
            mock_deactivate.return_value = (True, 'Success')
            mock_activate.return_value = (True, 'Success')
            
            success, message = self.manager.activate_profile('App')
            
            assert success is True
            assert 'успешно активирован' in message or 'Success' in message
    
    def test_activate_profile_nonexistent(self):
        """Тест активации несуществующего профиля"""
        with patch.object(self.manager, 'check_profile_exists') as mock_exists:
            mock_exists.return_value = False
            
            success, message = self.manager.activate_profile('NonExistent')
            
            assert success is False
            assert 'не существует' in message
    
    def test_parse_transfer_bytes(self):
        """Тест парсинга размера передачи (байты)"""
        result = self.manager._parse_transfer('123')
        assert result == 123
    
    def test_parse_transfer_kib(self):
        """Тест парсинга размера передачи (KiB)"""
        result = self.manager._parse_transfer('1.5 KiB')
        assert result == int(1.5 * 1024)
    
    def test_parse_transfer_mib(self):
        """Тест парсинга размера передачи (MiB)"""
        result = self.manager._parse_transfer('2.3 MiB')
        assert result == int(2.3 * 1024 * 1024)
    
    def test_parse_transfer_gib(self):
        """Тест парсинга размера передачи (GiB)"""
        result = self.manager._parse_transfer('0.5 GiB')
        assert result == int(0.5 * 1024 * 1024 * 1024)
    
    def test_parse_transfer_invalid(self):
        """Тест парсинга некорректного размера передачи"""
        result = self.manager._parse_transfer('invalid')
        assert result == 0
    
    def test_run_command_success(self):
        """Тест выполнения команды (успех)"""
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = 'Output'
        mock_result.stderr = ''
        
        self.mock_subprocess_run.return_value = mock_result
        
        with patch('wg_manager.core.time.time', side_effect=[0, 1]):
            success, output = self.manager._run_command(['test', 'command'])
            
            assert success is True
            assert output == 'Output'
            self.mock_subprocess_run.assert_called_once()
    
    def test_run_command_failure(self):
        """Тест выполнения команды (ошибка)"""
        mock_result = Mock()
        mock_result.returncode = 1
        mock_result.stdout = ''
        mock_result.stderr = 'Error message'
        
        self.mock_subprocess_run.return_value = mock_result
        
        success, output = self.manager._run_command(['test', 'command'])
        
        assert success is False
        assert output == 'Error message'
    
    def test_run_command_timeout(self):
        """Тест выполнения команды (таймаут)"""
        import subprocess
        self.mock_subprocess_run.side_effect = subprocess.TimeoutExpired(cmd=['test', 'command'], timeout=30)
        
        success, output = self.manager._run_command(['test', 'command'])
        
        assert success is False
        assert 'Таймаут' in output
    
    def test_run_command_exception(self):
        """Тест выполнения команды (исключение)"""
        self.mock_subprocess_run.side_effect = Exception('Unexpected error')
        
        success, output = self.manager._run_command(['test', 'command'])
        
        assert success is False
        assert 'Unexpected error' in output


class TestProfileStatus:
    """Тесты перечисления ProfileStatus"""
    
    def test_status_values(self):
        """Тест значений перечисления"""
        assert ProfileStatus.ACTIVE.value == 'active'
        assert ProfileStatus.INACTIVE.value == 'inactive'
        assert ProfileStatus.ERROR.value == 'error'
        assert ProfileStatus.UNKNOWN.value == 'unknown'


class TestProfileInfo:
    """Тесты класса ProfileInfo"""
    
    def test_profile_info_creation(self):
        """Тест создания объекта ProfileInfo"""
        info = ProfileInfo(
            name='Test',
            status=ProfileStatus.ACTIVE,
            config_path=Path('/test.conf')
        )
        
        assert info.name == 'Test'
        assert info.status == ProfileStatus.ACTIVE
        assert info.config_path == Path('/test.conf')
        assert info.transfer_rx == 0
        assert info.transfer_tx == 0


class TestGetManager:
    """Тесты функции get_manager"""
    
    def test_get_manager_singleton(self):
        """Тест получения синглтона менеджера"""
        manager1 = get_manager()
        manager2 = get_manager()
        
        assert manager1 is manager2
    
    def test_get_manager_reset(self):
        """Тест сброса синглтона (для изоляции тестов)"""
        import wg_manager.core
        
        # Сбрасываем синглтон
        wg_manager.core._manager_instance = None
        
        manager = get_manager()
        assert manager is not None
        
        # Проверяем, что следующий вызов возвращает тот же объект
        same_manager = get_manager()
        assert manager is same_manager