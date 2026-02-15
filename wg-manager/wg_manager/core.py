"""
Бизнес-логика управления профилями WireGuard
Обеспечивает безопасное выполнение команд через PolicyKit
"""

import os
import subprocess
import time
import threading
import shutil
import json
from pathlib import Path
from typing import List, Tuple, Optional, Dict, Any
from dataclasses import dataclass
from enum import Enum

from .logger import get_logger, Timer


class ProfileStatus(Enum):
    """Статус профиля WireGuard"""
    ACTIVE = "active"
    INACTIVE = "inactive"
    ERROR = "error"
    UNKNOWN = "unknown"


@dataclass
class ProfileInfo:
    """Информация о профиле WireGuard"""
    name: str
    status: ProfileStatus
    config_path: Path
    interface_name: str = ""
    public_key: str = ""
    endpoint: str = ""
    transfer_rx: int = 0
    transfer_tx: int = 0
    last_handshake: str = ""


class WireGuardManager:
    """Менеджер профилей WireGuard"""
    
    def __init__(self):
        self.logger = get_logger(__name__)
        self._lock = threading.RLock()
        self._active_profile: Optional[str] = None
        self._profiles_cache: Dict[str, ProfileInfo] = {}
        
        # Конфигурационные пути
        self.config_dir = Path('/etc/wireguard')
        self.profiles = []  # Будет заполнено из конфигурации
        
        # Таймауты (в секундах)
        self.timeout_wg_quick = 60
        self.timeout_wg_show = 30
        
        # Параметры повторных попыток
        self.max_retries = 3
        self.retry_delay = 1.0  # секунды между попытками
        
        # Загрузка конфигурации
        self._load_config()
        
        # Если профили не заданы в конфигурации, используем значения по умолчанию
        if not self.profiles:
            self.profiles = ['App', 'bomBox', 'usa']
            self.logger.info(f'Используются профили по умолчанию: {self.profiles}')
    
    def _load_config(self):
        """Загрузить конфигурацию из файла"""
        config_path = Path.home() / '.local' / 'share' / 'wg-manager' / 'config.json'
        
        if not config_path.exists():
            self.logger.debug(f'Конфигурационный файл не найден: {config_path}')
            return
        
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            if 'profiles' in config and isinstance(config['profiles'], list):
                self.profiles = config['profiles']
                self.logger.info(f'Загружены профили из конфигурации: {self.profiles}')
            
            # Можно добавить загрузку других параметров конфигурации здесь
            # if 'timeout_wg_show' in config:
            #     self.timeout_wg_show = config['timeout_wg_show']
            
        except json.JSONDecodeError as e:
            self.logger.error(f'Ошибка парсинга конфигурационного файла {config_path}: {e}')
        except Exception as e:
            self.logger.error(f'Ошибка загрузки конфигурации из {config_path}: {e}')
    
    def _run_command(self, command: List[str], timeout: int = 30) -> Tuple[bool, str]:
        """
        Выполнить команду через pkexec с проверкой прав
        
        Args:
            command: Список аргументов команды
            timeout: Таймаут выполнения в секундах
        
        Returns:
            Кортеж (успех, вывод)
        """
        with self._lock:
            full_command = ['pkexec'] + command
            self.logger.debug(f'Выполнение команды: {" ".join(full_command)}')
            
            start_time = time.time()
            try:
                with Timer(f'Команда: {" ".join(command)}', self.logger):
                    result = subprocess.run(
                        full_command,
                        capture_output=True,
                        text=True,
                        timeout=timeout,
                        encoding='utf-8'
                    )
                
                elapsed = time.time() - start_time
                
                if result.returncode == 0:
                    self.logger.debug(
                        f'Команда выполнена успешно за {elapsed:.2f}с: '
                        f'{result.stdout[:200]}...'
                    )
                    return True, result.stdout
                else:
                    # Анализ типа ошибки
                    stderr_lower = result.stderr.lower()
                    if 'authentication canceled' in stderr_lower or 'not authorized' in stderr_lower:
                        self.logger.warning(
                            f'Аутентификация отменена или недостаточно прав '
                            f'(код {result.returncode}) за {elapsed:.2f}с'
                        )
                    elif 'command not found' in stderr_lower:
                        self.logger.error(f'Команда не найдена: {" ".join(command)}')
                    elif 'permission denied' in stderr_lower:
                        self.logger.error(f'Отказано в доступе: {result.stderr}')
                    else:
                        self.logger.error(
                            f'Команда завершилась с ошибкой (код {result.returncode}) '
                            f'за {elapsed:.2f}с: {result.stderr}'
                        )
                    return False, result.stderr
                    
            except subprocess.TimeoutExpired:
                self.logger.error(f'Таймаут выполнения команды: {" ".join(command)}')
                return False, f'Таймаут ({timeout} секунд)'
            except Exception as e:
                self.logger.error(f'Ошибка выполнения команды: {e}')
                return False, str(e)
    
    def _run_command_with_retry(self, command: List[str], timeout: int = 30, 
                                max_retries: Optional[int] = None) -> Tuple[bool, str]:
        """
        Выполнить команду с повторными попытками при неудаче
        
        Args:
            command: Список аргументов команды
            timeout: Таймаут выполнения в секундах
            max_retries: Максимальное количество попыток (None = использовать self.max_retries)
        
        Returns:
            Кортеж (успех, вывод)
        """
        if max_retries is None:
            max_retries = self.max_retries
        
        last_error = ""
        for attempt in range(max_retries):
            success, output = self._run_command(command, timeout)
            
            if success:
                if attempt > 0:
                    self.logger.info(f'Команда выполнена успешно с {attempt+1} попытки')
                return True, output
            
            last_error = output
            self.logger.warning(
                f'Попытка {attempt+1}/{max_retries} не удалась: {output}'
            )
            
            # Не повторяем после таймаута или определенных ошибок
            output_lower = output.lower()
            if ("Таймаут" in output or "Permission denied" in output_lower or 
                "not found" in output_lower or "authentication canceled" in output_lower):
                break
            
            # Задержка перед следующей попыткой
            if attempt < max_retries - 1:
                time.sleep(self.retry_delay)
        
        self.logger.error(f'Все {max_retries} попыток выполнения команды не удались: {last_error}')
        return False, last_error
    
    def check_profile_exists(self, profile_name: str) -> bool:
        """
        Проверить существование профиля
        
        Args:
            profile_name: Имя профиля
        
        Returns:
            True если профиль существует
        """
        # Для стандартных профилей всегда возвращаем True
        if profile_name in self.profiles:
            self.logger.debug(f'Предполагаем существование стандартного профиля: {profile_name}')
            return True
        
        config_file = self.config_dir / f'{profile_name}.conf'
        try:
            exists = config_file.exists()
            self.logger.debug(f'Проверка профиля {profile_name}: {exists}')
            return exists
        except PermissionError:
            # Для нестандартных профилей без прав возвращаем False
            self.logger.debug(f'Нет прав на чтение {config_file}, предполагаем что профиль не существует')
            return False
        except Exception as e:
            self.logger.error(f'Ошибка проверки профиля {profile_name}: {e}')
            return False
    
    def validate_profile(self, profile_name: str) -> Tuple[bool, str]:
        """
        Проверить целостность профиля
        
        Args:
            profile_name: Имя профиля
        
        Returns:
            Кортеж (валидность, сообщение об ошибке)
        """
        if not self.check_profile_exists(profile_name):
            return False, f'Профиль {profile_name} не существует'
        
        # Базовая проверка конфигурационного файла
        config_file = self.config_dir / f'{profile_name}.conf'
        try:
            content = config_file.read_text(encoding='utf-8')
            # Проверяем наличие обязательных секций
            if '[Interface]' not in content:
                return False, 'Отсутствует секция [Interface]'
            
            self.logger.info(f'Профиль {profile_name} прошел валидацию')
            return True, 'OK'
        except (PermissionError, FileNotFoundError):
            # Для стандартных профилей без прав или отсутствующего файла пропускаем валидацию
            if profile_name in self.profiles:
                self.logger.debug(f'Стандартный профиль {profile_name}, проверка пропущена')
                return True, 'Стандартный профиль, проверка не требуется'
            else:
                self.logger.warning(f'Нет прав на чтение конфигурации {profile_name}, пропускаем валидацию')
                return True, 'Проверка прав доступа не удалась, предполагаем валидность'
        except Exception as e:
            self.logger.error(f'Ошибка чтения профиля {profile_name}: {e}')
            return False, f'Ошибка чтения файла: {e}'
    
    def get_active_profile(self) -> Optional[str]:
        """
        Получить имя активного профиля
        
        Returns:
            Имя активного профиля или None
        """
        with Timer('Получение активного профиля', self.logger):
            success, output = self._run_command_with_retry(
                ['wg', 'show'],
                timeout=self.timeout_wg_show
            )
            
            if not success:
                self.logger.warning('Не удалось получить информацию о подключениях')
                return None
            
            # Парсим вывод wg show
            lines = output.strip().split('\n')
            for line in lines:
                if 'interface:' in line.lower():
                    # Пример: interface: wg0
                    interface = line.split(':')[1].strip()
                    # Преобразуем имя интерфейса в имя профиля
                    for profile in self.profiles:
                        if profile.lower() in interface.lower():
                            self._active_profile = profile
                            return profile
            
            self._active_profile = None
            return None
    
    def get_profile_status(self, profile_name: str) -> ProfileStatus:
        """
        Получить статус профиля
        
        Args:
            profile_name: Имя профиля
        
        Returns:
            Статус профиля
        """
        active = self.get_active_profile()
        if active == profile_name:
            return ProfileStatus.ACTIVE
        
        # Проверяем, существует ли профиль
        if not self.check_profile_exists(profile_name):
            return ProfileStatus.ERROR
        
        return ProfileStatus.INACTIVE
    
    def get_all_profiles_info(self) -> Dict[str, ProfileInfo]:
        """
        Получить информацию обо всех профилях
        
        Returns:
            Словарь с информацией о профилях
        """
        with Timer('Получение информации обо всех профилях', self.logger):
            result = {}
            
            for profile in self.profiles:
                status = self.get_profile_status(profile)
                config_path = self.config_dir / f'{profile}.conf'
                
                info = ProfileInfo(
                    name=profile,
                    status=status,
                    config_path=config_path
                )
                
                # Если профиль активен, получаем дополнительную информацию
                if status == ProfileStatus.ACTIVE:
                    success, output = self._run_command_with_retry(
                        ['wg', 'show'],
                        timeout=self.timeout_wg_show
                    )
                    
                    if success:
                        # Парсим статистику (упрощенная версия)
                        lines = output.strip().split('\n')
                        for i, line in enumerate(lines):
                            if 'transfer:' in line.lower():
                                # Пример: transfer: 1.23 MiB received, 456.78 KiB sent
                                parts = line.split(':')[1].strip().split(',')
                                if len(parts) >= 2:
                                    rx_part = parts[0].strip()
                                    tx_part = parts[1].strip()
                                    
                                    # Парсим значения (упрощенно)
                                    if 'received' in rx_part:
                                        rx_value = rx_part.split()[0]
                                        info.transfer_rx = self._parse_transfer(rx_value)
                                    if 'sent' in tx_part:
                                        tx_value = tx_part.split()[0]
                                        info.transfer_tx = self._parse_transfer(tx_value)
                
                result[profile] = info
            
            self._profiles_cache = result
            return result
    
    def _parse_transfer(self, value_str: str) -> int:
        """Парсит строку с размером передачи в байты"""
        try:
            value_str = value_str.lower()
            if 'kib' in value_str:
                return int(float(value_str.replace('kib', '').strip()) * 1024)
            elif 'mib' in value_str:
                return int(float(value_str.replace('mib', '').strip()) * 1024 * 1024)
            elif 'gib' in value_str:
                return int(float(value_str.replace('gib', '').strip()) * 1024 * 1024 * 1024)
            elif 'kb' in value_str:
                return int(float(value_str.replace('kb', '').strip()) * 1000)
            elif 'mb' in value_str:
                return int(float(value_str.replace('mb', '').strip()) * 1000 * 1000)
            elif 'gb' in value_str:
                return int(float(value_str.replace('gb', '').strip()) * 1000 * 1000 * 1000)
            else:
                return int(float(value_str))
        except:
            return 0
    
    def turn_off_all(self) -> Tuple[bool, str]:
        """
        Отключить все профили
        
        Returns:
            Кортеж (успех, сообщение)
        """
        self.logger.info('Отключение всех профилей (последовательность: App → bomBox → usa)')
        
        operations = []
        for profile in ['App', 'bomBox', 'usa']:
            success, message = self._deactivate_profile(profile)
            operations.append((profile, success, message))
            
            if not success:
                self.logger.warning(f'Не удалось отключить профиль {profile}: {message}')
        
        # Проверяем результаты
        failed = [op for op in operations if not op[1]]
        if failed:
            error_msg = ', '.join([f'{p}: {m}' for p, s, m in failed])
            return False, f'Ошибки при отключении: {error_msg}'
        
        self._active_profile = None
        self.logger.info('Все профили отключены')
        return True, 'Все профили отключены'
    
    def activate_profile(self, profile_name: str) -> Tuple[bool, str]:
        """
        Активировать профиль (с предварительным отключением других)
        
        Args:
            profile_name: Имя профиля для активации
        
        Returns:
            Кортеж (успех, сообщение)
        """
        with self._lock:
            # Проверка существования профиля
            if not self.check_profile_exists(profile_name):
                return False, f'Профиль {profile_name} не существует'
            
            # Валидация профиля
            valid, msg = self.validate_profile(profile_name)
            if not valid:
                return False, f'Профиль {profile_name} невалиден: {msg}'
            
            # Проверка, не активен ли уже этот профиль
            current_status = self.get_profile_status(profile_name)
            if current_status == ProfileStatus.ACTIVE:
                self.logger.warning(f'Профиль {profile_name} уже активен')
                return True, f'Профиль {profile_name} уже активен'
            
            self.logger.info(f'Активация профиля {profile_name}...')
            
            # Определяем порядок отключения
            profiles_to_deactivate = []
            for profile in self.profiles:
                if profile != profile_name:
                    current = self.get_profile_status(profile)
                    if current == ProfileStatus.ACTIVE:
                        profiles_to_deactivate.append(profile)
            
            # Отключаем другие профили
            for profile in profiles_to_deactivate:
                self.logger.debug(f'Отключение профиля {profile} перед активацией {profile_name}')
                success, msg = self._deactivate_profile(profile)
                if not success:
                    self.logger.warning(f'Не удалось отключить профиль {profile}: {msg}')
            
            # Активируем целевой профиль
            success, message = self._activate_profile(profile_name)
            
            if success:
                self._active_profile = profile_name
                self.logger.info(f'Профиль {profile_name} успешно активирован')
            else:
                self.logger.error(f'Ошибка активации профиля {profile_name}: {message}')
            
            return success, message
    
    def _activate_profile(self, profile_name: str) -> Tuple[bool, str]:
        """Внутренний метод активации профиля"""
        command = ['wg-quick', 'up', profile_name]
        return self._run_command_with_retry(command, timeout=self.timeout_wg_quick)
    
    def _deactivate_profile(self, profile_name: str) -> Tuple[bool, str]:
        """Внутренний метод деактивации профиля"""
        command = ['wg-quick', 'down', profile_name]
        return self._run_command_with_retry(command, timeout=self.timeout_wg_quick)
    
    def get_wg_show_output(self) -> str:
        """
        Получить вывод команды wg show
        
        Returns:
            Вывод команды или сообщение об ошибке
        """
        success, output = self._run_command_with_retry(
            ['wg', 'show'],
            timeout=self.timeout_wg_show
        )
        
        if success:
            return output.strip()
        else:
            return f'Ошибка получения статуса: {output}'
    
    def check_system_ready(self) -> Tuple[bool, str]:
        """
        Проверить готовность системы к работе
        
        Returns:
            Кортеж (готовность, сообщение об ошибке)
        """
        checks = []
        
        # Проверка наличия команд
        required_commands = ['wg', 'wg-quick', 'pkexec']
        for cmd in required_commands:
            if shutil.which(cmd) is None:
                checks.append(f'Команда {cmd} не найдена')
        
        # Проверка директории конфигураций
        if not self.config_dir.exists():
            checks.append(f'Директория конфигураций не существует: {self.config_dir}')
        elif not os.access(self.config_dir, os.R_OK):
            # Нет прав на чтение директории - это не критично, так как предполагаем существование стандартных профилей
            self.logger.debug(f'Нет прав на чтение директории: {self.config_dir}')
            # Не добавляем в checks, чтобы не показывать предупреждение пользователю
        
        # Проверка хотя бы одного профиля
        profiles_exist = any(self.check_profile_exists(p) for p in self.profiles)
        if not profiles_exist:
            checks.append('Не найден ни один профиль WireGuard')
        
        if checks:
            error_msg = '; '.join(checks)
            self.logger.warning(f'Проблемы с системой: {error_msg}')
            return False, error_msg
        
        self.logger.debug('Система готова к работе')
        return True, 'Система готова'
    
    def refresh_cache(self) -> None:
        """Обновить кэш профилей"""
        with Timer('Обновление кэша профилей', self.logger):
            self._profiles_cache = self.get_all_profiles_info()


# Глобальный экземпляр менеджера
_manager_instance: Optional[WireGuardManager] = None


def get_manager() -> WireGuardManager:
    """
    Получить глобальный экземпляр менеджера
    
    Returns:
        Экземпляр WireGuardManager
    """
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = WireGuardManager()
    return _manager_instance


__all__ = [
    'WireGuardManager',
    'ProfileStatus',
    'ProfileInfo',
    'get_manager'
]