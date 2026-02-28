# SPDX-License-Identifier: AGPL-3.0-only WITH LICENSE-ADDITIONAL
# Copyright (C) 2025 Петунин Лев Михайлович

import logging
from pathlib import Path
from typing import Optional
from functools import wraps
import requests

logger = logging.getLogger(__name__)

# Глобальная переменная для хранения MODULE_ID
_module_id: Optional[str] = None


class ModuleIDInjector:
    """
    Класс для инъекции заголовка MODULE-ID во все исходящие requests запросы
    """
    
    def __init__(self, config_filename: str = 'global.conf'):
        self.config_filename = config_filename
        self._module_id: Optional[str] = None
        self._injected = False
    
    def _load_from_config(self) -> str:
        """
        Загружает MODULE_ID из конфигурационного файла
        
        Returns:
            Значение MODULE_ID или пустая строка в случае ошибки
        """
        # Определяем путь к конфигурационному файлу
        current_dir = Path(__file__).parent.parent
        config_file_path = current_dir / self.config_filename
        
        logger.debug(f"Поиск конфигурационного файла: {config_file_path}")
        
        if not config_file_path.exists():
            logger.error(f"Файл конфигурации не найден: {config_file_path}")
            return ""
        
        try:
            with open(config_file_path, 'r', encoding='utf-8') as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    
                    # Пропускаем пустые строки и комментарии
                    if not line or line.startswith('#'):
                        continue
                        
                    if line.startswith('MODULE_ID='):
                        module_id = line.split('=', 1)[1].strip()
                        
                        if module_id:
                            logger.info(f"MODULE_ID успешно загружен из файла {config_file_path.name}")
                            logger.debug(f"Значение MODULE_ID: {self._mask_id(module_id)}")
                            return module_id
                        else:
                            logger.warning(f"Найдена пустая строка MODULE_ID в строке {line_num}")
            
            logger.warning(f"Параметр MODULE_ID не найден в файле {config_file_path.name}")
            return ""
            
        except PermissionError as e:
            logger.error(f"Нет прав на чтение файла конфигурации: {e}")
            return ""
        except UnicodeDecodeError as e:
            logger.error(f"Ошибка кодировки файла конфигурации: {e}")
            return ""
        except Exception as e:
            logger.error(f"Неожиданная ошибка при загрузке MODULE_ID: {e}", exc_info=True)
            return ""
    
    @staticmethod
    def _mask_id(module_id: str) -> str:
        """Маскирует MODULE_ID для безопасного логирования"""
        if len(module_id) > 6:
            return f"{module_id[:3]}...{module_id[-3:]}"
        return module_id
    
    @property
    def module_id(self) -> str:
        """Ленивая загрузка MODULE_ID"""
        if self._module_id is None:
            logger.debug("Инициализация MODULE_ID (первый вызов)")
            self._module_id = self._load_from_config()
            
            if self._module_id:
                logger.info(f"MODULE_ID инициализирован: длина={len(self._module_id)}")
            else:
                logger.warning("MODULE_ID не инициализирован (пустое значение)")
        
        return self._module_id
    
    def inject(self) -> bool:
        """
        Модифицирует стандартные функции requests для автоматического добавления MODULE-ID
        
        Returns:
            bool: True если инъекция выполнена успешно, иначе False
        """
        if self._injected:
            logger.debug("Инъекция уже была выполнена ранее")
            return True
        
        logger.debug("Запуск процедуры инъекции MODULE-ID в requests")
        
        module_id = self.module_id
        
        if not module_id:
            logger.warning("MODULE-ID не найден, инъекция заголовка не выполнена")
            return False
        
        try:
            original_request = requests.Session.request
            
            @wraps(original_request)
            def wrapped_request(session, method, url, **kwargs):
                # Добавляем MODULE-ID к заголовкам
                headers = kwargs.get('headers', {}).copy()
                headers['MODULE-ID'] = module_id
                kwargs['headers'] = headers
                
                # Логируем информацию о запросе (без чувствительных данных)
                logger.debug(f"Добавлен заголовок MODULE-ID к запросу: {method} {url.split('?')[0]}")
                
                return original_request(session, method, url, **kwargs)
            
            # Заменяем метод request в Session
            requests.Session.request = wrapped_request
            self._injected = True
            
            logger.info(f"Глобальная инъекция MODULE-ID успешно выполнена. MODULE-ID: {self._mask_id(module_id)}")
            return True
            
        except AttributeError as e:
            logger.error(f"Ошибка доступа к методу requests.Session.request: {e}")
            return False
        except Exception as e:
            logger.error(f"Неожиданная ошибка при инъекции MODULE-ID: {e}", exc_info=True)
            return False
    
    def reset(self):
        """Сброс состояния инъектора (для тестирования)"""
        self._module_id = None
        self._injected = False


# Создаем глобальный экземпляр для обратной совместимости
_default_injector = ModuleIDInjector()

# Экспортируем функции для обратной совместимости
def get_module_id() -> str:
    """Обратно совместимая функция"""
    return _default_injector.module_id

def inject_module_id_to_requests():
    """Обратно совместимая функция"""
    _default_injector.inject()

# Автоматически выполняем инъекцию при импорте модуля (для обратной совместимости)
logger.debug("Модуль module_id_injector загружается, запуск автоматической инъекции")
inject_module_id_to_requests()
logger.debug("Завершение загрузки модуля module_id_injector")