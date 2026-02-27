# SPDX-License-Identifier: AGPL-3.0-only WITH LICENSE-ADDITIONAL
# Copyright (C) 2025 Петунин Лев Михайлович

"""
Сервис-шлюз для валидации всех входящих запросов.
Проверяет метод запроса и структуру тела по схемам из schemas.json.
Все пути должны быть описаны в schemas.json, иначе запрос блокируется.
"""

import json
import re
import logging
from typing import Dict, Any, Optional, List
from pathlib import Path
from flask import request, current_app

# Настройка логгера
logger = logging.getLogger(__name__)

# Кэш для загруженных схем
_schemas_cache: Optional[Dict[str, Any]] = None


class GateValidationError(Exception):
    """Кастомное исключение для ошибок валидации"""
    pass


def load_schemas() -> Dict[str, Any]:
    """
    Загружает схемы валидации из schemas.json с кэшированием.
    
    :return: Словарь со схемами
    :raises: GateValidationError если файл не найден или некорректен
    """
    global _schemas_cache
    
    # Возвращаем из кэша, если уже загружено
    if _schemas_cache is not None:
        return _schemas_cache
    
    try:
        # Определяем путь к файлу схем
        current_dir = Path(__file__).parent
        schema_path = current_dir / 'schemas.json'
        
        if not schema_path.exists():
            error_msg = f"Файл схем не найден: {schema_path}"
            logger.error(error_msg)
            raise GateValidationError(error_msg)
        
        # Загружаем и парсим JSON
        with open(schema_path, 'r', encoding='utf-8') as f:
            schemas = json.load(f)
        
        # Проверяем структуру
        if not isinstance(schemas, dict):
            error_msg = "Файл схем должен содержать объект JSON"
            logger.error(error_msg)
            raise GateValidationError(error_msg)
        
        # Нормализуем схемы для удобства использования
        normalized_schemas = {}
        for path, schema in schemas.items():
            normalized_schemas[path] = normalize_schema(schema)
        
        # Кэшируем
        _schemas_cache = normalized_schemas
        
        logger.info(f"Загружено {len(normalized_schemas)} схем валидации")
        return normalized_schemas
        
    except json.JSONDecodeError as e:
        error_msg = f"Ошибка парсинга JSON: {str(e)}"
        logger.error(error_msg)
        raise GateValidationError(error_msg)
    except Exception as e:
        error_msg = f"Неожиданная ошибка при загрузке схем: {str(e)}"
        logger.error(error_msg)
        raise GateValidationError(error_msg)


def normalize_schema(schema: Any) -> Dict:
    """
    Нормализует схему к единому формату.
    
    :param schema: Исходная схема
    :return: Нормализованная схема
    """
    # Если схема - строка, преобразуем в список
    if isinstance(schema, dict):
        if 'method' in schema:
            if isinstance(schema['method'], str):
                schema['method'] = [schema['method']]
        
        # Убеждаемся, что body есть всегда
        if 'body' not in schema:
            schema['body'] = {}
    
    return schema


def normalize_path(request_path: str) -> str:
    """
    Нормализует путь запроса для поиска в схеме.
    Удаляет trailing slash и приводит к единому формату.
    
    :param request_path: Исходный путь
    :return: Нормализованный путь
    """
    # Удаляем trailing slash если он есть и это не корень
    if request_path != '/' and request_path.endswith('/'):
        request_path = request_path[:-1]
    
    return request_path


def get_schema_for_path(request_path: str) -> Optional[Dict]:
    """
    Получает схему для указанного пути.
    Поддерживает точное совпадение.
    
    :param request_path: Путь запроса
    :return: Схема или None если путь не найден
    """
    schemas = load_schemas()
    normalized_path = normalize_path(request_path)
    
    # Ищем точное совпадение
    if normalized_path in schemas:
        return schemas[normalized_path]
    
    # Логируем отсутствие схемы
    logger.debug(f"Схема не найдена для пути: {normalized_path}")
    return None


def validate_method(allowed_methods: List[str], request_method: str) -> bool:
    """
    Проверяет разрешен ли метод запроса.
    
    :param allowed_methods: Список разрешенных методов
    :param request_method: Метод запроса
    :return: True если метод разрешен
    """
    return request_method.upper() in [m.upper() for m in allowed_methods]


def validate_field(value: Any, pattern: str) -> bool:
    """
    Проверяет значение поля по regex-паттерну.
    
    :param value: Значение поля
    :param pattern: Regex-паттерн
    :return: True если значение соответствует паттерну
    """
    try:
        # Преобразуем значение в строку для проверки
        str_value = str(value) if value is not None else ""
        return bool(re.match(pattern, str_value))
    except (TypeError, re.error) as e:
        logger.debug(f"Ошибка проверки паттерна: {e}")
        return False


