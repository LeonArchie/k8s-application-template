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
import time
import uuid
from typing import Dict, Any, Optional, List, Pattern, Union
from pathlib import Path
from flask import request, current_app, g

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
        logger.debug(f"Использование кэшированных схем ({len(_schemas_cache)} правил)")
        return _schemas_cache
    
    start_time = time.time()
    logger.info("Начало загрузки схем валидации из schemas.yaml")
    
    try:
        # Определяем путь к файлу схем
        current_dir = Path(__file__).parent.parent
        schema_path = current_dir / 'schemas.yaml'
        
        if not schema_path.exists():
            error_msg = f"Файл схем не найден: {schema_path}"
            logger.error(error_msg)
            _gate_healthy = False
            _gate_init_error = error_msg
            raise GateValidationError(error_msg)
        
        logger.debug(f"Загрузка файла: {schema_path}")
        
        # Загружаем и парсим YAML
        with open(schema_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        logger.debug("YAML файл успешно загружен")
        
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
        
        logger.debug(f"Найдено {len(api_rules)} правил в конфигурации")
        
        # Нормализуем правила
        normalized_rules = []
        skipped_rules = 0
        
        for idx, rule in enumerate(api_rules):
            if isinstance(rule, dict) and 'rule' in rule:
                try:
                    normalized_rule = normalize_rule(rule['rule'])
                    rule_name = rule.get('name', f'unnamed_{idx}')
                    normalized_rule['name'] = rule_name
                    normalized_rule['rqid'] = rule.get('rule', {}).get('rqid', False)
                    normalized_rules.append(normalized_rule)
                    logger.debug(f"Нормализовано правило '{rule_name}': path='{normalized_rule.get('path')}', method={normalized_rule.get('method')}, rqid={normalized_rule.get('rqid')}, body_type={type(normalized_rule.get('body')).__name__}")
                except Exception as e:
                    logger.warning(f"Ошибка нормализации правила #{idx}: {e}")
                    skipped_rules += 1
            else:
                logger.warning(f"Пропущено некорректное правило #{idx}: отсутствует ключ 'rule'")
                skipped_rules += 1
        
        # Кэшируем
        _schemas_cache = normalized_rules
        _gate_healthy = True
        _gate_init_error = None
        
        load_time = time.time() - start_time
        logger.info(f"Загружено {len(normalized_rules)} правил валидации (пропущено: {skipped_rules}) за {load_time:.3f}с")
        
        # Логируем список всех загруженных путей
        paths_summary = [f"'{r.get('path')}' ({r.get('name')})" for r in normalized_rules]
        logger.debug(f"Доступные пути: {', '.join(paths_summary)}")
        
        return normalized_rules
        
    except yaml.YAMLError as e:
        error_msg = f"Ошибка парсинга YAML: {str(e)}"
        logger.error(error_msg)
        _gate_healthy = False
        _gate_init_error = error_msg
        raise GateValidationError(error_msg)
    except Exception as e:
        error_msg = f"Неожиданная ошибка при загрузке схем: {str(e)}"
        logger.error(error_msg, exc_info=True)
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
        'method': rule.get('method', '').upper() if rule.get('method') else None,
        'headers': rule.get('headers', []) or [],  # Если None, то пустой список
        'body': rule.get('body', []) or []         # Если None, то пустой список
    }
    
    # Нормализуем заголовки - оставляем как есть для строгой проверки
    headers = []
    for header in normalized['headers']:
        if isinstance(header, dict):
            headers.append({
                'name': header.get('name', '').lower(),
                'value': header.get('value', '')
            })
    normalized['headers'] = headers
    
    # Нормализуем тело запроса с учетом новых правил
    body = normalized['body']
    
    # Случай 1: '*' - разрешено любое тело
    if isinstance(body, str) and body == '*':
        normalized['body'] = '*'
        logger.debug("Обнаружен wildcard '*' для тела запроса")
    
    # Случай 2: пустой список или пустое значение - тела быть не должно
    elif not body or (isinstance(body, list) and len(body) == 0):
        normalized['body'] = {}  # Пустой словарь = тело не ожидается
        logger.debug("Обнаружено пустое тело запроса (тело не ожидается)")
    
    # Случай 3: список полей для валидации
    elif isinstance(body, list):
        body_fields = {}
        for field in body:
            if isinstance(field, dict):
                for field_name, pattern in field.items():
                    body_fields[field_name] = pattern
            elif isinstance(field, str):
                # Поддержка простых строковых полей (для обратной совместимости)
                body_fields[field] = '.*'
        normalized['body'] = body_fields
        logger.debug(f"Нормализовано тело запроса с {len(body_fields)} полями")
    
    # Случай 4: что-то другое - считаем невалидным (но оставляем как есть для обработки ошибок позже)
    else:
        logger.warning(f"Неизвестный формат тела запроса: {type(body)}")
        normalized['body'] = body
    
    return normalized


