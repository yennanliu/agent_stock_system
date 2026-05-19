import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
DB_PATH: str = os.getenv("DB_PATH", "./data/stock.db")
DEFAULT_CAPITAL: float = float(os.getenv("DEFAULT_CAPITAL", "10000"))
DATA_PERIOD: str = os.getenv("DATA_PERIOD", "2y")
MAX_REVIEW_ITERATIONS: int = int(os.getenv("MAX_REVIEW_ITERATIONS", "3"))

Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
