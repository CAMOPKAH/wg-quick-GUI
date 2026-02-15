"""
GUI компоненты WireGuard Manager
Интерфейс на GTK 3 с поддержкой темной темы и анимациями
"""

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('GLib', '2.0')

from gi.repository import Gtk, GLib, Gdk, Pango
import threading
import time
from typing import Dict, Any, Optional, List
from pathlib import Path
from datetime import datetime

from .core import get_manager, ProfileStatus, ProfileInfo
from .logger import get_logger, export_logs


class WireGuardManagerApp:
    """Главное приложение WireGuard Manager"""
    
    def __init__(self):
        self.logger = get_logger(__name__)
        self.manager = get_manager()
        self.window: Optional[Gtk.Window] = None
        self._ui_lock = threading.RLock()
        self._operation_lock = threading.Lock()
        self._last_click_time = 0
        self._debounce_delay = 500  # мс
        
        # Кэш состояния UI
        self._active_profile: Optional[str] = None
        self._profiles_info: Dict[str, ProfileInfo] = {}
        self._status_text: str = ''
        
        # Таймер автообновления
        self._refresh_timer_id = None
        self._is_refreshing = False
        
        # Инициализация UI
        self._init_ui()
        
        # Проверка начального состояния системы
        self._check_initial_state()
    
    def _init_ui(self):
        """Инициализация пользовательского интерфейса"""
        # Создание главного окна
        self.window = Gtk.Window(title="WireGuard Manager")
        self.window.set_default_size(700, 500)
        self.window.set_border_width(10)
        self.window.set_resizable(True)
        
        # Установка иконки
        try:
            icon_theme = Gtk.IconTheme.get_default()
            if icon_theme.has_icon("network-wireless"):
                icon = icon_theme.load_icon("network-wireless", 48, 0)
                self.window.set_icon(icon)
        except:
            pass
        
        # Подключение обработчиков событий
        self.window.connect("destroy", self._on_destroy)
        self.window.connect("key-press-event", self._on_key_press)
        
        # Создание основного контейнера
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.window.add(main_box)
        
        # Панель действий
        self._create_action_panel(main_box)
        
        # Разделитель
        separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        main_box.pack_start(separator, False, False, 5)
        
        # Вкладки
        self.notebook = Gtk.Notebook()
        main_box.pack_start(self.notebook, True, True, 0)
        
        # Вкладка "Статус"
        self._create_status_tab()
        
        # Вкладка "Логи"
        self._create_logs_tab()
        
        # Строка состояния
        self._create_status_bar(main_box)
        
        # Инициализация данных
        self._refresh_data()
        
        # Настройка темной темы
        self._apply_theme()
    
    def _create_action_panel(self, parent: Gtk.Box):
        """Создать панель действий с кнопками"""
        action_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        parent.pack_start(action_box, False, False, 0)
        
        # Индикатор состояния
        self.status_indicator = Gtk.Label(label="🔴 OFF")
        self.status_indicator.set_markup('<span size="x-large" weight="bold">🔴 OFF</span>')
        action_box.pack_start(self.status_indicator, False, False, 0)
        
        # Кнопки профилей
        self.profile_buttons = {}
        
        # Кнопка OFF
        off_btn = Gtk.Button.new_with_label("OFF")
        off_btn.set_tooltip_text("Отключить все профили (Ctrl+1)")
        off_btn.connect("clicked", self._on_off_clicked)
        self.profile_buttons['OFF'] = off_btn
        action_box.pack_start(off_btn, False, False, 0)
        
        # Кнопка bomBox
        bombox_btn = Gtk.Button.new_with_label("🌍 Bombox")
        bombox_btn.set_tooltip_text("Активировать профиль bomBox (Ctrl+2)")
        bombox_btn.connect("clicked", self._on_bombox_clicked)
        self.profile_buttons['bomBox'] = bombox_btn
        action_box.pack_start(bombox_btn, False, False, 0)
        
        # Кнопка App
        app_btn = Gtk.Button.new_with_label("📱 App")
        app_btn.set_tooltip_text("Активировать профиль App (Ctrl+3)")
        app_btn.connect("clicked", self._on_app_clicked)
        self.profile_buttons['App'] = app_btn
        action_box.pack_start(app_btn, False, False, 0)
        
        # Кнопка обновления
        refresh_btn = Gtk.Button.new_from_icon_name("view-refresh", Gtk.IconSize.BUTTON)
        refresh_btn.set_tooltip_text("Обновить статус (F5)")
        refresh_btn.connect("clicked", self._on_refresh_clicked)
        action_box.pack_start(refresh_btn, False, False, 0)
        
        # Кнопка сохранения логов
        save_log_btn = Gtk.Button.new_with_label("💾 Сохранить лог")
        save_log_btn.set_tooltip_text("Экспортировать логи в файл")
        save_log_btn.connect("clicked", self._on_save_log_clicked)
        action_box.pack_start(save_log_btn, False, False, 0)
        
        # Индикатор выполнения
        self.spinner = Gtk.Spinner()
        action_box.pack_start(self.spinner, False, False, 0)
    
    def _create_status_tab(self):
        """Создать вкладку статуса"""
        status_frame = Gtk.Frame(label="Статус WireGuard")
        status_frame.set_shadow_type(Gtk.ShadowType.IN)
        
        scrolled_window = Gtk.ScrolledWindow()
        scrolled_window.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled_window.set_min_content_height(200)
        
        self.status_textview = Gtk.TextView()
        self.status_textview.set_editable(False)
        self.status_textview.set_cursor_visible(False)
        self.status_textview.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        
        # Используем моноширинный шрифт для вывода команд
        font_desc = Pango.FontDescription("Monospace 10")
        self.status_textview.modify_font(font_desc)
        
        scrolled_window.add(self.status_textview)
        status_frame.add(scrolled_window)
        
        self.notebook.append_page(status_frame, Gtk.Label(label="Статус"))
    
    def _create_logs_tab(self):
        """Создать вкладку логов"""
        logs_frame = Gtk.Frame(label="Логи приложения")
        logs_frame.set_shadow_type(Gtk.ShadowType.IN)
        
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        logs_frame.add(vbox)
        
        # Панель управления логами
        controls_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        controls_box.set_margin_top(5)
        controls_box.set_margin_bottom(5)
        controls_box.set_margin_start(5)
        controls_box.set_margin_end(5)
        vbox.pack_start(controls_box, False, False, 0)
        
        # Поле количества строк
        lines_label = Gtk.Label(label="Строк:")
        controls_box.pack_start(lines_label, False, False, 0)
        
        self.log_lines_spin = Gtk.SpinButton.new_with_range(10, 1000, 10)
        self.log_lines_spin.set_value(100)
        self.log_lines_spin.set_tooltip_text("Количество строк логов для отображения")
        controls_box.pack_start(self.log_lines_spin, False, False, 0)
        
        # Кнопка обновления логов
        refresh_logs_btn = Gtk.Button.new_with_label("Обновить логи")
        refresh_logs_btn.connect("clicked", self._on_refresh_logs_clicked)
        controls_box.pack_start(refresh_logs_btn, False, False, 0)
        
        # Кнопка очистки
        clear_logs_btn = Gtk.Button.new_with_label("Очистить")
        clear_logs_btn.connect("clicked", self._on_clear_logs_clicked)
        controls_box.pack_start(clear_logs_btn, False, False, 0)
        
        # Прокручиваемое окно для логов
        scrolled_window = Gtk.ScrolledWindow()
        scrolled_window.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled_window.set_min_content_height(300)
        
        self.logs_textview = Gtk.TextView()
        self.logs_textview.set_editable(False)
        self.logs_textview.set_cursor_visible(False)
        self.logs_textview.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        
        # Моноширинный шрифт для логов
        font_desc = Pango.FontDescription("Monospace 9")
        self.logs_textview.modify_font(font_desc)
        
        scrolled_window.add(self.logs_textview)
        vbox.pack_start(scrolled_window, True, True, 0)
        
        self.notebook.append_page(logs_frame, Gtk.Label(label="Логи"))
    
    def _create_status_bar(self, parent: Gtk.Box):
        """Создать строку состояния"""
        self.status_bar = Gtk.Statusbar()
        parent.pack_start(self.status_bar, False, False, 0)
        
        # Контекст для сообщений
        self.status_context_id = self.status_bar.get_context_id("status")
        
        # Обновляем время в строке состояния
        self._update_status_bar()
    
    def _apply_theme(self):
        """Применить темную тему если доступна"""
        try:
            settings = Gtk.Settings.get_default()
            settings.set_property("gtk-application-prefer-dark-theme", True)
            
            # Пытаемся установить тему Adwaita-dark
            css_provider = Gtk.CssProvider()
            css = """
            * {
                font-family: 'Ubuntu', 'Cantarell', sans-serif;
            }
            
            button {
                padding: 8px 12px;
                border-radius: 4px;
            }
            
            button:active {
                background-color: shade(@theme_bg_color, 0.9);
            }
            
            .active-profile {
                font-weight: bold;
                background-color: @theme_selected_bg_color;
                color: @theme_selected_fg_color;
            }
            """
            
            css_provider.load_from_data(css.encode())
            screen = Gdk.Screen.get_default()
            Gtk.StyleContext.add_provider_for_screen(
                screen,
                css_provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )
        except Exception as e:
            self.logger.debug(f"Не удалось применить тему: {e}")
    
    def _debounce_click(self) -> bool:
        """Проверка защиты от повторных кликов"""
        current_time = int(time.time() * 1000)
        if current_time - self._last_click_time < self._debounce_delay:
            return False
        self._last_click_time = current_time
        return True
    
    def _set_ui_busy(self, busy: bool):
        """Установить состояние занятости UI"""
        if self.window is None:
            self.logger.debug("Окно не существует, пропускаем обновление занятости")
            return
        
        try:
            if not self.window.get_property('visible'):
                self.logger.debug("Окно не видимо, пропускаем обновление занятости")
                return
        except Exception as e:
            self.logger.debug(f"Ошибка при проверке окна: {e}, пропускаем обновление занятости")
            return
        
        try:
            GLib.idle_add(self._safe_ui_busy_callback, busy)
        except Exception as e:
            self.logger.error(f"Ошибка при вызове GLib.idle_add (занятость): {e}")
    
    def _safe_ui_busy_callback(self, busy: bool):
        """Безопасный callback для установки состояния занятости UI"""
        try:
            self._ui_busy_callback(busy)
        except Exception as e:
            self.logger.error(f"Ошибка в UI callback (занятость): {e}")
    
    def _safe_idle_add(self, callback, *args):
        """Безопасный вызов GLib.idle_add с проверкой окна"""
        if self.window is None:
            self.logger.debug("Окно не существует, пропускаем обновление UI")
            return
        
        try:
            # Проверяем, что окно еще существует и видимо
            if not self.window.get_property('visible'):
                self.logger.debug("Окно не видимо, пропускаем обновление UI")
                return
        except Exception as e:
            self.logger.debug(f"Ошибка при проверке окна: {e}, пропускаем обновление UI")
            return
        
        def safe_callback(*cb_args):
            try:
                callback(*cb_args)
            except Exception as e:
                self.logger.error(f"Ошибка в idle_add callback: {e}")
                return False
            return False
        
        try:
            GLib.idle_add(safe_callback, *args)
        except Exception as e:
            self.logger.error(f"Ошибка при вызове GLib.idle_add: {e}")
    
    def _ui_busy_callback(self, busy: bool):
        """Callback для установки состояния занятости UI"""
        with self._ui_lock:
            if busy:
                self.spinner.start()
                # Деактивируем кнопки
                for btn in self.profile_buttons.values():
                    btn.set_sensitive(False)
            else:
                self.spinner.stop()
                # Активируем кнопки
                for btn in self.profile_buttons.values():
                    btn.set_sensitive(True)
        
        return False
    
    def _update_status_indicator(self):
        """Обновить индикатор состояния"""
        with self._ui_lock:
            if self._active_profile:
                markup = f'<span size="x-large" weight="bold">🟢 Активен: {self._active_profile}</span>'
            else:
                markup = f'<span size="x-large" weight="bold">🔴 OFF</span>'
            
            def update_indicator():
                try:
                    self.status_indicator.set_markup(markup)
                except Exception as e:
                    self.logger.error(f"Ошибка при обновлении индикатора состояния: {e}")
            
            self._safe_idle_add(update_indicator)
    
    def _update_profile_buttons(self):
        """Обновить состояние кнопок профилей"""
        with self._ui_lock:
            def update_buttons():
                try:
                    for profile_name, button in self.profile_buttons.items():
                        if profile_name == 'OFF':
                            continue
                        
                        # Получаем информацию о профиле
                        profile_info = self._profiles_info.get(profile_name)
                        if not profile_info:
                            continue
                        
                        # Обновляем стиль кнопки
                        ctx = button.get_style_context()
                        if profile_info.status == ProfileStatus.ACTIVE:
                            ctx.add_class("active-profile")
                            button.set_label(f"✓ {profile_name}")
                        else:
                            ctx.remove_class("active-profile")
                            # Восстанавливаем оригинальную метку
                            if profile_name == 'bomBox':
                                button.set_label("🌍 Bombox")
                            elif profile_name == 'App':
                                button.set_label("📱 App")
                except Exception as e:
                    self.logger.error(f"Ошибка при обновлении кнопок профилей: {e}")
            
            self._safe_idle_add(update_buttons)
    
    def _update_status_text(self):
        """Обновить текст статуса"""
        with self._ui_lock:
            # Формируем текст статуса
            lines = []
            lines.append("=== WireGuard Status ===")
            lines.append(f"Обновлено: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            lines.append("")
            
            # Добавляем информацию о профилях
            for profile_name, info in self._profiles_info.items():
                status_icon = "🟢" if info.status == ProfileStatus.ACTIVE else "🔴"
                lines.append(f"{status_icon} {profile_name}: {info.status.value}")
                
                if info.status == ProfileStatus.ACTIVE:
                    if info.transfer_rx > 0 or info.transfer_tx > 0:
                        rx_mb = info.transfer_rx / (1024 * 1024)
                        tx_mb = info.transfer_tx / (1024 * 1024)
                        lines.append(f"   📥 Принято: {rx_mb:.2f} МБ")
                        lines.append(f"   📤 Отправлено: {tx_mb:.2f} МБ")
            
            lines.append("")
            lines.append("=== wg show output ===")
            # Форматируем вывод для лучшей читаемости
            formatted_output = self._format_wg_show_output(self._status_text)
            lines.append(formatted_output)
            
            text = "\n".join(lines)
            
            def update_text():
                try:
                    textbuffer = self.status_textview.get_buffer()
                    textbuffer.set_text(text)
                except Exception as e:
                    self.logger.error(f"Ошибка при обновлении текста статуса: {e}")
            
            self._safe_idle_add(update_text)
    
    def _update_logs_text(self):
        """Обновить текст логов"""
        lines = int(self.log_lines_spin.get_value())
        log_file = Path.home() / '.local' / 'share' / 'wg-manager' / 'wg-manager.log'
        
        if not log_file.exists():
            text = "Файл логов не найден"
            def update_logs():
                try:
                    self.logs_textview.get_buffer().set_text(text)
                except Exception as e:
                    self.logger.error(f"Ошибка при обновлении логов: {e}")
            self._safe_idle_add(update_logs)
            return
        
        try:
            with open(log_file, 'r', encoding='utf-8') as f:
                all_lines = f.readlines()
            
            last_lines = all_lines[-lines:] if len(all_lines) > lines else all_lines
            text = "".join(last_lines)
            
            def update_logs_with_scroll():
                try:
                    textbuffer = self.logs_textview.get_buffer()
                    textbuffer.set_text(text)
                    end_iter = textbuffer.get_end_iter()
                    self.logs_textview.scroll_to_iter(end_iter, 0.0, False, 0.0, 0.0)
                except Exception as e:
                    self.logger.error(f"Ошибка при обновлении логов: {e}")
            self._safe_idle_add(update_logs_with_scroll)
        except Exception as e:
            self.logger.error(f"Ошибка чтения логов: {e}")
    
    def _update_status_bar(self):
        """Обновить строку состояния"""
        with self._ui_lock:
            if self._active_profile:
                profile_info = self._profiles_info.get(self._active_profile)
                if profile_info and profile_info.status == ProfileStatus.ACTIVE:
                    rx_mb = profile_info.transfer_rx / (1024 * 1024) if profile_info.transfer_rx else 0
                    tx_mb = profile_info.transfer_tx / (1024 * 1024) if profile_info.transfer_tx else 0
                    status_text = (
                        f"🟢 Активен: {self._active_profile} | "
                        f"📶 Передано: {rx_mb:.1f} МБ ↓ / {tx_mb:.1f} МБ ↑ | "
                        f"⏱️ Обновлено: {datetime.now().strftime('%H:%M:%S')}"
                    )
                else:
                    status_text = f"🔴 Нет активных профилей | ⏱️ {datetime.now().strftime('%H:%M:%S')}"
            else:
                status_text = f"🔴 Нет активных профилей | ⏱️ {datetime.now().strftime('%H:%M:%S')}"
            
            def update_status_bar():
                try:
                    self.status_bar.push(self.status_context_id, status_text)
                except Exception as e:
                    self.logger.error(f"Ошибка при обновлении строки состояния: {e}")
            
            self._safe_idle_add(update_status_bar)
     
    def _format_wg_show_output(self, raw_output: str) -> str:
        """
        Форматировать вывод команды wg show для отображения
        
        Args:
            raw_output: Сырой вывод команды wg show
            
        Returns:
            Отформатированный текст
        """
        if not raw_output or "Ошибка получения статуса" in raw_output:
            return raw_output
        
        lines = raw_output.strip().split('\n')
        formatted_lines = []
        
        # Парсим вывод
        current_section = None
        for line in lines:
            line = line.rstrip()
            if not line:
                continue
            
            # Определяем секции
            if 'interface:' in line.lower():
                formatted_lines.append(f"🔌 {line}")
                current_section = 'interface'
            elif 'peer:' in line.lower():
                formatted_lines.append(f"👤 {line}")
                current_section = 'peer'
            elif 'endpoint:' in line.lower():
                # Форматируем endpoint
                if ':' in line:
                    parts = line.split(':', 1)
                    formatted_lines.append(f"  🌐 {parts[0].strip()}: {parts[1].strip()}")
                else:
                    formatted_lines.append(f"  {line}")
            elif 'allowed ips:' in line.lower():
                formatted_lines.append(f"  📡 {line}")
            elif 'latest handshake:' in line.lower():
                # Извлекаем время handshake
                if ':' in line:
                    parts = line.split(':', 1)
                    time_str = parts[1].strip()
                    formatted_lines.append(f"  🤝 Последнее рукопожатие: {time_str}")
                else:
                    formatted_lines.append(f"  {line}")
            elif 'transfer:' in line.lower():
                # Форматируем transfer
                if ':' in line:
                    parts = line.split(':', 1)
                    transfer_info = parts[1].strip()
                    # Разделяем received и sent
                    if 'received' in transfer_info and 'sent' in transfer_info:
                        formatted_lines.append(f"  📊 Передача данных:")
                        # Пытаемся извлечь значения
                        if ',' in transfer_info:
                            received, sent = transfer_info.split(',', 1)
                            formatted_lines.append(f"    📥 {received.strip()}")
                            formatted_lines.append(f"    📤 {sent.strip()}")
                    else:
                        formatted_lines.append(f"  {line}")
                else:
                    formatted_lines.append(f"  {line}")
            elif 'preshared key:' in line.lower():
                # Скрываем preshared key
                formatted_lines.append(f"  🔑 preshared key: (скрыто)")
            elif line.startswith('  '):  # Отступы для деталей peer
                formatted_lines.append(f"  {line}")
            else:
                formatted_lines.append(line)
        
        # Если вывод пустой после форматирования, возвращаем оригинал
        if not formatted_lines:
            return raw_output
        
        return '\n'.join(formatted_lines)
    
    def _refresh_data(self):
        """Обновить все данные"""
        with self._ui_lock:
            # Проверяем, не выполняется ли уже обновление
            if self._is_refreshing:
                # Проверяем, не зависло ли обновление
                if hasattr(self, '_refresh_start_time'):
                    elapsed = time.time() - self._refresh_start_time
                    if elapsed > 60:  # 60 секунд - слишком долго
                        self.logger.warning(f"Обновление зависло ({elapsed:.0f} секунд), сбрасываем состояние")
                        self._is_refreshing = False
                    else:
                        self.logger.debug("Обновление уже выполняется, пропускаем")
                        return
                else:
                    self.logger.debug("Обновление уже выполняется, пропускаем")
                    return
            
            self._is_refreshing = True
            self._refresh_start_time = time.time()
            self._set_ui_busy(True)
            
            def refresh_task():
                try:
                    # Получаем активный профиль
                    self._active_profile = self.manager.get_active_profile()
                    
                    # Получаем информацию о профилях
                    self._profiles_info = self.manager.get_all_profiles_info()
                    
                    # Получаем вывод wg show
                    self._status_text = self.manager.get_wg_show_output()
                    
                    # Обновляем UI
                    self._update_status_indicator()
                    self._update_profile_buttons()
                    self._update_status_text()
                    self._update_status_bar()
                    
                    self.logger.debug("Данные успешно обновлены")
                except Exception as e:
                    self.logger.error(f"Ошибка при обновлении данных: {e}")
                finally:
                    with self._ui_lock:
                        self._is_refreshing = False
                        if hasattr(self, '_refresh_start_time'):
                            del self._refresh_start_time
                    self._set_ui_busy(False)
            
            # Запускаем в отдельном потоке
            try:
                thread = threading.Thread(target=refresh_task, daemon=True)
                thread.start()
            except Exception as e:
                self.logger.error(f"Не удалось запустить поток обновления: {e}")
                with self._ui_lock:
                    self._is_refreshing = False
                self._set_ui_busy(False)
    
    def _run_operation(self, operation_func, *args, **kwargs):
        """Выполнить операцию с блокировкой UI"""
        if not self._debounce_click():
            self.logger.debug("Игнорируем быстрый повторный клик")
            return
        
        self._set_ui_busy(True)
        
        def operation_task():
            try:
                success, message = operation_func(*args, **kwargs)
                
                if success:
                    self.logger.info(f"Операция успешна: {message}")
                    # Показываем уведомление
                    self._safe_idle_add(self._show_notification, "Успех", message, "dialog-information")
                else:
                    self.logger.error(f"Ошибка операции: {message}")
                    self._safe_idle_add(self._show_notification, "Ошибка", message, "dialog-error")
                
                # Обновляем данные после операции
                self._refresh_data()
            except Exception as e:
                self.logger.error(f"Неожиданная ошибка: {e}")
                self._safe_idle_add(self._show_notification, "Ошибка", str(e), "dialog-error")
            finally:
                self._set_ui_busy(False)
        
        thread = threading.Thread(target=operation_task, daemon=True)
        thread.start()
    
    def _adjust_dialog_position(self, dialog, offset_percent=30):
        """
        Настроить позицию диалога, сдвинув его на указанный процент ниже
        
        Args:
            dialog: Диалог Gtk.Dialog
            offset_percent: Процент смещения от высоты экрана (по умолчанию 30%)
        """
        def on_dialog_realize(widget):
            try:
                # Получаем экран
                screen = widget.get_screen()
                if not screen:
                    return
                
                # Получаем размеры экрана (используем основной монитор)
                try:
                    screen_height = screen.get_height()
                    screen_width = screen.get_width()
                except Exception:
                    # fallback: используем геометрию монитора
                    display = Gdk.Display.get_default()
                    if display:
                        monitor = display.get_primary_monitor() or display.get_monitor(0)
                        if monitor:
                            geometry = monitor.get_geometry()
                            screen_height = geometry.height
                            screen_width = geometry.width
                        else:
                            screen_height = 768
                            screen_width = 1024
                    else:
                        screen_height = 768
                        screen_width = 1024
                
                # Получаем текущую позицию окна
                x, y = widget.get_position()
                
                # Сдвигаем на указанный процент от высоты экрана
                offset = int(screen_height * offset_percent / 100)
                new_y = y + offset
                
                # Получаем размеры диалога
                width = widget.get_size().width
                height = widget.get_size().height
                
                # Проверяем, чтобы окно не вышло за нижнюю границу экрана
                if new_y + height > screen_height:
                    new_y = screen_height - height - 50  # Отступ 50 пикселей от нижнего края
                
                # Если new_y получился меньше 0, ставим небольшой отступ
                if new_y < 0:
                    new_y = 50  # Отступ от верхнего края
                
                # Перемещаем окно (горизонтальная позиция остается прежней)
                widget.move(x, new_y)
                
                self.logger.debug(f"Диалог перемещен с позиции ({x}, {y}) на ({x}, {new_y})")
            except Exception as e:
                self.logger.debug(f"Ошибка при настройке позиции диалога: {e}")
                # Продолжаем без изменения позиции
        
        dialog.connect('realize', on_dialog_realize)
    
    def _show_notification(self, title: str, message: str, icon_name: str):
        """Показать уведомление"""
        try:
            # Создаем диалог с parent, если окно существует
            if self.window and self.window.get_property('visible'):
                dialog = Gtk.MessageDialog(
                    transient_for=self.window,
                    flags=0,
                    message_type=Gtk.MessageType.INFO,
                    buttons=Gtk.ButtonsType.OK,
                    text=title
                )
                # Устанавливаем позицию относительно родительского окна
                dialog.set_position(Gtk.WindowPosition.CENTER_ON_PARENT)
            else:
                dialog = Gtk.MessageDialog(
                    parent=None,
                    flags=0,
                    message_type=Gtk.MessageType.INFO,
                    buttons=Gtk.ButtonsType.OK,
                    text=title
                )
                # Центрируем на экране
                dialog.set_position(Gtk.WindowPosition.CENTER)
            
            dialog.format_secondary_text(message)
            
            # Устанавливаем иконку
            try:
                dialog.set_icon_name(icon_name)
            except:
                pass
            
            # Настраиваем позицию диалога (сдвигаем на 30% ниже)
            self._adjust_dialog_position(dialog, offset_percent=30)
            
            dialog.run()
            dialog.destroy()
        except Exception as e:
            self.logger.error(f"Ошибка при показе уведомления: {e}")
            # Выводим в консоль как запасной вариант
            print(f"{title}: {message}")
    
    # Обработчики событий
    
    def _on_off_clicked(self, button: Gtk.Button):
        """Обработчик клика по кнопке OFF"""
        self._run_operation(self.manager.turn_off_all)
    
    def _on_bombox_clicked(self, button: Gtk.Button):
        """Обработчик клика по кнопке bomBox"""
        self._run_operation(self.manager.activate_profile, "bomBox")
    
    def _on_app_clicked(self, button: Gtk.Button):
        """Обработчик клика по кнопке App"""
        self._run_operation(self.manager.activate_profile, "App")
    
    def _on_refresh_clicked(self, button: Gtk.Button):
        """Обработчик клика по кнопке обновления"""
        self._refresh_data()
    
    def _on_save_log_clicked(self, button: Gtk.Button):
        """Обработчик клика по кнопке сохранения логов"""
        dialog = Gtk.FileChooserDialog(
            title="Сохранить логи",
            parent=self.window,
            action=Gtk.FileChooserAction.SAVE,
            buttons=(
                Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                Gtk.STOCK_SAVE, Gtk.ResponseType.OK
            )
        )
        
        # Устанавливаем имя файла по умолчанию
        default_name = f"wg-manager-logs-{datetime.now().strftime('%Y%m%d-%H%M%S')}.txt"
        dialog.set_current_name(default_name)
        
        # Настраиваем позицию диалога
        if self.window and self.window.get_property('visible'):
            dialog.set_position(Gtk.WindowPosition.CENTER_ON_PARENT)
        else:
            dialog.set_position(Gtk.WindowPosition.CENTER)
        
        # Сдвигаем диалог на 30% ниже
        self._adjust_dialog_position(dialog, offset_percent=30)
        
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            filename = dialog.get_filename()
            success = export_logs(filename, lines=1000)
            
            if success:
                self._show_notification(
                    "Успех",
                    f"Логи сохранены в {filename}",
                    "document-save"
                )
            else:
                self._show_notification(
                    "Ошибка",
                    "Не удалось сохранить логи",
                    "dialog-error"
                )
        
        dialog.destroy()
    
    def _on_refresh_logs_clicked(self, button: Gtk.Button):
        """Обработчик клика по кнопке обновления логов"""
        # Запускаем обновление логов через idle_add для безопасности
        self._safe_idle_add(self._update_logs_text)
    
    def _on_clear_logs_clicked(self, button: Gtk.Button):
        """Обработчик клика по кнопке очистки логов"""
        textbuffer = self.logs_textview.get_buffer()
        self._safe_idle_add(textbuffer.set_text, "")
    
    def _on_destroy(self, window: Gtk.Window):
        """Обработчик закрытия окна"""
        self.logger.info("Приложение завершает работу")
        self._stop_auto_refresh()
        self.window = None
        Gtk.main_quit()
    
    def _on_key_press(self, widget: Gtk.Widget, event: Gdk.EventKey) -> bool:
        """Обработчик нажатия клавиш"""
        # Ctrl+1 - OFF
        if event.state & Gdk.ModifierType.CONTROL_MASK and event.keyval == Gdk.KEY_1:
            self._on_off_clicked(None)
            return True
        # Ctrl+2 - bomBox
        elif event.state & Gdk.ModifierType.CONTROL_MASK and event.keyval == Gdk.KEY_2:
            self._on_bombox_clicked(None)
            return True
        # Ctrl+3 - App
        elif event.state & Gdk.ModifierType.CONTROL_MASK and event.keyval == Gdk.KEY_3:
            self._on_app_clicked(None)
            return True
        # F5 - обновить
        elif event.keyval == Gdk.KEY_F5:
            self._refresh_data()
            return True
        
        return False
    
    def _check_initial_state(self):
        """Проверить начальное состояние системы и показать предупреждения"""
        def check_task():
            try:
                # Проверка готовности системы
                ready, message = self.manager.check_system_ready()
                if not ready:
                    self.logger.warning(f"Проблемы с системой: {message}")
                    self._safe_idle_add(self._show_notification, 
                                       "Проблемы с системой", 
                                       f"Некоторые функции могут не работать: {message}", 
                                       "dialog-warning")
                
                # Пробуем получить статус WireGuard
                success, output = self.manager._run_command_with_retry(['wg', 'show'], timeout=10)
                if not success:
                    if "authentication canceled" in output.lower() or "not authorized" in output.lower():
                        self.logger.warning("Аутентификация отменена пользователем")
                        self._safe_idle_add(self._show_notification,
                                           "Требуются права администратора",
                                           "Для управления WireGuard нужны права администратора. "
                                           "При запросе пароля введите пароль вашей учётной записи.",
                                           "dialog-information")
                    elif "command not found" in output.lower():
                        self.logger.error("Команда wg не найдена")
                        self._safe_idle_add(self._show_notification,
                                           "WireGuard не установлен",
                                           "Установите WireGuard: sudo apt install wireguard",
                                           "dialog-error")
            except Exception as e:
                self.logger.error(f"Ошибка при проверке начального состояния: {e}")
        
        # Запускаем проверку в фоновом потоке
        thread = threading.Thread(target=check_task, daemon=True)
        thread.start()
    
    def _start_auto_refresh(self):
        """Запустить автоматическое обновление каждые 2 секунды"""
        if self._refresh_timer_id is not None:
            GLib.source_remove(self._refresh_timer_id)
        
        def refresh_callback():
            self._refresh_data()
            return True  # Продолжаем таймер
        
        # 2000 миллисекунд = 2 секунды
        self._refresh_timer_id = GLib.timeout_add(2000, refresh_callback)
        self.logger.debug("Автообновление запущено (интервал 2 секунды)")
    
    def _stop_auto_refresh(self):
        """Остановить автоматическое обновление"""
        if self._refresh_timer_id is not None:
            GLib.source_remove(self._refresh_timer_id)
            self._refresh_timer_id = None
            self.logger.debug("Автообновление остановлено")
     
    def run(self, argv: List[str]) -> int:
        """Запустить приложение"""
        self.logger.info("Запуск GUI приложения")
        self.window.show_all()
        # Запускаем автообновление каждые 2 секунды
        self._start_auto_refresh()
        Gtk.main()
        return 0


__all__ = ['WireGuardManagerApp']