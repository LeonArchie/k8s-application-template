# SPDX-License-Identifier: AGPL-3.0-only WITH LICENSE-ADDITIONAL
# Copyright (C) 2025 Петунин Лев Михайлович

from k8s.healthz import healthz_bp
from k8s.readyz import readyz_bp
from handlers.error_handlers import (
    not_found,
    internal_server_error,
    not_implemented,
    bad_gateway,
    service_unavailable,
    gateway_timeout,
    http_version_not_supported
)

def register_blueprints(app):
    """Регистрация всех blueprint'ов в приложении"""
    app.register_blueprint(healthz_bp)
    app.register_blueprint(readyz_bp)

def register_error_handlers(app):
    """Регистрация обработчиков ошибок"""
    app.register_error_handler(404, not_found)
    app.register_error_handler(500, internal_server_error)
    app.register_error_handler(501, not_implemented)
    app.register_error_handler(502, bad_gateway)
    app.register_error_handler(503, service_unavailable)
    app.register_error_handler(504, gateway_timeout)
    app.register_error_handler(505, http_version_not_supported)