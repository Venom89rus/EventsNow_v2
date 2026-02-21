import os

# Определим структуру проекта
project_structure = {
    "EventsNow_v2": {
        "bot": {
            "__init__.py": "",
            "config.py": "",
            "handlers": {
                "main_menu.py": "",
                "organizer.py": "",
                "resident.py": "",
                "admin.py": "",
                "feedback.py": "",
                "payments.py": "",
            },
            "models": {
                "user.py": "",
                "event.py": "",
                "payment.py": "",
                "reminder.py": "",
            },
            "utils": {
                "db.py": "",
                "notifications.py": "",
                "validators.py": "",
            },
            "services": {
                "yu_cassa_service.py": "",
            },
            "__main__.py": "",
        },
        "requirements.txt": "",
    }
}

# Функция для создания структуры папок и файлов
def create_project_structure(base_path, structure):
    for name, value in structure.items():
        path = os.path.join(base_path, name)
        if isinstance(value, dict):
            # Создание папки
            os.makedirs(path, exist_ok=True)
            # Рекурсивно создаем файлы и папки
            create_project_structure(path, value)
        else:
            # Создание файла
            with open(path, 'w') as f:
                f.write(value)

# Укажите путь, где будет создан проект
base_path = './EventsNow_v2'

# Создаем структуру проекта
create_project_structure(base_path, project_structure)

print(f"Структура проекта создана по пути: {base_path}")