def compile_path_pattern(pattern: str) -> Pattern:
    """
    Компилирует регулярное выражение для пути с кэшированием.
    
    :param pattern: Строка с регулярным выражением
    :return: Скомпилированный паттерн
    """
    if pattern in _compiled_patterns_cache:
        logger.debug(f"Использование кэшированного regex: {pattern}")
        return _compiled_patterns_cache[pattern]
    
    try:
        logger.debug(f"Компиляция regex: {pattern}")
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
    
    logger.debug(f"Поиск правила для пути: {request_path}")
    
    for rule in rules:
        path_pattern = rule.get('path', '')
        if not path_pattern:
            logger.debug(f"Правило '{rule.get('name')}' пропущено: пустой path")
            continue
        
        compiled_pattern = compile_path_pattern(path_pattern)
        if compiled_pattern.match(request_path):
            logger.info(f"Найдено правило '{rule.get('name')}' для пути {request_path} (pattern: {path_pattern})")
            return rule
    
    logger.warning(f"Правило не найдено для пути: {request_path}")
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
    
    result = request_method.upper() == allowed_method.upper()
    if result:
        logger.debug(f"Метод {request_method} соответствует разрешенному {allowed_method}")
    else:
        logger.debug(f"Метод {request_method} не соответствует разрешенному {allowed_method}")
    
    return result


def validate_rqid(expected_rqid: bool, request_headers) -> bool:
    """
    Проверяет наличие и корректность заголовка Rqid.
    
    :param expected_rqid: Флаг необходимости проверки Rqid
    :param request_headers: Заголовки запроса
    :return: True если проверка пройдена или не требуется
    """
    if not expected_rqid:
        logger.debug("Проверка Rqid не требуется")
        return True
    
    logger.debug("Проверка наличия Rqid заголовка")
    
    # Проверяем наличие заголовка Rqid (регистронезависимо)
    rqid_header = None
    for header_name in request_headers.keys():
        if header_name.lower() == 'rqid':
            rqid_header = header_name
            break
    
    if not rqid_header:
        logger.warning("Отсутствует обязательный заголовок Rqid")
        return False
    
    rqid_value = request_headers.get(rqid_header, '')
    logger.debug(f"Найден заголовок Rqid со значением: {rqid_value}")
    
    # Проверяем формат UUID
    try:
        # Пытаемся преобразовать в UUID
        uuid_obj = uuid.UUID(rqid_value)
        # Проверяем, что это строка в формате UUID (с дефисами или без)
        # uuid.UUID принимает оба варианта, поэтому дополнительная проверка не требуется
        logger.debug(f"Rqid имеет корректный формат UUID: {uuid_obj}")
        return True
    except (ValueError, AttributeError, TypeError) as e:
        logger.warning(f"Rqid имеет некорректный формат UUID: {rqid_value}, ошибка: {e}")
        return False


