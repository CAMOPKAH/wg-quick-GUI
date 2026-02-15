#!/bin/bash
#
# Скрипт запуска WireGuard Manager
# Проверяет зависимости и запускает приложение
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_NAME="WireGuard Manager"
VERSION="1.0.0"

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

check_dependencies() {
    log_info "Проверка зависимостей..."
    
    local missing_deps=()
    
    # Проверка Python 3.10+
    if command -v python3 >/dev/null 2>&1; then
        python_version=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
        if [[ $(echo "$python_version >= 3.10" | bc -l 2>/dev/null) -eq 1 ]]; then
            log_success "Python $python_version обнаружен"
        else
            log_error "Требуется Python 3.10+, обнаружен $python_version"
            missing_deps+=("python3 (>=3.10)")
        fi
    else
        log_error "Python3 не обнаружен"
        missing_deps+=("python3")
    fi
    
    # Проверка pip
    if command -v pip3 >/dev/null 2>&1; then
        log_success "pip3 обнаружен"
    else
        log_warning "pip3 не обнаружен, попытка установки через apt"
        missing_deps+=("python3-pip")
    fi
    
    # Проверка wireguard-tools
    if command -v wg >/dev/null 2>&1 && command -v wg-quick >/dev/null 2>&1; then
        log_success "wireguard-tools обнаружены"
    else
        log_error "wireguard-tools не обнаружены"
        missing_deps+=("wireguard-tools")
    fi
    
    # Проверка PolicyKit
    if command -v pkexec >/dev/null 2>&1; then
        log_success "PolicyKit обнаружен"
    else
        log_error "PolicyKit (pkexec) не обнаружен"
        missing_deps+=("policykit-1")
    fi
    
    # Проверка Python пакетов
    local python_packages=("gi" "sys" "os" "subprocess" "threading" "logging" "pathlib" "datetime")
    
    for package in "${python_packages[@]}"; do
        if python3 -c "import $package" 2>/dev/null; then
            log_success "Python модуль '$package' обнаружен"
        else
            case $package in
                "gi")
                    log_error "Python модуль 'gi' (PyGObject) не обнаружен"
                    missing_deps+=("python3-gi")
                    ;;
                *)
                    log_error "Python модуль '$package' не обнаружен"
                    missing_deps+=("python3-$package")
                    ;;
            esac
        fi
    done
    
    if [[ ${#missing_deps[@]} -gt 0 ]]; then
        log_error "Обнаружены отсутствующие зависимости:"
        for dep in "${missing_deps[@]}"; do
            echo "  - $dep"
        done
        echo ""
        log_info "Запустите ./install.sh для автоматической установки зависимостей"
        return 1
    fi
    
    log_success "Все зависимости удовлетворены"
    return 0
}

create_log_directories() {
    log_info "Создание директорий для логов..."
    
    local log_dir="$HOME/.local/share/wg-manager"
    
    if [[ ! -d "$log_dir" ]]; then
        mkdir -p "$log_dir"
        log_success "Создана директория логов: $log_dir"
    else
        log_info "Директория логов уже существует: $log_dir"
    fi
    
    # Создаем файлы логов если их нет
    touch "$log_dir/wg-manager.log" 2>/dev/null || true
    touch "$log_dir/errors.log" 2>/dev/null || true
    
    # Устанавливаем правильные права
    chmod 644 "$log_dir/wg-manager.log" 2>/dev/null || true
    chmod 644 "$log_dir/errors.log" 2>/dev/null || true
    
    log_success "Директории логов настроены"
}

check_wireguard_configs() {
    log_info "Проверка конфигураций WireGuard..."
    
    local config_dir="/etc/wireguard"
    local required_profiles=("App" "bomBox" "usa")
    local missing_configs=()
    
    if [[ ! -d "$config_dir" ]]; then
        log_warning "Директория $config_dir не существует"
        return 1
    fi
    
    for profile in "${required_profiles[@]}"; do
        local config_file="$config_dir/$profile.conf"
        if [[ -f "$config_file" ]]; then
            log_success "Конфигурация $profile обнаружена: $config_file"
        else
            log_warning "Конфигурация $profile не обнаружена: $config_file"
            missing_configs+=("$profile")
        fi
    done
    
    if [[ ${#missing_configs[@]} -gt 0 ]]; then
        log_warning "Некоторые конфигурации отсутствуют: ${missing_configs[*]}"
        log_warning "Добавьте недостающие конфигурации в $config_dir/"
        return 1
    fi
    
    log_success "Все конфигурации WireGuard обнаружены"
    return 0
}

run_application() {
    local args=()
    
    # Парсим аргументы командной строки
    while [[ $# -gt 0 ]]; do
        case $1 in
            --debug)
                args+=("--debug")
                log_info "Режим отладки включен"
                shift
                ;;
            --log-level=*)
                level="${1#*=}"
                args+=("--log-level=$level")
                log_info "Уровень логирования установлен: $level"
                shift
                ;;
            --no-gui)
                args+=("--no-gui")
                log_info "Режим без GUI включен"
                shift
                ;;
            --help)
                show_help
                exit 0
                ;;
            --version)
                echo "$APP_NAME v$VERSION"
                exit 0
                ;;
            *)
                log_warning "Неизвестный аргумент: $1"
                shift
                ;;
        esac
    done
    
    log_info "Запуск $APP_NAME v$VERSION..."
    
    # Переходим в директорию скрипта
    cd "$SCRIPT_DIR"
    
    # Запускаем приложение
    if python3 -c "import gi; gi.require_version('Gtk', '3.0')" 2>/dev/null; then
        python3 wg-manager.py "${args[@]}"
        local exit_code=$?
    else
        log_error "Не удалось импортировать GTK. Запуск в режиме без GUI..."
        python3 wg-manager.py --no-gui "${args[@]}"
        local exit_code=$?
    fi
    
    if [[ $exit_code -eq 0 ]]; then
        log_success "Приложение завершило работу успешно"
    else
        log_error "Приложение завершило работу с кодом ошибки: $exit_code"
    fi
    
    return $exit_code
}

show_help() {
    cat << EOF
Использование: ./run.sh [ОПЦИИ]

Опции:
  --debug           Включить режим отладки (уровень логов DEBUG)
  --log-level=LEVEL Установить уровень логирования (DEBUG, INFO, WARNING, ERROR, CRITICAL)
  --no-gui          Запустить без графического интерфейса (для CI/тестирования)
  --help            Показать эту справку
  --version         Показать версию приложения

Примеры:
  ./run.sh                    # Запуск с графическим интерфейсом
  ./run.sh --debug            # Запуск с отладкой
  ./run.sh --no-gui           # Запуск без GUI (консольный режим)
  ./run.sh --log-level=DEBUG  # Запуск с детальным логированием

EOF
}

main() {
    echo "=========================================="
    echo "    $APP_NAME - Запуск приложения"
    echo "=========================================="
    echo ""
    
    # Проверяем зависимости
    if ! check_dependencies; then
        log_error "Не удалось проверить зависимости. Запуск невозможен."
        echo ""
        log_info "Вы можете:"
        log_info "1. Установить зависимости вручную"
        log_info "2. Запустить ./install.sh для автоматической установки"
        echo ""
        exit 1
    fi
    
    # Создаем директории логов
    create_log_directories
    
    # Проверяем конфигурации WireGuard (предупреждение, но не ошибка)
    check_wireguard_configs || true
    
    echo ""
    log_info "Все проверки пройдены успешно"
    echo ""
    
    # Запускаем приложение с переданными аргументами
    run_application "$@"
}

# Запускаем главную функцию
main "$@"