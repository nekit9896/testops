# Testops




## Методы и их описание

/upload - метод загрузки результатов прогона автотеста:
- принимает массив файлов (allure-results);
- сохраняет их в уникальную папку (allure-results/run1_{date_of_run});
- создавать запись о новом прогоне в локальной базе данных (SQLAlchemy).
- поле run_name является обязательным.
- проверяет, что файлы не пустые.

## Миграции

flask db init
flask db migrate -m "Initail Migration"
flask db upgrade