def validate_headers_exact(expected_headers: List[Dict], request_headers) -> bool:
    """
    Строгая проверка заголовков запроса.
    Должен быть ровно один заголовок с правильной парой name:value.
    Если нет name или value у name - запрос отклоняется.
    
    :param expected_headers: Список ожидаемых заголовков (каждый с name и value)
    :param request_headers: Заголовки запроса
    :return: True если есть ровно одно совпадение
    """
    if not expected_headers:
        logger.debug("Проверка заголовков не требуется")
        return True
    
    logger.debug(f"Строгая проверка заголовков: {expected_headers}")
    
    # Собираем все ожидаемые пары name:value
    expected_pairs = {}
    for header in expected_headers:
        name = header.get('name', '').lower()
        value = header.get('value', '')
        
        if not name or not value:
            logger.warning(f"Некорректное правило заголовка: name='{name}', value='{value}'")
            return False
        
        if name not in expected_pairs:
            expected_pairs[name] = []
        expected_pairs[name].append(value)
    
    # Проверяем все заголовки в запросе
    found_match = False
    matched_pair = None
    
    # Сначала проверяем, нет ли лишних заголовков из списка ожидаемых
    # (заголовки не из списка ожидаемых игнорируются)
    for header_name in request_headers.keys():
        header_name_lower = header_name.lower()
        
        # Проверяем только те заголовки, которые есть в ожидаемых
        if header_name_lower in expected_pairs:
            actual_value = request_headers.get(header_name)
            expected_values = expected_pairs[header_name_lower]
            
            # Проверяем значение
            if actual_value in expected_values:
                if found_match:
                    # Нашли второе совпадение - ошибка
                    logger.warning(f"Найдено второе совпадение: заголовок {header_name}={actual_value} (первое было {matched_pair})")
                    return False
                
                # Первое совпадение
                found_match = True
                matched_pair = f"{header_name}={actual_value}"
                logger.debug(f"Найдено совпадение: {matched_pair}")
            else:
                logger.warning(f"Заголовок {header_name} имеет неверное значение: '{actual_value}', ожидалось одно из: {expected_values}")
                return False
    
    # Проверяем результат
    if not found_match:
        logger.warning(f"Не найдено ни одного подходящего заголовка из ожидаемых: {expected_pairs}")
        return False
    
    logger.info(f"Успешная проверка заголовков: найден ровно один подходящий заголовок {matched_pair}")
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
        
        # Маскируем чувствительные данные в логах
        log_value = str_value
        if any(keyword in pattern.lower() for keyword in ['password', 'token', 'secret', 'key']):
            log_value = '***'
        
        logger.debug(f"Проверка поля: значение='{log_value}', паттерн='{pattern}'")
        
        result = bool(re.match(pattern, str_value))
        if not result:
            logger.debug(f"Значение не соответствует паттерну: '{log_value}'")
        
        return result
    except (TypeError, re.error) as e:
        logger.debug(f"Ошибка проверки паттерна: {e}")
        return False


