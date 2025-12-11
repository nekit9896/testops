"""
Helpers для partial rendering страницы тест-кейсов.

Содержит функции для AJAX-загрузки частей страницы без полной перезагрузки.
"""

from __future__ import annotations

from typing import Optional

import flask

from helpers import testcase_helpers as tc_help
from logger import init_logger

logger = init_logger()


def get_testcase_detail_context(
    test_case_id: Optional[int] = None,
    create_mode: bool = False,
    include_deleted: bool = False,
) -> dict:
    """
    Подготавливает контекст для partial template детальной панели тест-кейса.

    Args:
        test_case_id: ID тест-кейса для редактирования (None если create_mode=True)
        create_mode: Режим создания нового тест-кейса
        include_deleted: Показывать удалённые тест-кейсы

    Returns:
        dict с ключами:
            - selected_case: объект TestCase или None
            - create: bool - режим создания
    """
    selected_case = None

    if not create_mode and test_case_id:
        try:
            selected_case = tc_help.get_test_case_by_id(
                test_case_id, include_deleted=include_deleted
            )
        except tc_help.NotFoundError:
            logger.warning(f"TestCase id={test_case_id} не найден")
            selected_case = None
        except Exception as e:
            logger.exception(
                f"Ошибка при получении TestCase id={test_case_id}", exc_info=e
            )
            selected_case = None

    return {
        "selected_case": selected_case,
        "create": create_mode,
    }


def render_testcase_detail_partial(
    test_case_id: Optional[int] = None,
    create_mode: bool = False,
    include_deleted: bool = False,
) -> str:
    """
    Рендерит partial HTML для детальной панели тест-кейса.

    Args:
        test_case_id: ID тест-кейса для редактирования
        create_mode: Режим создания нового тест-кейса
        include_deleted: Показывать удалённые тест-кейсы

    Returns:
        Строка с HTML содержимым partial template
    """
    context = get_testcase_detail_context(
        test_case_id=test_case_id,
        create_mode=create_mode,
        include_deleted=include_deleted,
    )

    return flask.render_template(
        "partials/testcase_detail.html",
        **context,
    )
