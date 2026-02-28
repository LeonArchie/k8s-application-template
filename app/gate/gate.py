# SPDX-License-Identifier: AGPL-3.0-only WITH LICENSE-ADDITIONAL
# Copyright (C) 2025 Петунин Лев Михайлович

"""
Сервис-шлюз для валидации всех входящих запросов.
Проверяет метод запроса, заголовки и структуру тела по схемам из schemas.yaml.
Все пути должны быть описаны в schemas.yaml (регулярными выражениями), иначе запрос блокируется.
"""

import re
import yaml
import json
import logging
from typing import Dict, Any, Optional, List, Pattern
from pathlib import Path
from flask import request, current_app

# Настройка логгера
logger = logging.getLogger(__name__)

# Кэш для загруженных схем
_schemas_cache: Optional[List[Dict[str, Any]]] = None
_compiled_patterns_cache: Dict[str, Pattern] = {}

# Флаг состояния шлюза
_gate_healthy: bool = True
_gate_init_error: Optional[str] = None


class GateValidationError(Exception):
    """Кастомное исключение для ошибок валидации"""
    pass


def load_schemas() -> List[Dict[str, Any]]:
    """
    Загружает схемы валидации из schemas.yaml с кэшированием.
    
    :return: Список правил валидации
    :raises: GateValidationError если файл не найден или некорректен
    """
    global _schemas_cache, _gate_healthy, _gate_init_error
    
    # Возвращаем из кэша, если уже загружено
    if _schemas_cache is not None:
        return _schemas_cache
    
    try:
        # Определяем путь к файлу схем
        current_dir = Path(__file__).parent
        schema_path = current_dir / 'schemas.yaml'
        
        if not schema_path.exists():
            error_msg = f"Файл схем не найден: {schema_path}"
            logger.error(error_msg)
            _gate_healthy = False
            _gate_init_error = error_msg
            raise GateValidationError(error_msg)
        
        # Загружаем и парсим YAML
        with open(schema_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        # Проверяем структуру
        if not isinstance(config, dict) or 'gate' not in config:
            error_msg = "Файл схем должен содержать корневой ключ 'gate'"
            logger.error(error_msg)
            _gate_healthy = False
            _gate_init_error = error_msg
            raise GateValidationError(error_msg)
        
        # Извлекаем правила API
        api_rules = config.get('gate', {}).get('api', [])
        
        if not isinstance(api_rules, list):
            error_msg = "Поле 'gate.api' должно быть списком"
            logger.error(error_msg)
            _gate_healthy = False
            _gate_init_error = error_msg
            raise GateValidationError(error_msg)
        
        # Нормализуем правила
        normalized_rules = []
        for rule in api_rules:
            if isinstance(rule, dict) and 'rule' in rule:
                normalized_rule = normalize_rule(rule['rule'])
                normalized_rule['name'] = rule.get('name', 'unnamed')
                normalized_rules.append(normalized_rule)
        
        # Кэшируем
        _schemas_cache = normalized_rules
        _gate_healthy = True
        _gate_init_error = None
        
        logger.info(f"Загружено {len(normalized_rules)} правил валидации")
        return normalized_rules
        
    except yaml.YAMLError as e:
        error_msg = f"Ошибка парсинга YAML: {str(e)}"
        logger.error(error_msg)
        _gate_healthy = False
        _gate_init_error = error_msg
        raise GateValidationError(error_msg)
    except Exception as e:
        error_msg = f"Неожиданная ошибка при загрузке схем: {str(e)}"
        logger.error(error_msg)
        _gate_healthy = False
        _gate_init_error = error_msg
        raise GateValidationError(error_msg)


def normalize_rule(rule: Any) -> Dict:
    """
    Нормализует правило к единому формату.
    
    :param rule: Исходное правило
    :return: Нормализованное правило
    """
    normalized = {
        'path': rule.get('path', ''),
        'method': rule.get('method', '').upper() if rule.get('method') else None,  # None если метод не указан
        'headers': rule.get('headers', []),
        'body': rule.get('body', [])
    }
    
    # Нормализуем заголовки
    headers = []
    for header in normalized['headers']:
        if isinstance(header, dict):
            headers.append({
                'name': header.get('name', '').lower(),
                'value': header.get('value', '')
            })
    normalized['headers'] = headers
    
    # Нормализуем тело запроса
    body_fields = {}
    for field in normalized['body']:
        if isinstance(field, dict):
            for field_name, pattern in field.items():
                body_fields[field_name] = pattern
    normalized['body'] = body_fields
    
    return normalized


def compile_path_pattern(pattern: str) -> Pattern:
    """
    Компилирует регулярное выражение для пути с кэшированием.
    
    :param pattern: Строка с регулярным выражением
    :return: Скомпилированный паттерн
    """
    if pattern in _compiled_patterns_cache:
        return _compiled_patterns_cache[pattern]
    
    try:
        compiled = re.compile(pattern)
        _compiled_patterns_cache[pattern] = compiled
        return compiled
    except re.error as e:
        logger.error(f"Ошибка компиляции regex '{pattern}': {e}")
        raise GateValidationError(f"Некорректное регулярное выражение: {pattern}")


def find_matching_rule(request_path: str) -> Optional[Dict]:
    """
    Находит правило, соответствующее пути запроса.
    
    :param request_path: Путь запроса
    :return: Правило или None если не найдено
    """
    rules = load_schemas()
    
    for rule in rules:
        path_pattern = rule.get('path', '')
        if not path_pattern:
            continue
        
        compiled_pattern = compile_path_pattern(path_pattern)
        if compiled_pattern.match(request_path):
            logger.debug(f"Найдено правило '{rule.get('name')}' для пути {request_path}")
            return rule
    
    logger.debug(f"Правило не найдено для пути: {request_path}")
    return None


def validate_method(allowed_method: Optional[str], request_method: str) -> bool:
    """
    Проверяет разрешен ли метод запроса.
    Если метод не указан в правиле - доступ запрещен для любых методов.
    
    :param allowed_method: Разрешенный метод (None если не указан)
    :param request_method: Метод запроса
    :return: True если метод разрешен
    """
    # Если метод не указан в правиле - доступ запрещен
    if allowed_method is None:
        logger.debug("Метод не указан в правиле - доступ запрещен")
        return False
    
    return request_method.upper() == allowed_method.upper()


def validate_headers(expected_headers: List[Dict], request_headers) -> bool:
    """
    Проверяет заголовки запроса.
    
    :param expected_headers: Список ожидаемых заголовков
    :param request_headers: Заголовки запроса
    :return: True если все заголовки присутствуют и соответствуют значениям
    """
    for header in expected_headers:
        header_name = header.get('name', '')
        expected_value = header.get('value', '')
        
        # Проверяем наличие заголовка
        if header_name not in request_headers:
            logger.debug(f"Отсутствует обязательный заголовок: {header_name}")
            return False
        
        # Если указано ожидаемое значение, проверяем его
        if expected_value:
            actual_value = request_headers.get(header_name, '')
            if actual_value != expected_value:
                logger.debug(f"Заголовок {header_name} имеет значение '{actual_value}', ожидалось '{expected_value}'")
                return False
    
    return True


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
    # Если тело не ожидается, проверяем что тело пустое
    if not expected_body:
        if actual_body:
            logger.debug("Тело не ожидается, но получены данные")
            return False
        return True
    
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
    Все пути должны быть описаны в schemas.yaml, иначе запрос блокируется.
    При ошибках инициализации шлюза все запросы отклоняются с кодом 504.
    
    :param app: Flask приложение
    :return: Модифицированное приложение
    """
    
    @app.before_request
    def validate_request():
        """Перехватываем и валидируем запрос"""
        global _gate_healthy, _gate_init_error
        
        # Проверяем состояние шлюза
        if not _gate_healthy:
            logger.error(f"Шлюз нездоров: {_gate_init_error}. Запрос {request.path} отклонен с кодом 504")
            return "Gateway initialization failed", 504
        
        try:
            # Получаем путь запроса (без query параметров)
            request_path = request.path
            
            # Находим правило для этого пути
            rule = find_matching_rule(request_path)
            
            # ЕСЛИ ПРАВИЛО НЕ НАЙДЕНО - БЛОКИРУЕМ ЗАПРОС
            if rule is None:
                logger.warning(f"Запрос отклонен: путь {request_path} не описан в schemas.yaml")
                return "", 403
            
            # Проверяем метод запроса
            if not validate_method(rule.get('method'), request.method):
                logger.warning(f"Запрос отклонен: неверный метод {request.method} для {request_path}")
                return "", 403
            
            # Проверяем заголовки
            if not validate_headers(rule.get('headers', []), request.headers):
                logger.warning(f"Запрос отклонен: неверные заголовки для {request_path}")
                return "", 403
            
            # Получаем ожидаемую структуру тела
            expected_body = rule.get('body', {})
            
            # Извлекаем фактическое тело запроса
            actual_body = extract_request_body()
            
            # Проверяем структуру тела
            if not validate_body_structure(expected_body, actual_body):
                logger.warning(f"Запрос отклонен: неверная структура тела для {request_path}")
                logger.debug(f"Ожидалось: {expected_body}, получено: {actual_body}")
                return "", 403
            
            # Если все проверки пройдены, добавляем информацию в контекст
            if not hasattr(current_app, 'gate_context'):
                current_app.gate_context = {}
            
            current_app.gate_context['validated'] = True
            current_app.gate_context['rule'] = rule.get('name')
            
            logger.info(f"Запрос {request_path} успешно прошел валидацию по правилу '{rule.get('name')}'")
            return None
            
        except GateValidationError as e:
            logger.error(f"Ошибка валидации: {e}")
            return "Gateway validation error", 504
        except Exception as e:
            logger.error(f"Неожиданная ошибка при валидации запроса: {str(e)}")
            return "Internal gateway error", 504
    
    return app


def init_gate(app):
    """
    Инициализирует шлюз для приложения.
    
    :param app: Flask приложение
    """
    global _gate_healthy, _gate_init_error
    
    logger.info("Инициализация сервиса-шлюза (gate)")
    
    try:
        # Пробуем загрузить схемы при старте
        rules = load_schemas()
        logger.info(f"Успешно загружено {len(rules)} правил валидации")
        
        # Добавляем middleware
        gate_middleware(app)
        
        logger.info("Сервис-шлюз успешно инициализирован")
        
    except GateValidationError as e:
        logger.error(f"Критическая ошибка инициализации шлюза: {e}")
        _gate_healthy = False
        _gate_init_error = str(e)
        # Добавляем middleware даже при ошибке, чтобы он отклонял запросы
        gate_middleware(app)
        logger.warning("Шлюз инициализирован в аварийном режиме - все запросы будут отклоняться с кодом 504")
    except Exception as e:
        logger.error(f"Неожиданная ошибка инициализации шлюза: {str(e)}")
        _gate_healthy = False
        _gate_init_error = str(e)
        gate_middleware(app)
        logger.warning("Шлюз инициализирован в аварийном режиме - все запросы будут отклоняться с кодом 504")
    
    return app


def get_gate_status() -> Dict[str, Any]:
    """
    Возвращает статус шлюза для мониторинга.
    
    :return: Словарь со статусом шлюза
    """
    return {
        'healthy': _gate_healthy,
        'error': _gate_init_error,
        'rules_loaded': len(_schemas_cache) if _schemas_cache else 0
    }