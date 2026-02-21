import os
from dotenv import load_dotenv

load_dotenv()

API_TOKEN = os.getenv("BOT_TOKEN", "").strip()
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

if not API_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing in .env")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is missing in .env")
# --- ADMIN IDS ---
# В .env добавь строку:
# ADMIN_IDS=823223744,111222333
_admin_ids_raw = os.getenv("ADMIN_IDS", "").strip()
ADMIN_IDS = [int(x) for x in _admin_ids_raw.split(",") if x.strip().isdigit()]

YOOKASSA_SHOP_ID = os.getenv("YOOKASSA_SHOP_ID", "").strip()
YOOKASSA_SECRET_KEY = os.getenv("YOOKASSA_SECRET_KEY", "").strip()

if not YOOKASSA_SHOP_ID:
    raise RuntimeError("YOOKASSA_SHOP_ID is missing in .env")

if not YOOKASSA_SECRET_KEY:
    raise RuntimeError("YOOKASSA_SECRET_KEY is missing in .env")