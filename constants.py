PORT = 5000
HOST = "0.0.0.0"
UPLOAD_FOLDER = "allure-results"
ALLOWED_EXTENSIONS = {"html", "json", "txt"}

ALLURE_REPORT_NAME = "index.html"

ALLURE_REPORT_FOLDER_NAME = "reports"  # Отсюда читаются готовые отчеты
ALLURE_RESULT_FOLDER_NAME = (
    "allure-results"  # Здесь в отдельных директориях будут находиться
)

BUCKET_NAME = "allure-results-bucket"

TEMP_RUN_ID = 5557

DATE_FORMAT = "%Y%m%d_%H%M%S"
