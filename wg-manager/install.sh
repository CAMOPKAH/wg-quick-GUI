#!/bin/bash
#
# Скрипт установки WireGuard Manager
# Устанавливает зависимости, настраивает PolicyKit и интегрирует приложение
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_NAME="WireGuard Manager"
VERSION="1.0.0"
POLICY_FILE="org.wireguard.manager.policy"
DESKTOP_FILE="wg-manager.desktop"

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_root() {
    if [[ $EUID -eq 0 ]]; then
        log_warning "Скрипт запущен от root. Рекомендуется запускать от обычного пользователя."
        read -p "Продолжить? [y/N] " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    fi
}

install_system_dependencies() {
    log_info "Установка системных зависимостей..."
    
    local packages=(
        "wireguard-tools"
        "policykit-1"
        "python3"
        "python3-pip"
        "python3-gi"
        "python3-gi-cairo"
        "gir1.2-gtk-3.0"
        "gir1.2-glib-2.0"
        "python3-setuptools"
    )
    
    # Проверяем, есть ли apt
    if ! command -v apt-get >/dev/null 2>&1; then
        log_error "Система управления пакетами apt не обнаружена"
        log_info "Установите следующие пакеты вручную:"
        for pkg in "${packages[@]}"; do
            echo "  - $pkg"
        done
        return 1
    fi
    
    # Обновляем список пакетов
    log_info "Обновление списка пакетов..."
    sudo apt-get update -qq
    
    # Устанавливаем пакеты
    for pkg in "${packages[@]}"; do
        if dpkg -l | grep -q "^ii  $pkg "; then
            log_success "$pkg уже установлен"
        else
            log_info "Установка $pkg..."
            sudo apt-get install -y -qq "$pkg"
            if [[ $? -eq 0 ]]; then
                log_success "$pkg успешно установлен"
            else
                log_error "Ошибка установки $pkg"
                return 1
            fi
        fi
    done
    
    log_success "Все системные зависимости установлены"
    return 0
}

install_python_dependencies() {
    log_info "Установка Python зависимостей..."
    
    # Создаем виртуальное окружение (опционально)
    if [[ ! -d "$SCRIPT_DIR/venv" ]]; then
        log_info "Создание виртуального окружения..."
        python3 -m venv "$SCRIPT_DIR/venv" 2>/dev/null || {
            log_warning "Не удалось создать виртуальное окружение, используем системный Python"
        }
    fi
    
    # Устанавливаем pytest для тестов
    log_info "Установка pytest для тестирования..."
    pip3 install --quiet pytest pytest-cov 2>/dev/null || {
        log_warning "Не удалось установить pytest через pip3"
        log_info "Попытка установки через apt..."
        sudo apt-get install -y -qq python3-pytest python3-pytest-cov 2>/dev/null || true
    }
    
    log_success "Python зависимости установлены"
    return 0
}

setup_policykit() {
    log_info "Настройка PolicyKit..."
    
    local policy_dir="/usr/share/polkit-1/actions"
    local policy_path="$policy_dir/$POLICY_FILE"
    
    # Создаем XML политики
    local policy_xml=$(cat << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE policyconfig PUBLIC
 "-//freedesktop//DTD PolicyKit Policy Configuration 1.0//EN"
 "http://www.freedesktop.org/standards/PolicyKit/1/policyconfig.dtd">
<policyconfig>
  <vendor>WireGuard Manager</vendor>
  <vendor_url>https://github.com/yourusername/wg-manager</vendor_url>

  <action id="org.wireguard.manager.run-wg-quick">
    <description>Run wg-quick commands for WireGuard profiles</description>
    <message>Authentication is required to manage WireGuard VPN connections</message>
    <icon_name>network-wireless</icon_name>
    <defaults>
      <allow_any>auth_admin</allow_any>
      <allow_inactive>auth_admin</allow_inactive>
      <allow_active>auth_admin_keep</allow_active>
    </defaults>
    <annotate key="org.freedesktop.policykit.exec.path">/usr/bin/wg-quick</annotate>
    <annotate key="org.freedesktop.policykit.exec.allow_gui">false</annotate>
  </action>

  <action id="org.wireguard.manager.run-wg">
    <description>Run wg commands to check WireGuard status</description>
    <message>Authentication is required to check WireGuard status</message>
    <icon_name>network-wireless</icon_name>
    <defaults>
      <allow_any>auth_admin</allow_any>
      <allow_inactive>auth_admin</allow_inactive>
      <allow_active>auth_admin_keep</allow_active>
    </defaults>
    <annotate key="org.freedesktop.policykit.exec.path">/usr/bin/wg</annotate>
    <annotate key="org.freedesktop.policykit.exec.allow_gui">false</annotate>
  </action>
</policyconfig>
EOF
    )
    
    # Проверяем существование директории
    if [[ ! -d "$policy_dir" ]]; then
        log_error "Директория PolicyKit не найдена: $policy_dir"
        return 1
    fi
    
    # Записываем политику
    log_info "Создание файла политики: $policy_path"
    echo "$policy_xml" | sudo tee "$policy_path" > /dev/null
    
    if [[ $? -eq 0 ]]; then
        log_success "Политика PolicyKit успешно создана"
        
        # Устанавливаем правильные права
        sudo chmod 644 "$policy_path"
        
        # Проверяем, что политика загружена
        if pkaction --action-id org.wireguard.manager.run-wg-quick > /dev/null 2>&1; then
            log_success "Политика успешно загружена в PolicyKit"
        else
            log_warning "Политика создана, но не загружена. Перезапустите систему или PolicyKit"
        fi
    else
        log_error "Ошибка создания файла политики"
        return 1
    fi
    
    return 0
}

