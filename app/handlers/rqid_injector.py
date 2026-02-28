# SPDX-License-Identifier: AGPL-3.0-only WITH LICENSE-ADDITIONAL
# Copyright (C) 2025 Петунин Лев Михайлович

import logging
import uuid
from functools import wraps
import requests

logger = logging.getLogger(__name__)


class RQIDInjector:
    """
    Класс для инъекции заголовка rqid (UUID) во все исходящие requests запросы
    """
    
    def __init__(self):
        self._injected = False
    
    def _generate_rqid(self) -> str:
        """
        Генерирует новый UUID для rqid
        
        Returns:
            Строка с UUID
        """
        return str(uuid.uuid4())
    
    def inject(self) -> bool:
        """
        Модифицирует стандартные функции requests для автоматического добавления rqid
        
        Returns:
            bool: True если инъекция выполнена успешно, иначе False
        """
        if self._injected:
            logger.debug("Инъекция уже была выполнена ранее")
            return True
        
        logger.debug("Запуск процедуры инъекции rqid в requests")
        
        try:
            original_request = requests.Session.request
            
            @wraps(original_request)
            def wrapped_request(session, method, url, **kwargs):
                # Генерируем новый UUID для каждого запроса
                rqid_value = self._generate_rqid()
                
                # Добавляем rqid к заголовкам
                headers = kwargs.get('headers', {}).copy()
                headers['rqid'] = rqid_value
                kwargs['headers'] = headers
                
                # Логируем информацию о запросе
                log_url = url.split('?')[0]  # Убираем query параметры из лога
                logger.debug(f"Добавлен заголовок rqid [{rqid_value}] к запросу: {method} {log_url}")
                
                return original_request(session, method, url, **kwargs)
            
            # Заменяем метод request в Session
            requests.Session.request = wrapped_request
            self._injected = True
            
            logger.info("Глобальная инъекция rqid успешно выполнена (автоматическая генерация UUID для каждого запроса)")
            return True
            
        except AttributeError as e:
            logger.error(f"Ошибка доступа к методу requests.Session.request: {e}")
            return False
        except Exception as e:
            logger.error(f"Неожиданная ошибка при инъекции rqid: {e}", exc_info=True)
            return False
    
    def reset(self):
        """Сброс состояния инъектора (для тестирования)"""
        self._injected = False


# Создаем глобальный экземпляр
_default_injector = RQIDInjector()


def inject_rqid() -> bool:
    """
    Выполняет инъекцию rqid в requests
    
    Returns:
        bool: True если инъекция выполнена успешно
    """
    return _default_injector.inject()


# Автоматически выполняем инъекцию при импорте модуля
logger.debug("Модуль rqid_injector загружается, запуск автоматической инъекции")
inject_rqid()
logger.debug("Завершение загрузки модуля rqid_injector")