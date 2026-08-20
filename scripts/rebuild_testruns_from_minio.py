"""
Восстанавливает строки testrun_results из объектов бакета allure-results-bucket.

Скрипт группирует объекты по run_name и создаёт запись в PostgreSQL,
только если такого run_name ещё нет.

Запуск из /app в контейнере приложения (PYTHONPATH=/app):
    python scripts/rebuild_testruns_from_minio.py --dry-run
    python -m scripts.rebuild_testruns_from_minio --dry-run
"""

from __future__ import annotations

import argparse
import datetime
import io
import os
from collections import defaultdict
from typing import Any, DefaultDict, Iterable, Mapping, Optional, Protocol, Sequence

from werkzeug.datastructures import FileStorage

import constants as const
from app import create_app, db
from app.clients import MinioClient
from app.models import TestResult
from helpers import testrun_helpers


class MinioObjectLike(Protocol):
    """Минимальный контракт объекта из MinioClient.list_objects."""

    object_name: Optional[str]
    last_modified: Optional[datetime.datetime]


def _parse_args() -> argparse.Namespace:
    """Разбирает аргументы CLI."""
    parser = argparse.ArgumentParser(
        description="Восстановить прогоны TestOps из MinIO allure-results-bucket"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Только показать, что будет вставлено, без записи в БД",
    )
    return parser.parse_args()


