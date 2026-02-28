# SPDX-License-Identifier: AGPL-3.0-only WITH LICENSE-ADDITIONAL
# Copyright (C) 2025 Петунин Лев Михайлович

import json
import time
import logging
from datetime import datetime
from flask import request
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# Глобальная переменная для хранения времени начала обработки запроса
_request_start_time: Optional[float] = None


class IncomingRequestLogger:
    """Логгер для входящих HTTP запросов в Flask приложении"""
    
    def __init__(self, app=None):
        self.app = app
        if app is not None:
            self.init_app(app)
    
    def init_app(self, app):
        """Инициализация логгера с Flask приложением"""
        app.before_request(self.log_request_info)
        app.after_request(self.log_request_response)
        logger.debug("IncomingRequestLogger инициализирован с Flask приложением")
    
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
                logger.debug(f"Отфильтрован чувствительный заголовок: {k}")
            else:
                filtered[k] = v
        
        return filtered
    
    @staticmethod
    def _get_request_body() -> Optional[Dict[str, Any]]:
        """
        Безопасное извлечение тела запроса
        
        Возвращает:
            Тело запроса или None если извлечь не удалось
        """
        try:
            if not request.data:
                return None
                
            content_type = request.content_type or ''
            
            if 'application/json' in content_type:
                return request.get_json(silent=False)
            elif 'multipart/form-data' in content_type:
                return {'multipart_data': True}
            elif 'application/x-www-form-urlencoded' in content_type:
                return dict(request.form)
            else:
                body = request.data.decode('utf-8', errors='replace')
                return {'raw_body': body[:1000]}
                
        except Exception as e:
            logger.warning(f"Ошибка извлечения тела запроса: {str(e)}", exc_info=True)
            return None
    
    @staticmethod
    def _get_response_body(response) -> Optional[Dict[str, Any]]:
        """
        Безопасное извлечение тела ответа
        
        Параметры:
            response: Объект ответа Flask
            
        Возвращает:
            Тело ответа или None если извлечь не удалось
        """
        try:
            content_type = response.content_type or ''
            
            if 'application/json' in content_type:
                return json.loads(response.get_data(as_text=True))
            elif 'text/' in content_type:
                text = response.get_data(as_text=True)
                return {'text_response': text[:1000]}
            else:
                return None
                
        except Exception as e:
            logger.warning(f"Ошибка извлечения тела ответа: {str(e)}", exc_info=True)
            return None
    
    def log_request_info(self):
        """Логирование входящего запроса"""
        global _request_start_time
        _request_start_time = time.time()
        
        try:
            filtered_headers = self._filter_sensitive_data(dict(request.headers))
            
            request_info = {
                'timestamp': datetime.utcnow().isoformat(),
                'type': 'INCOMING_REQUEST',
                'method': request.method,
                'path': request.path,
                'endpoint': request.endpoint,
                'remote_addr': request.remote_addr,
                'user_agent': request.user_agent.string,
                'headers': filtered_headers,
                'query_params': dict(request.args),
                'content_type': request.content_type,
                'content_length': request.content_length,
            }
            
            request_body = self._get_request_body()
            if request_body:
                request_info['request_body'] = request_body
            
            logger.info(
                f"Входящий запрос:\n{json.dumps(request_info, indent=2, ensure_ascii=False)}",
                extra={'request_info': request_info}
            )
            
        except Exception as e:
            logger.error(f"Ошибка логирования запроса: {str(e)}", exc_info=True)
    
    def log_request_response(self, response):
        """Логирование ответа на запрос"""
        try:
            global _request_start_time
            processing_time = (time.time() - _request_start_time) * 1000 if _request_start_time else None
            
            filtered_request_headers = self._filter_sensitive_data(dict(request.headers))
            filtered_response_headers = self._filter_sensitive_data(dict(response.headers))
            
            response_info = {
                'timestamp': datetime.utcnow().isoformat(),
                'type': 'OUTGOING_RESPONSE',
                'method': request.method,
                'path': request.path,
                'status_code': response.status_code,
                'processing_time_ms': round(processing_time, 2) if processing_time else None,
                'remote_addr': request.remote_addr,
                'request_headers': filtered_request_headers,
                'response_headers': filtered_response_headers,
                'query_params': dict(request.args),
                'response_content_type': response.content_type,
                'response_content_length': response.content_length,
            }
            
            request_body = self._get_request_body()
            if request_body:
                response_info['request_body'] = request_body
                
            response_body = self._get_response_body(response)
            if response_body:
                response_info['response_body'] = response_body
            
            # Логирование в зависимости от статуса ответа
            log_level = logger.info
            if response.status_code >= 500:
                log_level = logger.error
                message = f"Ошибка сервера:\n{json.dumps(response_info, indent=2, ensure_ascii=False)}"
            elif response.status_code >= 400:
                log_level = logger.warning
                message = f"Ошибка клиента:\n{json.dumps(response_info, indent=2, ensure_ascii=False)}"
            else:
                message = f"Успешный ответ:\n{json.dumps(response_info, indent=2, ensure_ascii=False)}"
            
            log_level(message, extra={'response_info': response_info})
                
        except Exception as e:
            logger.error(f"Ошибка логирования ответа: {str(e)}", exc_info=True)
        
        return response