def validate_body_structure(expected_body: Dict, actual_body: Dict) -> bool:
    """
    Проверяет структуру тела запроса.
    - Все ожидаемые поля должны присутствовать
    - Не должно быть лишних полей
    - Каждое поле должно соответствовать паттерну
    
    :param expected_body: Ожидаемая структура тела
    :param actual_body: Фактическое тело запроса
    :return: True если структура соответствует
    """
    # Проверяем наличие всех обязательных полей и отсутствие лишних
    expected_fields = set(expected_body.keys())
    actual_fields = set(actual_body.keys())
    
    # Если поля не совпадают - ошибка
    if expected_fields != actual_fields:
        logger.debug(f"Несовпадение полей: ожидаемые {expected_fields}, полученные {actual_fields}")
        return False
    
    # Проверяем каждое поле на соответствие паттерну
    for field_name, pattern in expected_body.items():
        if field_name not in actual_body:
            logger.debug(f"Отсутствует поле: {field_name}")
            return False
        
        if not validate_field(actual_body[field_name], pattern):
            logger.debug(f"Поле {field_name} не соответствует паттерну {pattern}")
            return False
    
    return True


def extract_request_body() -> Dict:
    """
    Извлекает тело запроса в зависимости от Content-Type.
    
    :return: Словарь с данными запроса
    """
    if request.is_json:
        return request.get_json(silent=True) or {}
    elif request.form:
        return request.form.to_dict()
    elif request.data:
        # Пытаемся распарсить как JSON строку
        try:
            return json.loads(request.data.decode('utf-8'))
        except:
            return {}
    else:
        return {}


def gate_middleware(app):
    """
    Middleware для Flask, выполняющий валидацию всех запросов.
    Все пути должны быть описаны в schemas.json, иначе запрос блокируется.
    
    :param app: Flask приложение
    :return: Модифицированное приложение
    """
    
    @app.before_request
    def validate_request():
        """Перехватываем и валидируем запрос"""
        
        # Получаем путь запроса (без query параметров)
        request_path = request.path
        
        # Получаем схему для этого пути
        schema = get_schema_for_path(request_path)
        
        # ЕСЛИ СХЕМА НЕ НАЙДЕНА - БЛОКИРУЕМ ЗАПРОС
        if schema is None:
            logger.warning(f"Запрос отклонен: путь {request_path} не описан в schemas.json")
            # Возвращаем 403 без тела
            return "", 403
        
        # Проверяем метод запроса
        if not validate_method(schema.get('method', []), request.method):
            logger.warning(f"Запрос отклонен: неверный метод {request.method} для {request_path}")
            # Возвращаем 403 без тела
            return "", 403
        
        # Получаем ожидаемую структуру тела
        expected_body = schema.get('body', {})
        
        # Извлекаем фактическое тело запроса
        actual_body = extract_request_body()
        
        # Проверяем структуру тела
        if not validate_body_structure(expected_body, actual_body):
            logger.warning(f"Запрос отклонен: неверная структура тела для {request_path}")
            logger.debug(f"Ожидалось: {expected_body}, получено: {actual_body}")
            # Возвращаем 403 без тела
            return "", 403
        
        # Если все проверки пройдены, добавляем информацию в контекст
        if not hasattr(current_app, 'gate_context'):
            current_app.gate_context = {}
        
        current_app.gate_context['validated'] = True
        current_app.gate_context['schema'] = request_path
        
        logger.info(f"Запрос {request_path} успешно прошел валидацию")
        return None
    
    return app


def init_gate(app):
    """
    Инициализирует шлюз для приложения.
    
    :param app: Flask приложение
    """
    logger.info("Инициализация сервиса-шлюза (gate)")
    
    try:
        # Пробуем загрузить схемы при старте
        schemas = load_schemas()
        logger.info(f"Успешно загружено {len(schemas)} схем валидации")
        
        # Добавляем middleware
        gate_middleware(app)
        
        logger.info("Сервис-шлюз успешно инициализирован")
        
    except GateValidationError as e:
        logger.error(f"Критическая ошибка инициализации шлюза: {e.message}")
        # В продакшне здесь можно решить, останавливать приложение или нет
        raise
    except Exception as e:
        logger.error(f"Неожиданная ошибка инициализации шлюза: {str(e)}")
        raise
    
    return app