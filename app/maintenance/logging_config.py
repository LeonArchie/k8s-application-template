# SPDX-License-Identifier: AGPL-3.0-only WITH LICENSE-ADDITIONAL
# Copyright (C) 2025 Петунин Лев Михайлович

# Импорт необходимых модулей
import logging  # Стандартный модуль логирования Python
import json     # Для форматирования логов в JSON
import sys      # Для работы с системными потоками ввода/вывода
import os       # Для работы с файловой системой
from datetime import datetime, timezone  # Для временных меток
from typing import Optional

class StructuredFormatter(logging.Formatter):
    """
    Кастомный форматтер для структурированных логов в формате JSON.
    """
    def format(self, record):
        """
        Преобразует запись лога в структурированный JSON-объект.
        
        :param record: Запись лога, содержащая всю информацию о событии
        :return: JSON-строка с структурированными данными лога
        """
        # Базовая структура лога
        log_data = {
            "timestamp": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),  # Время в UTC в ISO-формате
            "level": record.levelname,      # Уровень логирования (INFO, WARNING и т.д.)
            "message": record.getMessage(),  # Текст сообщения
        }
        
        # Если есть информация об исключении, добавляем её в лог
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        
        # Сериализуем в JSON с поддержкой Unicode (ensure_ascii=False)
        return json.dumps(log_data, ensure_ascii=False)

def read_log_level_from_config(config_file_path: Optional[str] = None) -> str:
    """
    Чтение уровня логирования из файла global.conf
    
    :param config_file_path: путь к файлу global.conf (опционально)
    :return: уровень логирования из конфигурации или значение по умолчанию "INFO"
    """
    if config_file_path is None:
        # Определяем путь к файлу global.conf относительно текущего файла
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        config_file_path = os.path.join(base_dir, "global.conf")
    
    default_level = "INFO"
    
    try:
        if not os.path.exists(config_file_path):
            print(f"Предупреждение: Файл конфигурации не найден: {config_file_path}. Используется уровень по умолчанию: {default_level}")
            return default_level
        
        with open(config_file_path, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                
                # Пропускаем комментарии и пустые строки
                if not line or line.startswith('#'):
                    continue
                
                if line.startswith('LOG_LVL='):
                    log_level = line.split('=', 1)[1].strip()
                    
                    # ИСПРАВЛЕНО: Добавлена проверка валидности уровня
                    valid_levels = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
                    if log_level in valid_levels:
                        return log_level
                    else:
                        print(f"Предупреждение: Неизвестный уровень логирования '{log_level}'. Используется уровень по умолчанию: {default_level}")
                        return default_level
        
        # Если дошли до сюда, значит LOG_LVL не найден в файле
        print(f"Информация: LOG_LVL не найден в конфигурации. Используется уровень по умолчанию: {default_level}")
        return default_level
        
    except Exception as e:
        print(f"Ошибка при чтении уровня логирования из конфигурации: {e}. Используется уровень по умолчанию: {default_level}")
        return default_level

def setup_logging(config_file_path: Optional[str] = None):
    """
    Настройка системы логирования для приложения.
    
    :param config_file_path: путь к файлу global.conf (опционально)
    :return: Настроенный root-логгер
    """
    # Получаем root-логгер
    logger = logging.getLogger()
    
    # Читаем уровень логирования из конфигурационного файла
    log_level_str = read_log_level_from_config(config_file_path)
    
    # Преобразуем строковый уровень в константу logging
    log_level_map = {
        'DEBUG': logging.DEBUG,
        'INFO': logging.INFO,
        'WARNING': logging.WARNING,
        'ERROR': logging.ERROR,
        'CRITICAL': logging.CRITICAL
    }
    
    log_level = log_level_map.get(log_level_str, logging.INFO)
    
    # Устанавливаем уровень логирования из конфигурации
    logger.setLevel(log_level)
    
    # Создаем обработчик, который выводит логи в stdout
    # (рекомендуется для Docker/Kubernetes)
    handler = logging.StreamHandler(sys.stdout)
    
    # Устанавливаем наш кастомный форматтер
    handler.setFormatter(StructuredFormatter())
    
    # Очищаем существующие обработчики, если они есть
    # (предотвращает дублирование логов)
    if logger.hasHandlers():
        logger.handlers.clear()
    
    # Добавляем наш обработчик к root-логгеру
    logger.addHandler(handler)
    
    # Логируем успешную настройку логирования
    logger.debug(f"Система логирования настроена. Уровень: {log_level_str}")
    return logger