def _to_naive_utc(value: Optional[datetime.datetime]) -> Optional[datetime.datetime]:
    """Приводит datetime к naive UTC: колонка testrun_results.created_at без tz."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(datetime.timezone.utc).replace(tzinfo=None)


def _parse_run_datetime(value: Optional[str]) -> Optional[datetime.datetime]:
    """Парсит строку времени прогона формата DB_DATE_FORMAT в datetime."""
    if not value:
        return None
    return datetime.datetime.strptime(value, const.DB_DATE_FORMAT)


def _read_object_bytes(minio_client: MinioClient, object_name: str) -> bytes:
    """Скачивает тело объекта MinIO целиком и закрывает соединение."""
    response = minio_client.get_object_stream(
        const.ALLURE_RESULTS_BUCKET_NAME, object_name
    )
    payload = response.read()
    response.close()
    response.release_conn()
    return payload


def _as_file_storage(object_name: str, payload: bytes) -> FileStorage:
    """Оборачивает байты в FileStorage, как при HTTP-загрузке в /upload.

    check_all_tests_passed_run ожидает объекты с .filename и файловым потоком.
    В имени оставляем только basename: allure-results.tar.gz или *-result.json.
    """
    filename = os.path.basename(object_name.replace("\\", "/")) or object_name
    return FileStorage(stream=io.BytesIO(payload), filename=filename)


def _group_objects_by_run(
    minio_client: MinioClient,
) -> DefaultDict[str, list[MinioObjectLike]]:
    """Группирует объекты бакета по run_name - первому сегменту ключа.

    MinIO хранит results как:
        run_12_20250801_120000/allure-results.tar.gz
        run_12_20250801_120000/environment.properties или .json - это legacy
    split("/", 1) один раз режет ключ на prefix и остаток пути.
    Ключ без слэша (файл в корне бакета) к прогону не относится - пропускаем.
    """
    groups: DefaultDict[str, list[MinioObjectLike]] = defaultdict(list)
    for obj in minio_client.list_objects(const.ALLURE_RESULTS_BUCKET_NAME, prefix=""):
        name = obj.object_name or ""
        if not name or name.endswith("/"):
            continue
        parts = name.split("/", 1)
        if len(parts) < 2:
            continue
        run_name, _relative_path = parts
        groups[run_name].append(obj)
    return groups


def _rewind(file_storage: FileStorage) -> None:
    """Ставит курсор потока в начало.

    BytesIO/FileStorage после .read() оказываются в EOF. Следующий парсер
    иначе прочитает 0 байт. seek(0) - rewind файлового курсора.
    """
    file_storage.stream.seek(0)


def _extract_stand(files: Sequence[FileStorage]) -> Optional[str]:
    """Достаёт stand из environment.properties (архив или отдельный legacy-файл)."""
    stand: Optional[str] = None
    for file_storage in files:
        filename = file_storage.filename or ""
        _rewind(file_storage)
        content = file_storage.stream.read()
        _rewind(file_storage)
        if testrun_helpers._is_allure_results_archive(filename):
            stand = testrun_helpers._extract_stand_from_archive(content) or stand
        elif os.path.basename(filename) == "environment.properties":
            stand = (
                testrun_helpers._extract_stand_value(
                    "environment.properties", content
                )
                or stand
            )
    return stand


def _build_file_storages(
    minio_client: MinioClient, objects: Iterable[MinioObjectLike]
) -> list[FileStorage]:
    """Скачивает объекты одного прогона и готовит их к check_all_tests_passed_run."""
    files: list[FileStorage] = []
    for obj in objects:
        if not obj.object_name:
            continue
        payload = _read_object_bytes(minio_client, obj.object_name)
        if not payload:
            continue
        files.append(_as_file_storage(obj.object_name, payload))
    return files


def _created_at_from_objects(objects: Sequence[MinioObjectLike]) -> datetime.datetime:
    """created_at прогона: самый поздний LastModified объектов в префиксе."""
    timestamps = [_to_naive_utc(obj.last_modified) for obj in objects]
    known = [item for item in timestamps if item is not None]
    if not known:
        return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    return max(known)


def _print_plan(
    run_name: str,
    info: Mapping[str, Any],
    stand: Optional[str],
    created_at: datetime.datetime,
    action: str,
) -> None:
    """Печатает одну строку плана вставки / результата."""
    stats = info.get(const.STATUS_STATS_KEY) or {}
    print(
        f"{action} run_name={run_name} status={info.get(const.STATUS_KEY)} "
        f"stand={stand!r} start={info.get(const.START_RUN_KEY)} "
        f"stop={info.get(const.STOP_RUN_KEY)} "
        f"passed={stats.get(const.STATUS_PASSED, 0)} "
        f"failed={stats.get(const.STATUS_FAILED, 0)} "
        f"broken={stats.get(const.STATUS_BROKEN, 0)} "
        f"skipped={stats.get(const.STATUS_SKIPPED, 0)} "
        f"created_at={created_at}"
    )


def rebuild(dry_run: bool) -> None:
    """Сканирует MinIO и вставляет отсутствующие прогоны в testrun_results."""
    app = create_app()
    minio_client = MinioClient()

    with app.app_context():
        existing = {
            name for (name,) in db.session.query(TestResult.run_name).all()
        }
        groups = _group_objects_by_run(minio_client)
        print(f"Найдено префиксов в MinIO: {len(groups)}")
        print(f"Уже есть в testrun_results: {len(existing)}")

        skipped = 0
        inserted = 0
        empty = 0

        for run_name in sorted(groups):
            objects = groups[run_name]
            if run_name in existing:
                print(f"SKIP already exists run_name={run_name}")
                skipped += 1
                continue

            files = _build_file_storages(minio_client, objects)
            if not files:
                print(f"SKIP empty prefix run_name={run_name}")
                empty += 1
                continue

            info = testrun_helpers.check_all_tests_passed_run(files)
            stand = _extract_stand(files)
            created_at = _created_at_from_objects(objects)
            stats = info.get(const.STATUS_STATS_KEY) or {}

            if dry_run:
                _print_plan(run_name, info, stand, created_at, "DRY-RUN insert")
                inserted += 1
                continue

            result = TestResult(
                run_name=run_name,
                start_date=_parse_run_datetime(info.get(const.START_RUN_KEY)),
                end_date=_parse_run_datetime(info.get(const.STOP_RUN_KEY)),
                stand=stand,
                status=info.get(const.STATUS_KEY),
                passed_count=stats.get(const.STATUS_PASSED, 0),
                failed_count=stats.get(const.STATUS_FAILED, 0),
                broken_count=stats.get(const.STATUS_BROKEN, 0),
                skipped_count=stats.get(const.STATUS_SKIPPED, 0),
                created_at=created_at,
                is_deleted=False,
            )
            db.session.add(result)
            db.session.commit()
            _print_plan(run_name, info, stand, created_at, "INSERTED")
            inserted += 1

        print(
            f"Готово. skipped={skipped} empty={empty} "
            f"{'would_insert' if dry_run else 'inserted'}={inserted}"
        )


def main() -> None:
    """Точка входа CLI."""
    args = _parse_args()
    rebuild(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
