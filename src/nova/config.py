import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()


class Settings(BaseModel):
    base_url: str
    api_key: str
    model: str
    workspace: Path
    db: Path
    max_steps: int
    temperature: float


def get_settings() -> Settings:
    return Settings(
        base_url=os.getenv("NOVA_BASE_URL", "http://localhost:11434/v1"),
        api_key=os.getenv("NOVA_API_KEY", "ollama"),
        model=os.getenv("NOVA_MODEL", "qwen3.5:4b"),
        workspace=Path(os.getenv("NOVA_WORKSPACE", "./workspace")),
        db=Path(os.getenv("NOVA_DB", "./data/nova_memory.sqlite3")),
        max_steps=int(os.getenv("NOVA_MAX_STEPS", "8")),
        temperature=float(os.getenv("NOVA_TEMPERATURE", "0.2")),
    )