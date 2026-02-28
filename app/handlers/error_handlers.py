# SPDX-License-Identifier: AGPL-3.0-only WITH LICENSE-ADDITIONAL
# Copyright (C) 2025 Петунин Лев Михайлович

from flask import jsonify

# Существующий обработчик 404
def not_found(error):
    response = jsonify({
        "status": False,
        "code": 404,
        "body": {
            "message": "Not Found"
        }
    })
    response.status_code = 404
    return response

# 500 Internal Server Error
def internal_server_error(error):
    response = jsonify({
        "status": False,
        "code": 500,
        "body": {
            "message": "Internal Server Error",
            "detail": str(error) if str(error) else "An unexpected error occurred"
        }
    })
    response.status_code = 500
    return response

# 501 Not Implemented
def not_implemented(error):
    response = jsonify({
        "status": False,
        "code": 501,
        "body": {
            "message": "Not Implemented",
            "detail": "The server does not support the functionality required to fulfill the request"
        }
    })
    response.status_code = 501
    return response

# 502 Bad Gateway
def bad_gateway(error):
    response = jsonify({
        "status": False,
        "code": 502,
        "body": {
            "message": "Bad Gateway",
            "detail": "Invalid response from upstream server"
        }
    })
    response.status_code = 502
    return response

# 503 Service Unavailable
def service_unavailable(error):
    response = jsonify({
        "status": False,
        "code": 503,
        "body": {
            "message": "Service Unavailable",
            "detail": "The server is temporarily unable to handle the request"
        }
    })
    response.status_code = 503
    return response

# 504 Gateway Timeout
def gateway_timeout(error):
    response = jsonify({
        "status": False,
        "code": 504,
        "body": {
            "message": "Gateway Timeout",
            "detail": "The upstream server failed to respond in time"
        }
    })
    response.status_code = 504
    return response

# 505 HTTP Version Not Supported
def http_version_not_supported(error):
    response = jsonify({
        "status": False,
        "code": 505,
        "body": {
            "message": "HTTP Version Not Supported",
            "detail": "The server does not support the HTTP protocol version used in the request"
        }
    })
    response.status_code = 505
    return response