import asyncpg
from bot.config import DB_HOST, DB_NAME, DB_USER, DB_PASSWORD

# Функция для подключения к базе данных
async def get_db_connection():
    conn = await asyncpg.connect(
        user=DB_USER, password=DB_PASSWORD, database=DB_NAME, host=DB_HOST
    )
    return conn

# Функция для получения всех событий, ожидающих модерации
async def get_events(status):
    conn = await get_db_connection()
    events = await conn.fetch(f"SELECT * FROM events WHERE status = $1", status)
    await conn.close()
    return events

# Функция для получения событий по категории
async def get_events_by_category(category):
    conn = await get_db_connection()
    events = await conn.fetch(f"SELECT * FROM events WHERE category = $1", category)
    await conn.close()
    return events

# Функция для получения событий по дате
async def get_events_by_date(days):
    conn = await get_db_connection()
    events = await conn.fetch(f"SELECT * FROM events WHERE date <= CURRENT_DATE + INTERVAL '$1 day'", days)
    await conn.close()
    return events

# Функция для сохранения события в базе данных
async def save_event(event):
    conn = await get_db_connection()
    await conn.execute(
        "INSERT INTO events(name, description, date, time, location, price, photos, ticket_link, category, status) "
        "VALUES($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)",
        event.name, event.description, event.date, event.time, event.location, event.price, event.photos, event.ticket_link, event.category, event.status
    )
    await conn.close()

# Функция для обновления статуса события
async def update_event_status(event_id, status):
    conn = await get_db_connection()
    await conn.execute("UPDATE events SET status = $1 WHERE id = $2", status, event_id)
    await conn.close()
