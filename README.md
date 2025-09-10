# Testops




## Методы и их описание

/upload - метод загрузки результатов прогона автотеста:
- принимает массив файлов (allure-results);
- сохраняет их в уникальную папку (allure-results/run1_{date_of_run});
- создавать запись о новом прогоне в локальной базе данных (SQLAlchemy).
- поле run_name является обязательным.
- проверяет, что файлы не пустые.

## Миграции
```bash
flask db init
flask db migrate -m "Initial Migration"
flask db upgrade

flask db stamp <stamp_id>
```

Для отладки:
внутри контейнера скриптом можно чекнуть текущие таблицы:
```
python - <<'PY'
from app import create_app, db
app = create_app()
with app.app_context():
    print(sorted(db.metadata.tables.keys()))
PY
```


# Хранение данных

## Кратко про таблицы testops

- **TestCase** — тест-кейс (metadata, steps, tags, привязки к сьютам).  
- **TestCaseStep** — шаги тест-кейса (позиция, действие, ожидаемый результат).  
- **TestSuite** — группа / папка тест-кейсов (иерархия через `parent_id`).  
- **TestCaseSuite** — ассоциативный объект между `TestCase` и `TestSuite` (содержит `position` — порядок кейса в сьюте).  
- **Tag + test_case_tags** — простая M:N-таблица для тегов.  
- **TestResult** — результаты прогонов.

**База:** Postgres. **ORM:** Flask-SQLAlchemy / SQLAlchemy. **Миграции:** Alembic (Flask-Migrate). **Файлы:** MinIO (S3-type)

---

## ER / Структура
- **test_cases** (1 — N) test_case_steps
- **test_cases** (M — N) test_suites через test_case_suites (association-class)
- **test_cases** (M — N) tags через test_case_tags (plain table)
- **test_suites** рекурсивно: parent_id -> test_suites.id
- **testrun_results** — отдельная сущность, хранит прогоны


## Описание моделей и полей

### TestCase
- `id` — PK  
- `name` — строка (255)  
- `preconditions`, `description`, `expected_result` — текстовые поля  
- `created_at`, `updated_at`, `deleted_at`, `is_deleted` — временные метки и soft-delete  
- `steps` — relationship к `TestCaseStep`, упорядочены по `position`  
- `suites` — `association_proxy` к `TestSuite` через `TestCaseSuite`  
- `tags` — M:N через `test_case_tags`  
- `UniqueConstraint('name', 'is_deleted')` — уникальность среди активных записей

---

### TestCaseStep
- `id` — PK  
- `test_case_id` — FK -> `test_cases.id` (`ON DELETE CASCADE`)  
- `position` — integer (порядок шага)  
- `action`, `expected`, `attachments` — текст  
- `UniqueConstraint('test_case_id', 'position')` — уникальная позиция в кейсе

---

### TestSuite
- `id` — PK  
- `name` — строка (255)  
- `description` — текст  
- `parent_id` — FK -> `test_suites.id` (смежные), `ondelete=SET NULL`  
- `children` — relationship для под-папок  
- `case_links` — relationship к `TestCaseSuite`  
- `test_cases` — `association_proxy("case_links", "test_case")`  
- `is_deleted` — bool  
- `created_at`, `updated_at` — timestamps

---

### TestCaseSuite (association object)
- `test_case_id`, `suite_id` — составной PK  
- `position` — порядок кейса в сьюте  
- `test_case`, `suite` — relationship с `back_populates`/`backref`  

> Это полноценный ORM-класс — `position` доступен как `link.position`.

---

### Tag + test_case_tags
- `Tag.name` уникален  
- `test_case_tags` — plain table с PK (`test_case_id`, `tag_id`)

---

### TestResult
- `id`, `run_name`, `start_date`, `end_date`, `status`, `created_at`, `is_deleted`  
- Хранит метаданные прогонов тестов (используется в `reports/UI`).

---

## Особенности реализации хранения

