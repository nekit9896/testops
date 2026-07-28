"""
Валидация и безопасная распаковка tar.gz архивов allure-results.
"""

from __future__ import annotations

import io
import os
import tarfile
from dataclasses import dataclass
from typing import Optional, Sequence

import constants as const
from helpers.allure_utils import extract_stand_from_environment_file


class UploadValidationError(Exception):
    """Ошибка валидации загружаемых файлов до создания записей в БД."""

    def __init__(self, message: str, code: str = "upload_validation_failed") -> None:
        self.message = message
        self.code = code
        super().__init__(message)


@dataclass
class TarArchiveInfo:
    """Результат успешной валидации tar.gz архива."""

    payload_file_count: int
    detected_stand: Optional[str]


def is_gzip_payload(data: bytes) -> bool:
    """
    Проверяет, что файл начинается с gzip-сигнатуры (magic bytes).

    Magic bytes — фиксированные первые байты файла, по которым программа
    определяет формат без полного разбора. Для gzip это два байта 0x1F 0x8B.
    """
    if len(data) < const.GZIP_HEADER_SIZE:
        return False
    header = data[:const.GZIP_HEADER_SIZE]
    return header == const.GZIP_MAGIC


def _unsafe_path_error_message(member_name: str) -> str:
    return (
        f"Архив не принят: внутри есть файл «{member_name}» с некорректным путём "
        "(например, ../ или путь вне папки allure-results). "
        "Соберите allure-results.tar.gz так, чтобы файлы лежали в одной папке "
        "без выхода «вверх» по директориям."
    )


def _unsafe_link_error_message(member_name: str) -> str:
    return (
        f"Архив не принят: внутри есть ссылка «{member_name}». "
        "В архиве должны быть только обычные файлы allure-results, без ссылок."
    )


def _unsafe_special_file_error_message(member_name: str) -> str:
    return (
        f"Архив не принят: внутри есть специальный файл «{member_name}». "
        "В архиве должны быть только обычные файлы allure-results."
    )


def is_allure_payload_filename(name: str) -> bool:
    """Проверяет, что имя файла соответствует allure result/container."""
    basename = os.path.basename(name.replace("\\", "/"))
    return (
        basename.endswith(const.RESULT_NAMING)
        or basename.endswith(const.CONTAINER_NAMING)
    )


def _normalize_member_path(path: str) -> str:
    return path.replace("\\", "/").lstrip("/")


def _is_safe_member_path(destination_dir: str, member_name: str) -> bool:
    normalized = _normalize_member_path(member_name)
    if normalized.startswith("/") or normalized.startswith("../"):
        return False

    abs_destination = os.path.abspath(destination_dir)
    member_target = os.path.abspath(os.path.join(destination_dir, normalized))
    return member_target == abs_destination or member_target.startswith(
        abs_destination + os.sep
    )


def _reject_unsafe_tar_members(tar: tarfile.TarFile, destination_dir: str) -> None:
    for member in tar.getmembers():
        if not _is_safe_member_path(destination_dir, member.name):
            raise UploadValidationError(
                _unsafe_path_error_message(member.name),
                code="unsafe_archive_path",
            )
        if member.issym() or member.islnk():
            raise UploadValidationError(
                _unsafe_link_error_message(member.name),
                code="unsafe_archive_member",
            )
        if member.ischr() or member.isblk() or member.isfifo():
            raise UploadValidationError(
                _unsafe_special_file_error_message(member.name),
                code="unsafe_archive_member",
            )


def _collect_payload_paths(tar: tarfile.TarFile) -> list[str]:
    payload_paths: list[str] = []
    for member in tar.getmembers():
        if not member.isfile():
            continue
        normalized = _normalize_member_path(member.name)
        if is_allure_payload_filename(normalized):
            payload_paths.append(normalized)
    return payload_paths