setup_log_directories() {
    log_info "Настройка директорий для логов..."
    
    local log_dir="$HOME/.local/share/wg-manager"
    
    # Создаем директорию
    mkdir -p "$log_dir"
    
    # Создаем файлы логов
    touch "$log_dir/wg-manager.log"
    touch "$log_dir/errors.log"
    
    # Устанавливаем права
    chmod 644 "$log_dir/wg-manager.log"
    chmod 644 "$log_dir/errors.log"
    
    log_success "Директории логов созданы: $log_dir"
    return 0
}

check_wireguard_configs() {
    log_info "Проверка конфигураций WireGuard..."
    
    local config_dir="/etc/wireguard"
    
    if [[ ! -d "$config_dir" ]]; then
        log_warning "Директория WireGuard не найдена: $config_dir"
        log_info "Создание директории..."
        sudo mkdir -p "$config_dir"
        sudo chmod 755 "$config_dir"
        log_success "Директория создана: $config_dir"
    fi
    
    # Проверяем права на чтение
    if [[ -r "$config_dir" ]]; then
        log_success "Есть доступ на чтение к $config_dir"
    else
        log_warning "Нет доступа на чтение к $config_dir"
        log_info "Добавьте себя в группу, имеющую доступ к /etc/wireguard"
        log_info "Или используйте sudo для управления профилями"
    fi
    
    # Пример конфигурации
    local sample_config=$(cat << EOF
# Пример конфигурации WireGuard
# Сохраните как /etc/wireguard/App.conf
# и замените значения на свои

[Interface]
PrivateKey = YOUR_PRIVATE_KEY
Address = 10.0.0.2/24
DNS = 1.1.1.1

[Peer]
PublicKey = SERVER_PUBLIC_KEY
Endpoint = server.example.com:51820
AllowedIPs = 0.0.0.0/0
PersistentKeepalive = 25
EOF
    )
    
    # Проверяем существование профилей
    local profiles=("App" "bomBox" "usa")
    local missing_profiles=()
    
    for profile in "${profiles[@]}"; do
        if [[ -f "$config_dir/$profile.conf" ]]; then
            log_success "Профиль $profile обнаружен"
        else
            log_warning "Профиль $profile не найден: $config_dir/$profile.conf"
            missing_profiles+=("$profile")
        fi
    done
    
    if [[ ${#missing_profiles[@]} -gt 0 ]]; then
        log_warning "Отсутствуют профили: ${missing_profiles[*]}"
        log_info "Создайте недостающие конфигурации в $config_dir/"
        log_info "Пример конфигурации:"
        echo ""
        echo "$sample_config"
        echo ""
    fi
    
    return 0
}

setup_desktop_integration() {
    log_info "Настройка интеграции с рабочим столом..."
    
    local desktop_dir="$HOME/.local/share/applications"
    local desktop_path="$desktop_dir/$DESKTOP_FILE"
    
    # Создаем директорию если не существует
    mkdir -p "$desktop_dir"
    
    # Создаем .desktop файл
    cat > "$desktop_path" << EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=WireGuard Manager
Comment=GUI для управления профилями WireGuard
Exec=$SCRIPT_DIR/run.sh
Icon=network-wireless
Terminal=false
Categories=Network;System;
Keywords=wireguard;vpn;network;security;
StartupNotify=true
EOF
    
    if [[ $? -eq 0 ]]; then
        log_success "Файл .desktop создан: $desktop_path"
        
        # Делаем исполняемым
        chmod +x "$desktop_path"
        
        # Обновляем кэш приложений
        if command -v update-desktop-database >/dev/null 2>&1; then
            update-desktop-database "$desktop_dir"
            log_success "Кэш приложений обновлен"
        fi
    else
        log_error "Ошибка создания .desktop файла"
        return 1
    fi
    
    return 0
}

setup_binary_symlink() {
    log_info "Настройка симлинка для глобального запуска..."
    
    local bin_dir="$HOME/.local/bin"
    local symlink_path="$bin_dir/wg-manager"
    
    # Создаем директорию если не существует
    mkdir -p "$bin_dir"
    
    # Создаем симлинк
    if [[ -L "$symlink_path" ]]; then
        rm "$symlink_path"
    fi
    
    ln -sf "$SCRIPT_DIR/run.sh" "$symlink_path"
    
    if [[ $? -eq 0 ]]; then
        log_success "Симлинк создан: $symlink_path -> $SCRIPT_DIR/run.sh"
        
        # Добавляем в PATH если еще нет
        if [[ ":$PATH:" != *":$bin_dir:"* ]]; then
            log_info "Добавьте $bin_dir в переменную PATH для глобального доступа"
            echo "Добавьте в ~/.bashrc или ~/.zshrc:"
            echo "  export PATH=\"\$PATH:$bin_dir\""
        fi
    else
        log_warning "Не удалось создать симлинк"
    fi
    
    return 0
}

run_tests() {
    log_info "Запуск тестов..."
    
    cd "$SCRIPT_DIR"
    
    if python3 -m pytest tests/ -v --cov=wg_manager --cov-report=term-missing; then
        log_success "Все тесты пройдены успешно"
        return 0
    else
        log_warning "Некоторые тесты не пройдены"
        return 1
    fi
}

show_summary() {
    echo ""
    echo "=========================================="
    echo "    $APP_NAME - Установка завершена"
    echo "=========================================="
    echo ""
    echo "Установленные компоненты:"
    echo "  ✓ Системные зависимости"
    echo "  ✓ Python зависимости"
    echo "  ✓ PolicyKit политики"
    echo "  ✓ Директории логов"
    echo "  ✓ Интеграция с рабочим столом"
    echo "  ✓ Симлинк для глобального запуска"
    echo ""
    echo "Способы запуска:"
    echo "  1. Из директории приложения: ./run.sh"
    echo "  2. Глобально (если .local/bin в PATH): wg-manager"
    echo "  3. Из меню приложений: WireGuard Manager"
    echo ""
    echo "Дополнительные действия:"
    echo "  1. Убедитесь, что профили WireGuard созданы в /etc/wireguard/"
    echo "  2. Проверьте права на чтение /etc/wireguard/*.conf"
    echo "  3. Для отладки используйте: ./run.sh --debug"
    echo ""
    echo "Документация:"
    echo "  См. README.md для подробной информации"
    echo ""
}

main() {
    echo "=========================================="
    echo "    $APP_NAME - Установка"
    echo "=========================================="
    echo ""
    
    # Проверяем, не запущен ли скрипт от root
    check_root
    
    # Устанавливаем системные зависимости
    if ! install_system_dependencies; then
        log_error "Ошибка установки системных зависимостей"
        exit 1
    fi
    
    # Устанавливаем Python зависимости
    if ! install_python_dependencies; then
        log_warning "Ошибка установки Python зависимостей (продолжаем)"
    fi
    
    # Настраиваем PolicyKit
    if ! setup_policykit; then
        log_warning "Ошибка настройки PolicyKit (продолжаем)"
    fi
    
    # Настраиваем директории логов
    if ! setup_log_directories; then
        log_error "Ошибка настройки директорий логов"
        exit 1
    fi
    
    # Проверяем конфигурации WireGuard
    check_wireguard_configs
    
    # Настраиваем интеграцию с рабочим столом
    if ! setup_desktop_integration; then
        log_warning "Ошибка настройки интеграции с рабочим столом (продолжаем)"
    fi
    
    # Настраиваем симлинк для глобального запуска
    setup_binary_symlink
    
    # Запускаем тесты
    echo ""
    read -p "Запустить тесты? [Y/n] " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]] || [[ -z $REPLY ]]; then
        run_tests || true
    fi
    
    # Показываем итоговую информацию
    show_summary
    
    log_success "Установка завершена успешно!"
    echo ""
}

# Запускаем главную функцию
main "$@"