def validate_body_structure(expected_body: Union[Dict, str], actual_body: Dict) -> bool:
    """
    Проверяет структуру тела запроса с учетом новых правил:
    - Если expected_body == '*': разрешено любое тело (проверка пропускается)
    - Если expected_body == {}: тело не должно быть передано
    - Если expected_body - словарь с полями: строгая проверка всех полей
    
    :param expected_body: Ожидаемая структура тела (словарь с полями, пустой словарь или '*')
    :param actual_body: Фактическое тело запроса
    :return: True если структура соответствует
    """
    # Случай 1: '*' - разрешено любое тело
    if expected_body == '*':
        logger.debug("Wildcard '*' обнаружен: любое тело разрешено")
        return True
    
    # Случай 2: пустой словарь - тело не ожидается
    if expected_body == {}:
        if actual_body:
            logger.warning(f"Тело не ожидается, но получены данные: {list(actual_body.keys())}")
            return False
        logger.debug("Тело не ожидается и не получено - OK")
        return True
    
    # Случай 3: словарь с полями - строгая проверка
    if isinstance(expected_body, dict):
        # Проверяем наличие всех обязательных полей и отсутствие лишних
        expected_fields = set(expected_body.keys())
        actual_fields = set(actual_body.keys())
        
        # Если поля не совпадают - ошибка
        if expected_fields != actual_fields:
            missing = expected_fields - actual_fields
            extra = actual_fields - expected_fields
            
            if missing:
                logger.warning(f"Отсутствуют поля: {missing}")
            if extra:
                logger.warning(f"Лишние поля: {extra}")
            
            logger.debug(f"Несовпадение полей: ожидаемые {expected_fields}, полученные {actual_fields}")
            return False
        
        logger.debug(f"Проверка {len(expected_body)} полей тела запроса")
        
        # Проверяем каждое поле на соответствие паттерну
        for field_name, pattern in expected_body.items():
            if field_name not in actual_body:
                logger.warning(f"Отсутствует поле: {field_name}")
                return False
            
            if not validate_field(actual_body[field_name], pattern):
                logger.warning(f"Поле {field_name} не соответствует паттерну {pattern}")
                return False
            
            logger.debug(f"Поле {field_name} прошло проверку")
        
        logger.debug("Все поля тела запроса прошли проверку")
        return True
    
    # Неизвестный формат expected_body
    logger.error(f"Неизвестный формат expected_body: {type(expected_body)}")
    return False