### Ассоциационная модель `TestCaseSuite`
**Причина:** нужно хранить порядок кейсов внутри сьюта (`position`) и, возможно, другие атрибуты связи в будущем.  
**Следствие:** используем `association-class` (класс-модель). Это даёт удобный доступ в ORM: `link.position`, простое обновление порядка и нормальные запросы.

---

### Plain table для тегов (`test_case_tags`)
**Причина:** теги не требуют дополнительных полей в связи.  
**Следствие:** простая и быстрая M:N таблица — меньше кода и индексации.

---

### Soft-delete (`is_deleted`, `deleted_at`) + уникальность `name, is_deleted`
**Причина:** нужно сохранять историю или давать возможность восстановить удалённые кейсы.  
**Следствие:** уникальность применяется среди активных записей; фильтрация `WHERE is_deleted = false` обязательна при запросах в UI.

---

### FK `ON DELETE CASCADE` + ORM `passive_deletes=True` / `cascade="all, delete-orphan"`
**Причина:** необходимо обеспечить целостность данных при реальном удалении (DB-level cascade) и оптимизировать работу ORM.  
**Следствие:** при `DELETE` родителя СУБД удалит дочерние записи; ORM не генерирует лишние DELETE-запросы.

---

### `parent_id` с `SET NULL` у `TestSuite`
**Причина:** при удалении родителя не хочется массово удалять все дочерние сьюты автоматически.  
**Следствие:** дочерние получат `NULL` и могут быть обработаны вручную/перемещены.

---




## Быстродокер
```bash
docker build -t nekit9896/testops-flask-app:v1.0.18 -f Dockerfile .
docker push nekit9896/testops-flask-app:v1.0.18
docker exec -it testops-flask-app bash

docker run --rm -v /var/run/docker.sock:/var/run/docker.sock aquasec/trivy image nekit9896/system-dependencies:v0.1
```


Примеры запросов
```bash
curl -X POST 'http://localhost:5000/upload' -F "files=@C:\Users\nekit\PycharmProjects\test_pets\allure-results\0477e9be-9f9a-4301-9792-784ae94c08bb-result.json"      -F "files=@C:\Users\nekit\PycharmProjects\test_pets\allure-results\3383fa62-dce1-4ac2-abc6-ead40f3f4b7a-attachment.txt" -F "files=@C:\Users\nekit\PycharmProjects\test_pets\allure-results\11327270-8aab-4d37-81b4-6488855be7f4-attachment.txt" -F "files=@C:\Users\nekit\PycharmProjects\test_pets\allure-results\a66c33e6-bb8c-4fa2-b268-0d47342c76a3-result.json" -F "files=@C:\Users\nekit\PycharmProjects\test_pets\allure-results\b33d1db4-fc93-460f-925e-e4e1535b0c9e-attachment.txt" -F "files=@C:\Users\nekit\PycharmProjects\test_pets\allure-results\ba852533-61b6-45f4-ae51-483aaedb8871-attachment.txt" -F "files=@C:\Users\nekit\PycharmProjects\test_pets\allure-results\d3c09ae1-4f16-400b-a70e-abfb701ea0de-container.json" -v
```
```bash
export LANG=en_US.UTF-8  # делаем локаль UTF-8 в текущей сессии (рекомендовано)
cat > payload.json <<'JSON'
{
  "name": "Созданный через curl тест-кейс",
  "preconditions": "Авторизация: пользователь залогинен",
  "description": "Пошаговая проверка входа и создания записи",
  "expected_result": "Запись создаётся, данные отображаются в списке",
  "steps": [
    {"position": 1, "action": "Открыть поле ввода", "expected": "Поле ввода открылось"},
    {"position": 2, "action": "Ввести текст и отправить", "expected": "Текст введен и отправлен"},
    {"action": "Заполнить форму и отправить", "expected": "Появилось подтверждение", "attachments": "screenshot-1.png"}
  ],
  "tags": ["smoke", {"name": "regression"}],
  "suite_links": [{"suite_name": "API Suite", "position": 2}]
}
JSON
curl -v -i -X POST 'http://localhost:5000/test_cases' \
  -H 'Content-Type: application/json; charset=utf-8' \
  --data-binary @payload.json
```

