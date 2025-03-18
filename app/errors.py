from flask import Blueprint, jsonify, render_template, request
from werkzeug.exceptions import HTTPException

from constants import HTML_CONTENT_TYPE, JSON_CONTENT_TYPE
from logger import init_logger

errors_bp = Blueprint(name="errors", import_name=__name__)

logger = init_logger()


def check_is_request_api() -> bool:
    """
    Проверяет тип запроса.
    """
    return (
        request.accept_mimetypes.best_match([JSON_CONTENT_TYPE, HTML_CONTENT_TYPE])
        == JSON_CONTENT_TYPE
    )


def format_json_error_response(error: HTTPException) -> dict:
    """
    Форматирует ошибки для JSON-ответа.
    """
    return {
        "status_code": error.code,
        "name": error.name,
        "description": error.description,
    }


def render_error_html_template(status_code: int) -> str:
    """
    Получает путь к HTML-шаблону ошибок и рендерит его.
    """
    return render_template(f"errors/{status_code}.html")


@errors_bp.app_errorhandler(HTTPException)
def exception_handler(error):
    """
    Универсальный обработчик http ошибок
    """
    logger.error(
        "http-exception",
        status_code=error.code or "UNKNOWN",
        name=error.name,
        description=error.description,
        method=request.method,
        url=request.url,
    )
    # Проверяет наличие кода ошибки
    if error.code:
        # Если тип запроса API то в ответе будет json
        if check_is_request_api():
            response = format_json_error_response(error)
            return jsonify(response), error.code

        return render_error_html_template(error.code), error.code
    else:
        # Возвращает неизвестную ошибку обратно, для дефолтного обработчика
        return error
