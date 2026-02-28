# SPDX-License-Identifier: AGPL-3.0-only WITH LICENSE-ADDITIONAL
# Copyright (C) 2025 Петунин Лев Михайлович

import threading
from flask import Flask

from handlers.gate import init_gate 
from handlers.module_id_injector import ModuleIDInjector
from handlers.rqid_injector import RQIDInjector
from handlers.incoming_logger import IncomingRequestLogger
from handlers.outgoing_logger import OutgoingRequestLogger
from maintenance.logging_config import setup_logging
from maintenance.config_read import get_config_reader 
from maintenance.database_connector import initialize_database
from maintenance.migration import run_migrations
from maintenance.app_blueprint import register_blueprints, register_error_handlers

logger = setup_logging()

def create_app():
    """Создание и инициализация Flask приложения"""
    app = Flask(__name__)
    
    # Инициализация логгеров
    incoming_logger = IncomingRequestLogger(app)
    outgoing_logger = OutgoingRequestLogger()
    
    # Сохраняем логгеры в конфигурации приложения для доступа из других модулей
    app.config['INCOMING_LOGGER'] = incoming_logger
    app.config['OUTGOING_LOGGER'] = outgoing_logger
    
    # ИНИЦИАЛИЗАЦИЯ ШЛЮЗА - ДОЛЖНА БЫТЬ ДО ВСЕХ ДРУГИХ КОМПОНЕНТОВ
    # Чтобы перехватывает запросы до их обработки   
    init_gate(app)
    
    # Инициализация компонентов приложения
    initialize_components()
    
    # Запуск миграций в фоновом режиме
    start_migrations_background()
    
    # Регистрация blueprint'ов
    register_blueprints(app)

    # Регистрация обработчиков ошибок
    register_error_handlers(app)
    
    logger.info("Приложение успешно инициализировано")
    return app

def initialize_components():
    """Инициализация всех компонентов приложения"""
    try:
        config_reader = get_config_reader()
        logger.info("ConfigReader успешно инициализирован")
    except Exception as e:
        logger.error(f"Ошибка инициализации ConfigReader: {e}")

    try:
        logger.info("Инициализация базы данных...")
        initialize_database()
        logger.info("База данных успешно инициализирована")
    except Exception as e:
        logger.error(f"Ошибка инициализации базы данных: {e}")

def start_migrations_background():
    """Запуск миграций в фоновом режиме"""
    def run_migrations_background():
        try:
            logger.info("Запуск миграций базы данных...")
            applied_migrations = run_migrations()
            if applied_migrations:
                logger.info(f"Миграции успешно применены: {applied_migrations}")
            else:
                logger.info("Нет новых миграций для применения")
        except Exception as e:
            logger.error(f"Ошибка выполнения миграций: {e}")

    migration_thread = threading.Thread(target=run_migrations_background, daemon=True)
    migration_thread.start()