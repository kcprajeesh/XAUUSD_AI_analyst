import os
from pathlib import Path
import stat
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


def load_sifting_api_key(secret_file: Path | None = None) -> bool:
    """Load only SIFTING_API_KEY, preserving an explicitly supplied environment value."""
    if os.environ.get("SIFTING_API_KEY"):
        return True
    path = secret_file or Path.home() / ".config/xauusd-ai-analyst/sifting.env"
    try:
        metadata = path.stat()
    except FileNotFoundError:
        return False
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid() or metadata.st_mode & 0o077:
        raise ValueError("sifting_secret_file_permissions") from None
    for line in path.read_text().splitlines():
        entry = line.strip()
        if not entry or entry.startswith("#"):
            continue
        name, separator, value = entry.removeprefix("export ").partition("=")
        if name.strip() != "SIFTING_API_KEY" or not separator:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if not value:
            raise ValueError("sifting_secret_file_invalid") from None
        os.environ["SIFTING_API_KEY"] = value
        return True
    return False


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    host: Literal["127.0.0.1"] = "127.0.0.1"
    port: int = Field(default=8000, ge=1024, le=65535)
    ai_config_file: str | None = Field(default=None, min_length=1)

    @classmethod
    def from_environment(cls) -> "Settings":
        values = {
            key.removeprefix("XAUUSD_").lower(): value
            for key, value in os.environ.items()
            if key.startswith("XAUUSD_")
        }
        return cls.model_validate(values)

    def load_ai_configuration(self):
        from app.ai.config import AIConfiguration, load_configuration

        return load_configuration(self.ai_config_file) if self.ai_config_file else AIConfiguration()
