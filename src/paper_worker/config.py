import os
import tempfile
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator


class ZoteroConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    library_id: str = ""
    library_type: Literal["user", "group"] = "user"
    api_key: SecretStr = SecretStr("")
    collection_key: str = ""

    @property
    def enabled(self) -> bool:
        return bool(self.library_id and self.api_key.get_secret_value())


class SupabaseConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    url: str = ""
    key: SecretStr = SecretStr("")

    @property
    def enabled(self) -> bool:
        return bool(self.url and self.key.get_secret_value())


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    obsidian_vault_dir: Path = Path("output")
    cache_dir: Path = Path.home() / ".cache" / "paper-worker"
    codex_command: str = "codex exec --full-auto"
    codex_timeout: int = Field(default=900, ge=10)
    github_token: SecretStr = SecretStr("")
    zotero: ZoteroConfig = Field(default_factory=ZoteroConfig)
    supabase: SupabaseConfig = Field(default_factory=SupabaseConfig)

    @model_validator(mode="after")
    def validate_config(self):
        if not self.codex_command.strip():
            raise ValueError("Codex command cannot be empty")
        for label, configured, enabled in [
            (
                "Zotero",
                bool(self.zotero.library_id or self.zotero.api_key.get_secret_value()),
                self.zotero.enabled,
            ),
            (
                "Supabase",
                bool(self.supabase.url or self.supabase.key.get_secret_value()),
                self.supabase.enabled,
            ),
        ]:
            if configured and not enabled:
                raise ValueError(f"{label} credentials are incomplete")
        return self


def load_config(path: Path = Path("config.yaml")) -> Config:
    if not path.exists():
        return Config()
    data = yaml.safe_load(path.read_text(encoding="utf-8-sig")) or {}
    config = Config.model_validate(data)
    for field in ("obsidian_vault_dir", "cache_dir"):
        value = getattr(config, field).expanduser()
        setattr(config, field, value if value.is_absolute() else (path.resolve().parent / value))
    return config


def save_config(config: Config, path: Path) -> None:
    data = config.model_dump(mode="json")
    data["github_token"] = config.github_token.get_secret_value()
    data["zotero"]["api_key"] = config.zotero.api_key.get_secret_value()
    data["supabase"]["key"] = config.supabase.key.get_secret_value()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            yaml.safe_dump(data, stream, allow_unicode=True, sort_keys=False)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