def _validate_payload_directory_layout(payload_paths: Sequence[str]) -> None:
    """
    Проверяет, что файлы allure-results можно однозначно сопоставить с одной директорией.
    Логика соответствует _resolve_allure_results_dir в testrun_helpers.
    """
    if not payload_paths:
        raise UploadValidationError(
            "Архив не содержит файлов allure-results "
            "(*-result.json или *-container.json).",
            code="missing_allure_results",
        )

    root_payload_files = [
        path for path in payload_paths if "/" not in path and "\\" not in path
    ]
    if root_payload_files:
        nested_paths = [
            path for path in payload_paths if "/" in path or "\\" in path
        ]
        if nested_paths:
            raise UploadValidationError(
                "Архив содержит файлы allure-results в корне и во вложенных "
                "директориях; невозможно однозначно определить источник отчёта.",
                code="ambiguous_allure_results",
            )
        return

    payload_directories: set[str] = set()
    for path in payload_paths:
        parent = os.path.dirname(path.replace("\\", "/"))
        if parent:
            payload_directories.add(parent)

    if len(payload_directories) != 1:
        raise UploadValidationError(
            "Архив содержит файлы allure-results в нескольких директориях; "
            "невозможно однозначно определить источник отчёта.",
            code="ambiguous_allure_results",
        )


def _extract_stand_from_tar(tar: tarfile.TarFile) -> Optional[str]:
    for member in tar.getmembers():
        if not member.isfile():
            continue
        if os.path.basename(member.name.replace("\\", "/")) != "environment.properties":
            continue
        fileobj = tar.extractfile(member)
        if not fileobj:
            continue
        raw = fileobj.read()
        stand = extract_stand_from_environment_file(raw)
        if stand:
            return stand.strip()
    return None


def open_validated_tar_gz(archive_bytes: bytes) -> tarfile.TarFile:
    """
    Проверяет, что байты - gzip+tar, и открывает tar для чтения.
    Вызывающий код должен закрыть TarFile.
    """
    if not archive_bytes:
        raise UploadValidationError("Архив пустой.", code="empty_archive")

    if not is_gzip_payload(archive_bytes):
        raise UploadValidationError(
            "Файл не является корректным gzip-архивом (ожидается tar.gz).",
            code="invalid_gzip",
        )

    try:
        tar = tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz")
    except tarfile.TarError as error:
        raise UploadValidationError(
            f"Архив не является корректным tar.gz: {error}",
            code="invalid_tar_gz",
        ) from error

    try:
        members = tar.getmembers()
        if not members:
            tar.close()
            raise UploadValidationError(
                "Архив tar.gz не содержит файлов.",
                code="empty_tar_archive",
            )
    except tarfile.TarError as error:
        tar.close()
        raise UploadValidationError(
            f"Не удалось прочитать содержимое tar.gz: {error}",
            code="invalid_tar_gz",
        ) from error

    return tar


def validate_tar_gz_archive(archive_bytes: bytes) -> TarArchiveInfo:
    """Полная валидация архива allure-results до записи в БД/MinIO."""
    tar = open_validated_tar_gz(archive_bytes)
    try:
        validation_root = os.path.abspath(os.path.join(os.getcwd(), ".archive_validation"))
        _reject_unsafe_tar_members(tar, validation_root)
        payload_paths = _collect_payload_paths(tar)
        _validate_payload_directory_layout(payload_paths)
        detected_stand = _extract_stand_from_tar(tar)
        return TarArchiveInfo(
            payload_file_count=len(payload_paths),
            detected_stand=detected_stand,
        )
    finally:
        tar.close()


def safe_extract_tar_gz_bytes(archive_bytes: bytes, destination_dir: str) -> None:
    """
    Безопасно распаковывает tar.gz в destination_dir.
    Предполагается, что архив уже прошёл validate_tar_gz_archive.
    """
    tar = open_validated_tar_gz(archive_bytes)
    try:
        os.makedirs(destination_dir, exist_ok=True)
        _reject_unsafe_tar_members(tar, destination_dir)

        extract_filter = getattr(tarfile, "data_filter", None)
        if extract_filter is not None:
            tar.extractall(destination_dir, filter="data")
            return

        for member in tar.getmembers():
            if not member.isfile():
                continue
            if not _is_safe_member_path(destination_dir, member.name):
                raise UploadValidationError(
                    _unsafe_path_error_message(member.name),
                    code="unsafe_archive_path",
                )
            tar.extract(member, path=destination_dir)
    finally:
        tar.close()
