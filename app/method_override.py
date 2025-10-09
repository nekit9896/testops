import io
import logging
import re

from flask import request

from constants import ALLOWED_OVERRIDE_METHODS

logger = logging.getLogger(__name__)


def init_method_override(app):
    """
    WSGI-middleware: поддержка method override для HTML-форм (hidden field _method)
    и заголовка X-HTTP-Method-Override. Выполняется ДО маршрутизации.
    """
    orig_app = app.wsgi_app  # <-- обязательно сохраняем оригинал, иначе будет рекурсия

    def middleware(environ, start_response):
        try:
            method = environ.get("REQUEST_METHOD", "").upper()
            if method == "POST":
                override = None

                # 1) Сначала заголовок X-HTTP-Method-Override
                header_override = environ.get("HTTP_X_HTTP_METHOD_OVERRIDE")
                if header_override:
                    override = header_override.strip().upper()

                # 2) Если не в заголовке — попробуем найти в теле (urlencoded или multipart)
                if not override:
                    content_type = environ.get("CONTENT_TYPE", "")
                    # проверяем, что тело формовое
                    is_form_like = content_type.startswith(
                        "application/x-www-form-urlencoded"
                    ) or content_type.startswith("multipart/form-data")

                    try:
                        content_length = int(environ.get("CONTENT_LENGTH") or 0)
                    except Exception:
                        content_length = 0

                    if content_length > 0 and is_form_like:
                        wsgi_input = environ.get("wsgi.input")
                        if wsgi_input is not None:
                            body = wsgi_input.read(content_length)
                            # сразу восстановим поток (чтобы Flask мог его прочитать позже)
                            environ["wsgi.input"] = io.BytesIO(body)

                            # 2.a попробуем извлечь из urlencoded: _method=PUT
                            m = re.search(rb"_method=([^&\r\n]+)", body)
                            if m:
                                try:
                                    override = (
                                        m.group(1)
                                        .decode("utf-8", errors="ignore")
                                        .strip()
                                        .upper()
                                    )
                                except Exception:
                                    override = None
                            else:
                                # 2.b пробуем простой multipart-паттерн: name="_method" \r\n\r\n value
                                m2 = re.search(
                                    rb'name="?_method"?\r\n\r\n([^\r\n]+)', body
                                )
                                if m2:
                                    try:
                                        override = (
                                            m2.group(1)
                                            .decode("utf-8", errors="ignore")
                                            .strip()
                                            .upper()
                                        )
                                    except Exception:
                                        override = None
                        # если wsgi.input отсутствует — ничего не делаем
                # проверим и применим override
                if override:
                    if override in ALLOWED_OVERRIDE_METHODS:
                        environ["REQUEST_METHOD"] = override
                        logger.debug(
                            "method-override: overridden to %s for %s",
                            override,
                            environ.get("PATH_INFO"),
                        )
                    else:
                        logger.warning(
                            "method-override: unsupported override attempted: %s",
                            override,
                        )
        except Exception:
            # не даём middleware ломать приложение — логируем и продолжаем
            logger.exception("method-override middleware: unexpected error")

        # вызывaем оригинальный wsgi_app (а не app.wsgi_app — иначе рекурсия)
        return orig_app(environ, start_response)

    # оборачиваем
    app.wsgi_app = middleware


def payload_from_form_or_json():
    """
    Возвращает payload, пригодный для create_test_case/update_test_case.
    - если запрос JSON -> вернём request.get_json()
    - иначе попытаемся построить payload из request.form (urlencoded или multipart).
    Поддерживает:
      - поля name, preconditions, description, expected_result
      - tags: строка "a, b" -> ["a","b"]
      - suites / suite_links: строка "S1, S2" -> [{'suite_name':'S1'}, ...]
      - steps: поля вида steps[0][action], steps[0][expected], steps[1][action] ...
        -> преобразуем в [{"position":1,"action":...,"expected":...}, ...]
    """
    if request.is_json:
        return request.get_json(silent=True)

    form = request.form or {}
    payload = {}

    # simple text fields
    for f in ("name", "preconditions", "description", "expected_result"):
        if f in form:
            payload[f] = form.get(f)

    # tags: support comma-separated
    tags_raw = form.get("tags")
    if tags_raw is not None:
        tags = [t.strip() for t in tags_raw.split(",") if t.strip()]
        payload["tags"] = tags

    # suites / suite_links: accept comma-separated names -> suite_links with suite_name
    suites_raw = form.get("suite_links") or form.get("suites")
    if suites_raw:
        suites = [s.strip() for s in suites_raw.split(",") if s.strip()]
        payload["suite_links"] = [{"suite_name": s} for s in suites]

    # steps parsing
    # collect keys like steps[0][action]
    steps_regex = re.compile(r"^steps\[(\d+)\]\[(action|expected|position)\]$")
    steps_map = {}
    for key, val in form.items():
        m = steps_regex.match(key)
        if not m:
            continue
        idx = int(m.group(1))
        field = m.group(2)
        if idx not in steps_map:
            steps_map[idx] = {}
        # position may be provided as string
        if field == "position":
            try:
                steps_map[idx][field] = int(val)
            except Exception:
                steps_map[idx][field] = None
        else:
            steps_map[idx][field] = val

    if steps_map:
        # convert to ordered list by index and set position defaults if missing
        steps_list = []
        for i in sorted(steps_map.keys()):
            s = steps_map[i]
            steps_list.append(
                {
                    # if position provided use it, otherwise set automatic by list order
                    "position": s.get("position"),
                    "action": s.get("action", "") or "",
                    "expected": s.get("expected", "") or "",
                }
            )
        payload["steps"] = steps_list

    return payload if payload else None
