from flask import Blueprint, jsonify, render_template, request
from jinja2 import TemplateNotFound
from werkzeug.exceptions import HTTPException

from constants import HTML_CONTENT_TYPE, JSON_CONTENT_TYPE
from logger import init_logger

errors_bp = Blueprint(name="errors", import_name=__name__)

logger = init_logger()


def check_is_request_api() -> bool:
    """
    Проверяет тип запроса.
    Возвращает True если это, скорее всего, API/JSON запрос.
    Дополнительно учитываем request.is_json.
    """
    # если клиент явно прислал JSON body
    if request.is_json:
        return True

    # Преференции Accept: если json предпочтительнее html
    best = request.accept_mimetypes.best_match([JSON_CONTENT_TYPE, HTML_CONTENT_TYPE])
    return best == JSON_CONTENT_TYPE


def format_json_error_response(error: HTTPException) -> dict:
    """
    Форматирует ошибки для JSON-ответа
    """
    # защитимся если поля отсутствуют
    code = getattr(error, "code", 500)
    name = getattr(error, "name", "Internal Server Error")
    description = getattr(error, "description", str(error))
    return {"status_code": code, "name": name, "description": description}


@errors_bp.app_errorhandler(HTTPException)
def exception_handler(error):
    """
    Универсальный обработчик http ошибок.
    Для API -> JSON.
    Для браузера -> пытаемся specific -> generic -> 500 -> JSON.
    """
    code = getattr(error, "code", 500)
    name = getattr(error, "name", "Internal Server Error")
    description = getattr(error, "description", str(error))

    logger.error(
        "http-exception",
        status_code=code or "UNKNOWN",
        name=name,
        description=description,
        method=request.method,
        url=request.url,
    )

    json_body = {"status_code": code, "name": name, "description": description}

    # Если это API — сразу JSON
    if check_is_request_api():
        return jsonify(json_body), code

    try:
        return (
            render_template(
                "errors/generic.html", code=code, name=name, description=description
            ),
            code,
        )
    except TemplateNotFound:
        logger.debug("Generic error template errors/generic.html not found")

    # в крайнем случае — JSON fallback
    logger.warning(
        "No HTML error template found; returning JSON fallback for status %s", code
    )
    return jsonify(json_body), code
