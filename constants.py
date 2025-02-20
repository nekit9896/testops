PORT = 5000
HOST = "0.0.0.0"
UPLOAD_FOLDER = "allure-results"
ALLOWED_EXTENSIONS = {"html", "json", "txt"}

ALLURE_REPORT_NAME = "index.html"

ALLURE_REPORT_FOLDER_NAME = "reports"  # Отсюда читаются готовые отчеты
ALLURE_RESULTS_FOLDER_NAME = (
    "allure-results"  # Здесь в отдельных директориях будут находиться
)

ALLURE_RESULT_BUCKET_NAME = "allure-results-bucket"

TEMP_RUN_ID = 5557

DATE_FORMAT = "%Y%m%d_%H%M%S"
STATUS_KEY = "status"
STATUS_PASS = "passed"
STATUS_FAIL = "fail"
ENCODING = "utf-8"
RESULT_NAMING = "result.json"
CONTAINER_NAMING = "container.json"
START_RUN_KEY = "start"
STOP_RUN_KEY = "stop"
TIMESTAMP_DIVISOR = 1000
DEFAULT_RUN_NAME = "TempName"
