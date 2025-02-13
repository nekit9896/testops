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



пример запроса
curl -X POST http://localhost:5000/upload -F "files=@C:\Users\nekit\PycharmProjects\test_pets\allure-results\0477e9be-9f9a-4301-9792-784ae94c08bb-result.json"      -F "files=@C:\Users\nekit\PycharmProjects\test_pets\allure-results\3383fa62-dce1-4ac2-abc6-ead40f3f4b7a-attachment.txt" -F "files=@C:\Users\nekit\PycharmProjects\test_pets\allure-results\11327270-8aab-4d37-81b4-6488855be7f4-attachment.txt" -F "files=@C:\Users\ne
kit\PycharmProjects\test_pets\allure-results\a66c33e6-bb8c-4fa2-b268-0d47342c76a3-result.json" -F "files=@C:\Users\nekit\PycharmProjects\test_pets\allure-results\b33d1db4-fc93-460f-925e-e4e1535b0c9e-attachment.txt" -F "files=@C:\Users\nekit\PycharmProjects\test_pets\allure-results\ba852533-61b6-45f4-ae51-483aaedb8871-attachment.txt" -F "files=@C:\Users\nekit\PycharmProjects\test_pets\allure-results\d3c09ae1-4f16-400b-a70e-abfb701ea0de-container.json"