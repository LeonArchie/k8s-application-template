# SPDX-License-Identifier: AGPL-3.0-only WITH LICENSE-ADDITIONAL
# Copyright (C) 2025 Петунин Лев Михайлович

import json
import time
import logging
from datetime import datetime
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class OutgoingRequestLogger:
    """Логгер для исходящих HTTP запросов (вызовы внешних API)"""
    
    @staticmethod
    def _filter_sensitive_data(headers: Dict[str, str]) -> Dict[str, str]:
        """
        Фильтрация чувствительных данных из заголовков
        
        Параметры:
            headers: Исходные заголовки запроса
            
        Возвращает:
            Заголовки с отфильтрованными чувствительными данными
        """
        sensitive_keys = ['authorization', 'cookie', 'token', 'set-cookie', 
                          'x-api-key', 'api-key', 'auth-token']
        
        filtered = {}
        for k, v in headers.items():
            if any(sensitive in k.lower() for sensitive in sensitive_keys):
                filtered[k] = '***FILTERED***'
            else:
                filtered[k] = v
        
        return filtered
    
    @staticmethod
    def _parse_body(body: Any) -> Any:
        """Парсинг тела запроса/ответа для логирования"""
        if body is None:
            return None
        
        if isinstance(body, dict):
            return body
        elif isinstance(body, str):
            try:
                return json.loads(body)
            except:
                return {'raw_body': body[:1000]}
        else:
            return {'body_type': str(type(body))}
    
    def log_request(self, method: str, url: str, headers: Dict[str, str], 
                    body: Optional[Any] = None):
        """
        Логирование исходящего HTTP запроса
        
        Параметры:
            method: HTTP метод
            url: URL назначения
            headers: Заголовки запроса
            body: Тело запроса
        """
        try:
            filtered_headers = self._filter_sensitive_data(headers)
            
            request_info = {
                'timestamp': datetime.utcnow().isoformat(),
                'type': 'OUTGOING_REQUEST',
                'method': method.upper(),
                'url': url,
                'headers': filtered_headers,
            }
            
            if body:
                request_info['body'] = self._parse_body(body)
            
            logger.info(
                f"Исходящий запрос:\n{json.dumps(request_info, indent=2, ensure_ascii=False)}",
                extra={'outgoing_request': request_info}
            )
            
        except Exception as e:
            logger.error(f"Ошибка логирования исходящего запроса: {str(e)}", exc_info=True)
    
    def log_response(self, url: str, status_code: int, headers: Dict[str, str], 
                     body: Optional[Any] = None, duration_ms: Optional[float] = None):
        """
        Логирование ответа на исходящий запрос
        
        Параметры:
            url: URL назначения
            status_code: HTTP статус ответа
            headers: Заголовки ответа
            body: Тело ответа
            duration_ms: Длительность запроса в миллисекундах
        """
        try:
            filtered_headers = self._filter_sensitive_data(headers)
            
            response_info = {
                'timestamp': datetime.utcnow().isoformat(),
                'type': 'OUTGOING_RESPONSE',
                'url': url,
                'status_code': status_code,
                'headers': filtered_headers,
            }
            
            if duration_ms is not None:
                response_info['duration_ms'] = round(duration_ms, 2)
            
            if body:
                response_info['body'] = self._parse_body(body)
            
            # Логирование в зависимости от статуса
            log_level = logger.info
            if status_code >= 500:
                log_level = logger.error
                message = f"Ошибка сервера при исходящем запросе:\n{json.dumps(response_info, indent=2, ensure_ascii=False)}"
            elif status_code >= 400:
                log_level = logger.warning
                message = f"Ошибка клиента при исходящем запросе:\n{json.dumps(response_info, indent=2, ensure_ascii=False)}"
            else:
                message = f"Успешный ответ на исходящий запрос:\n{json.dumps(response_info, indent=2, ensure_ascii=False)}"
            
            log_level(message, extra={'outgoing_response': response_info})
                
        except Exception as e:
            logger.error(f"Ошибка логирования ответа на исходящий запрос: {str(e)}", exc_info=True)
    
    def log_request_with_timing(self, method: str, url: str, headers: Dict[str, str], 
                                 body: Optional[Any] = None) -> Dict[str, Any]:
        """
        Логирование исходящего запроса с автоматическим замером времени
        
        Возвращает словарь с информацией для последующего логирования ответа
        """
        self.log_request(method, url, headers, body)
        return {
            'url': url,
            'method': method,
            'start_time': time.time()
        }
    
    def log_response_with_timing(self, context: Dict[str, Any], status_code: int,
                                  headers: Dict[str, str], body: Optional[Any] = None):
        """Логирование ответа с использованием контекста от log_request_with_timing"""
        duration_ms = (time.time() - context['start_time']) * 1000
        self.log_response(context['url'], status_code, headers, body, duration_ms)