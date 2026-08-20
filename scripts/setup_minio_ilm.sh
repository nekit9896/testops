#!/bin/sh
#
# Разовый скрипт настройки MinIO ILM для allure-reports-bucket.
# Запускается вручную один раз с хоста, где развернут
#
# Зачем:
#   HTML-отчёты Allure весят десятки мегабайт. Без TTL бакет allure-reports-bucket
#   забивает диск. Правило ILM говорит MinIO самому физически удалять объект,
#   когда с момента загрузки прошло 30 дней.
#   allure-results-bucket не трогаем: из него отчёт можно сгенерировать снова.
#
# Почему docker run, а не exec в flask_app:
#   В образе приложения нет бинаря mc. Одноразовый контейнер minio/mc
#   подключается к той же docker-сети, что и сервис minio, и говорит с ним
#   по имени хоста "minio". --rm удаляет этот контейнер сразу после выхода.
#
# Что делает по шагам:
#   1. Находит docker-сеть compose (*minio-network), либо берёт MINIO_NETWORK.
#   2. Стартует minio/mc в этой сети.
#   3. mc alias set - сохраняет URL и ключи как профиль "local".
#   4. mc mb --ignore-existing - создаёт бакет, если его ещё нет
#      (после инцидента reports-bucket мог исчезнуть).
#   5. mc ilm rule add --expire-days 30 - вешает правило удаления HTML старше 30 дней.
#   6. mc ilm rule ls - печатает правила, чтобы проверить, что запись появилась.
#
# После успеха правило живёт в MinIO. Повторять скрипт не нужно: повторный
# ilm rule add может добавить второе такое же правило.
#
# Запуск:
#   sh scripts/setup_minio_ilm.sh
#   MINIO_NETWORK=testops_minio-network sh scripts/setup_minio_ilm.sh
#
set -eu

NETWORK="${MINIO_NETWORK:-}"
if [ -z "$NETWORK" ]; then
  NETWORK=$(docker network ls --format '{{.Name}}' | grep minio-network | head -n 1)
fi
if [ -z "$NETWORK" ]; then
  echo "Не найдена docker-сеть minio-network. Задайте MINIO_NETWORK=..."
  echo "Список сетей: docker network ls"
  exit 1
fi

MINIO_USER="${MINIO_ROOT_USER:-minioadmin}"
MINIO_PASS="${MINIO_ROOT_PASSWORD:-minioadmin}"
MINIO_HOST="${MINIO_HOST:-minio:9000}"

echo "Using docker network: $NETWORK"
echo "MinIO endpoint inside network: $MINIO_HOST"

docker run --rm --network "$NETWORK" \
  -e MINIO_ROOT_USER="$MINIO_USER" \
  -e MINIO_ROOT_PASSWORD="$MINIO_PASS" \
  minio/mc sh -c "
    mc alias set local http://${MINIO_HOST} \"\$MINIO_ROOT_USER\" \"\$MINIO_ROOT_PASSWORD\" &&
    mc mb local/allure-reports-bucket --ignore-existing &&
    mc ilm rule add local/allure-reports-bucket --expire-days 30 &&
    mc ilm rule ls local/allure-reports-bucket
  "
