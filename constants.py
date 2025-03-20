# IP
PORT = 5000
HOST = "0.0.0.0"

# Folders
UPLOAD_FOLDER = "allure-results"
ALLURE_REPORT_FOLDER_NAME = "reports"  # Отсюда читаются готовые отчеты
ALLURE_RESULT_FOLDER_NAME = (
    "allure-results"  # Здесь в отдельных директориях будут находиться данные о прогоне
)

# Files
ALLOWED_EXTENSIONS = {"html", "json", "txt"}
ALLURE_REPORT_NAME = "index.html"
LOG_FILE_NAME = "logs.json"

# MinIO
ALLURE_RESULTS_BUCKET_NAME = "allure-results-bucket"
TEMP_RUN_ID = 5557  # Тестовый айди прогона для запуска без PostgreSQL

# Front
TEMPLATE_INDEX = "index.html"
TEMPLATE_REPORTS = "reports.html"
HTML_403 = "errors/403.html"
HTML_404 = "errors/404.html"
HTML_500 = "errors/500.html"

# PostgreSQL
TEMP_TEST_STATUS = "success"
DEFAULT_RUN_NAME = "TempName"

# Типы запросов
JSON_CONTENT_TYPE = "application/json"
HTML_CONTENT_TYPE = "text/html"

# Upload files
STATUS_KEY = "status"
STATUS_PASS = "passed"
STATUS_FAIL = "fail"
ENCODING = "utf-8"
RESULT_NAMING = "result.json"
CONTAINER_NAMING = "container.json"
START_RUN_KEY = "start"
STOP_RUN_KEY = "stop"
TIMESTAMP_DIVISOR = 1000

# Other
DATE_FORMAT = "%Y%m%d_%H%M%S"