def extract_request_body() -> Dict:
    """
    Извлекает тело запроса в зависимости от Content-Type.
    
    :return: Словарь с данными запроса
    """
    content_type = request.headers.get('Content-Type', 'unknown')
    logger.debug(f"Извлечение тела запроса, Content-Type: {content_type}")
    
    if request.is_json:
        body = request.get_json(silent=True) or {}
        logger.debug(f"JSON тело запроса: {list(body.keys())}")
        return body
    elif request.form:
        body = request.form.to_dict()
        logger.debug(f"Form данные: {list(body.keys())}")
        return body
    elif request.data:
        # Пытаемся распарсить как JSON строку
        try:
            body = json.loads(request.data.decode('utf-8'))
            logger.debug(f"JSON из сырых данных: {list(body.keys())}")
            return body
        except:
            logger.debug("Не удалось распарсить сырые данные как JSON")
            return {}
    else:
        logger.debug("Тело запроса отсутствует")
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
        
        # Сохраняем время начала обработки
        g.start_time = time.time()
        
        # Логируем входящий запрос
        logger.info(f"→ {request.method} {request.path} (IP: {request.remote_addr})")
        
        # Проверяем состояние шлюза
        if not _gate_healthy:
            error_msg = f"Шлюз нездоров: {_gate_init_error}"
            logger.error(f"{error_msg}. Запрос {request.path} отклонен с кодом 504")
            return "Gateway initialization failed", 504
        
        try:
            # Получаем путь запроса (без query параметров)
            request_path = request.path
            
            # Находим правило для этого пути
            rule = find_matching_rule(request_path)
            
            # ЕСЛИ ПРАВИЛО НЕ НАЙДЕНО - БЛОКИРУЕМ ЗАПРОС
            if rule is None:
                logger.warning(f" Запрос отклонен: путь {request_path} не описан в schemas.yaml")
                return "", 403
            
            # Проверяем метод запроса
            if not validate_method(rule.get('method'), request.method):
                logger.warning(f" Запрос отклонен: неверный метод {request.method} для {request_path} (ожидался {rule.get('method')})")
                return "", 403
            
            # Строгая проверка заголовков - ровно одно совпадение
            if not validate_headers_exact(rule.get('headers', []), request.headers):
                logger.warning(f" Запрос отклонен: ошибка проверки заголовков для {request_path}")
                return "", 403
            
            # Проверяем Rqid если требуется
            if not validate_rqid(rule.get('rqid', False), request.headers):
                logger.warning(f" Запрос отклонен: неверный или отсутствующий Rqid для {request_path}")
                return "", 403
            
            # Получаем ожидаемую структуру тела
            expected_body = rule.get('body', {})
            
            # Извлекаем фактическое тело запроса
            actual_body = extract_request_body()
            
            # Проверяем структуру тела
            if not validate_body_structure(expected_body, actual_body):
                logger.warning(f" Запрос отклонен: неверная структура тела для {request_path}")
                if expected_body == '*':
                    logger.debug("Ожидался wildcard '*', но тело не прошло проверку (это сообщение не должно появляться)")
                elif expected_body == {}:
                    logger.debug(f"Ожидалось пустое тело, получено: {list(actual_body.keys()) if actual_body else {}}")
                else:
                    logger.debug(f"Ожидалось: {expected_body}, получено: {list(actual_body.keys()) if actual_body else {}}")
                return "", 403
            
            # Если все проверки пройдены, добавляем информацию в контекст
            if not hasattr(current_app, 'gate_context'):
                current_app.gate_context = {}
            
            current_app.gate_context['validated'] = True
            current_app.gate_context['rule'] = rule.get('name')
            
            # Логируем успешную валидацию
            process_time = time.time() - g.start_time
            logger.info(f" Запрос {request.path} успешно прошел валидацию по правилу '{rule.get('name')}' (обработка: {process_time:.3f}с)")
            return None
            
        except GateValidationError as e:
            logger.error(f" Ошибка валидации: {e}")
            return "Gateway validation error", 504
        except Exception as e:
            logger.error(f" Неожиданная ошибка при валидации запроса: {str(e)}", exc_info=True)
            return "Internal gateway error", 504
    
    @app.after_request
    def log_response(response):
        """Логируем ответ после обработки запроса"""
        if hasattr(g, 'start_time'):
            process_time = time.time() - g.start_time
            logger.info(f"← {response.status_code} ({process_time:.3f}с)")
        else:
            logger.info(f"← {response.status_code}")
        
        return response
    
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
        start_time = time.time()
        rules = load_schemas()
        load_time = time.time() - start_time
        
        logger.info(f" Успешно загружено {len(rules)} правил валидации за {load_time:.3f}с")
        
        # Выводим список правил
        if rules:
            logger.info("Загруженные правила:")
            for rule in rules:
                method = rule.get('method', 'ANY')
                path = rule.get('path', '')
                name = rule.get('name', 'unnamed')
                rqid = rule.get('rqid', False)
                body_type = type(rule.get('body')).__name__
                if rule.get('body') == '*':
                    body_desc = "wildcard '*'"
                elif rule.get('body') == {}:
                    body_desc = "no body"
                elif isinstance(rule.get('body'), dict):
                    body_desc = f"{len(rule.get('body', {}))} fields"
                else:
                    body_desc = str(rule.get('body'))
                logger.info(f"  - {method:7} {path:30} [{name}] (rqid: {rqid}, body: {body_desc})")
        
        # Добавляем middleware
        gate_middleware(app)
        logger.info(" Сервис-шлюз успешно инициализирован")      
        
    except GateValidationError as e:
        logger.error(f" Критическая ошибка инициализации шлюза: {e}")
        _gate_healthy = False
        _gate_init_error = str(e)
        # Добавляем middleware даже при ошибке, чтобы он отклонял запросы
        gate_middleware(app)
        logger.warning(" Шлюз инициализирован в аварийном режиме - все запросы будут отклоняться с кодом 504")
        
    except Exception as e:
        logger.error(f" Неожиданная ошибка инициализации шлюза: {str(e)}", exc_info=True)
        _gate_healthy = False
        _gate_init_error = str(e)
        gate_middleware(app)
        logger.warning(" Шлюз инициализирован в аварийном режиме - все запросы будут отклоняться с кодом 504")
    
    return app


def get_gate_status() -> Dict[str, Any]:
    """
    Возвращает статус шлюза для мониторинга.
    
    :return: Словарь со статусом шлюза
    """
    status = {
        'healthy': _gate_healthy,
        'error': _gate_init_error,
        'rules_loaded': len(_schemas_cache) if _schemas_cache else 0
    }
    
    logger.debug(f"Запрос статуса шлюза: {status}")
    return status