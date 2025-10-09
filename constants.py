# IP
PORT = 5000
HOST = "0.0.0.0"

# Folders
ALLURE_REPORT_FOLDER_NAME = "allure-reports"  # Отсюда читаются готовые отчеты
ALLURE_RESULT_FOLDER_NAME = "allure-results"

# Files
ALLOWED_EXTENSIONS = {"html", "json", "txt"}
ALLURE_REPORT_NAME = "index.html"
LOG_FILE_NAME = "logs.json"

# MinIO
ALLURE_RESULTS_BUCKET_NAME = "allure-results-bucket"
ALLURE_REPORTS_BUCKET_NAME = "allure-reports-bucket"
ATTACHMENTS_BUCKET = "testcase-files-bucket"

# Front
TEMPLATE_INDEX = "index.html"
TEMPLATE_REPORTS = "reports.html"
HTML_403 = "errors/403.html"
HTML_404 = "errors/404.html"
HTML_500 = "errors/500.html"
ALLOWED_OVERRIDE_METHODS = {"PUT", "DELETE", "PATCH"}

# PostgreSQL
TEMP_TEST_STATUS = "success"
DEFAULT_RUN_NAME = "TempName"

# Типы запросов
JSON_CONTENT_TYPE = "application/json"
HTML_CONTENT_TYPE = "text/html"

# Upload files
STATUS_KEY = "status"
PENDING_STATUS = "pending"
STATUS_PASS = "passed"
STATUS_FAIL = "fail"
ENCODING = "utf-8"
RESULT_NAMING = "result.json"
CONTAINER_NAMING = "container.json"
START_RUN_KEY = "start"
STOP_RUN_KEY = "stop"
TIMESTAMP_DIVISOR = 1000

# Тест кейсы:
ASCII_CODING = "ascii"
TESTCASE_PER_PAGE_LIMIT = 25

# Other
DB_DATE_FORMAT = "%Y%m%d_%H%M%S"
VIEW_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
MAX_FILE_SIZE = 52428800  # 50 Mb в байтах