### POST /test_cases — Создание тест-кейса

#### Описание

POST /test_cases — создаёт TestCase и опционально связанные сущности: `steps`, `tags`, `suite_links`.
Принимает JSON, вызывает `create_test_case_from_payload`, мапит доменные исключения на HTTP-статусы и возвращает сериализованный созданный объект.

#### Правила поведения

##### Теги (tags):
- Строка "smoke" или объект `{"name": "regression"}` → ищем по имени, если нет — создаём новый тег.
- Объект `{"id": N}` → если тег с таким id есть — привяжем; если нет — элемент будет пропущен и в логах появится warning. (Терпимое поведение по умолчанию.)
- Suite links (suite_links):
    - `{"suite_name": "API Suite"}` → ищем по имени, если нет — создаём новый TestSuite.
    - `{"suite_id": N}` → если suite с таким id есть — привяжем; если нет — элемент будет пропущен и логируется warning.

##### Шаги (steps):
Каждый шаг обязателтно имеет action (не пустая строка).
`position` опционален — если отсутствует, позиции назначаются автоматически (последовательные).
Дубликат `position` в рамках одного тест-кейса → ошибка валидации (400).

##### Уникальность имени:
Constraint на `name` + `is_deleted`. Попытка создать активный тест-кейс с уже существующим именем вернёт 409 Conflict.

##### Ожидаемый JSON-body (пример)
```json
{
  "name": "string (required)",
  "preconditions": "string (optional)",
  "description": "string (optional)",
  "expected_result": "string (optional)",
  "steps": [
    {"position": 1, "action": "string (required)", "expected": "string (optional)", "attachments": "string (optional)"},
    {"action": "string"}
  ],
  "tags": [
    "string",          
    {"id": 5},              
    {"name": "regression"}   
  ],
  "suite_links": [
    {"suite_id": 3, "position": 1},             
    {"suite_name": "API Suite", "position": 2}  
  ]
}
```

##### Примеры ответов
201 Created — успех

Headers:
```
Location: /test_cases/123
Content-Type: application/json
```


Body:
```json
{
  "id": 123,
  "name": "Созданный через curl тест-кейс",
  "preconditions": "Авторизация: пользователь залогинен",
  "description": "Проверка формы",
  "expected_result": "Запись создаётся",
  "created_at": "2025-09-10T09:21:56.123456+00:00",
  "updated_at": "2025-09-10T09:21:56.123456+00:00",
  "is_deleted": false,
  "steps": [
    {"id": 1, "position": 1, "action": "Открыть поле ввода", "expected": "Поле открылось", "attachments": null},
    {"id": 2, "position": 2, "action": "Ввести текст и отправить", "expected": "Текст отправлен", "attachments": null},
    {"id": 3, "position": 3, "action": "Проверить подтверждение", "expected": "Появилось подтверждение", "attachments": null}
  ],
  "tags": [{"id": 1, "name": "smoke"}, {"id": 2, "name": "regression"}],
  "suites": [{"id": 5, "name": "API Suite", "position": 2}]
}
```

### DELETE /delete_test_run/<int:run_id>

Маркирует тестран как удаленный по указанному `run_id`.

#### Параметры

- `run_id` (int)  
  Идентификатор тестового прогона (TestRun), который нужно пометить как удаленный.

#### Описание

Метод получает объект `TestResult` из базы данных по его `run_id`. Если объект существует, он обновляет поле `is_deleted` на `True`, что логически помечает данный тестран как удаленный, и сохраняет изменения в базе данных. Если объект с указанным `run_id` не найден, возвращается соответствующее сообщение об ошибке.

Этот метод использует ORM (SQLAlchemy), чтобы взаимодействовать с базой данных как с Python-объектами.

#### Возвращаемые значения

- **Успех** (200):  
  Возвращает JSON-ответ с сообщением:  
```json
  {
    "message": "TestRun помечен как удаленный"
  }
```
- **Ошибка** (404):  
  Возвращает JSON-ответ с сообщением:
```json
  {
    "message": "TestRun не найден"
  }
```
