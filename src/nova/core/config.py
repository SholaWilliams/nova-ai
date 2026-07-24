"""Settings (`settings.json`) and Secrets (env/.env) — load/validate/persist (docs/11 §5).

Defaults live in code; overrides live in the file, so a missing or corrupt settings file
always yields a working app (docs/03 §15). Two independent things live here:

- `Settings`: non-secret, user-adjustable config, persisted to `settings.json`.
- `Secrets`: API keys and a few env-only knobs, read from the process environment / `.env`
  files — never written by this module, never persisted to `settings.json` (NFR-8).
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from nova.core.atomic_io import atomic_write_text

logger = logging.getLogger(__name__)


def get_data_dir() -> Path:
    """Resolve NOVA's data root: `NOVA_DATA_DIR` override, else `%APPDATA%/NOVA`.

    Read directly from the process environment (not `.env`) since this decides where
    a data-directory `.env` file would even live — see `Secrets` below.
    """
    override = os.environ.get("NOVA_DATA_DIR")
    if override:
        return Path(override)
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "NOVA"
    return Path.home() / ".nova"


class Secrets(BaseSettings):
    """API keys and env-only knobs (docs/14 §2). Never logged, never written to disk here."""

    model_config = SettingsConfigDict(env_prefix="NOVA_", extra="ignore")

    # M9: OmniRoute (a locally-run gateway, docs/04 TD-4) is the sole LLM backend.
    omniroute_api_key: str | None = None
    groq_api_key: str | None = None  # STT only (TD-5) — Groq's chat usage was removed at M9
    log_level: str = "INFO"
    desktop_override: str | None = None

    @classmethod
    def load(cls, repo_env: Path | None = None, data_dir: Path | None = None) -> Secrets:
        """Load secrets with precedence: process env > data-dir `.env` > repo `.env` (dev).

        `pydantic-settings` applies real process environment variables over any `env_file`
        value automatically; among the files themselves, later entries in `env_file` win,
        so the data-dir file is listed after the repo file.
        """
        data_dir = data_dir if data_dir is not None else get_data_dir()
        candidates = [repo_env or Path(".env"), data_dir / ".env"]
        env_files = tuple(str(p) for p in candidates if p.is_file())
        return cls(_env_file=env_files or None)  # type: ignore[call-arg]


class ProviderSettings(BaseModel):
    """OmniRoute connection config (M9, docs/04 TD-4) — sole LLM backend, no active-provider
    selection needed anymore (there's only one)."""

    model_config = ConfigDict(extra="allow")

    omniroute_base_url: str = "http://127.0.0.1:20128"
    # ⚠️ verify-at-implementation (M9): OmniRoute's public docs don't list a specific model id
    # with confirmed tool-calling support (unlike OpenRouter's catalog, which did) — "auto/coding"
    # (OmniRoute's own "quality-first" combo name) is the closest documented option, a
    # placeholder pending owner verification against their own OmniRoute dashboard/model
    # catalog once it's running. See docs/04 TD-4.
    omniroute_model: str = "auto/coding"


class VoiceSettings(BaseModel):
    """TTS on/off, voice choice, and device selection."""

    model_config = ConfigDict(extra="allow")

    tts_enabled: bool = True
    # ⚠️ verify-at-implementation (M4, docs/04 TD-6 revision): pocket-tts's built-in, non-
    # gated voice catalog is name-selected (not a locale code like the old `en-US-AnaNeural`
    # takada-tts-service's default; catalog: alba, cosette, marius, javert, jean, anna, vera,
    # fantine, charles, paul, eponine, azelma, george, mary, jane, michael, eve, bill_boerst,
    # peter_yearsley, stuart_bell, caro_davy, giovanni, lola, juergen, rafael, estelle.
    # "alba" chosen to match takada-tts-service's PocketTTSProvider default (POCKET_TTS_VOICE)
    # — the service loads only one voice per instance, so Nova's default must match or the
    # service returns 400. Owner can change the service's env var or pick a different voice
    # in Settings; just keep them in sync.
    voice: str = "alba"
    # M9: takada-tts-service connection config (docs/04 TD-6) — a locally-run microservice,
    # not a cloud endpoint, so no API key: see `Secrets` docstring (NFR-8 only covers secrets).
    # Port 8000 confirmed live (2026-07-23) — matches the service's own README default
    # (`uvicorn app.main:app --port 8000`), not the 8020 first guessed from an early example.
    tts_base_url: str = "http://127.0.0.1:8000"
    tts_tenant_id: str = "nova"
    input_device: int | None = None
    output_device: int | None = None
    sound_effects: bool = True


class WeatherSettings(BaseModel):
    """Default city for the weather tool when the user doesn't name one."""

    model_config = ConfigDict(extra="allow")

    default_city: str = "Lagos"


class UiSettings(BaseModel):
    """User-adjustable look and feel (FR-44)."""

    model_config = ConfigDict(extra="allow")

    accent: Literal["cyan", "violet", "emerald", "amber"] = "cyan"
    reduced_motion: bool = False
    pipeline_visible: bool = True


class VadSettings(BaseModel):
    """Voice-activity-detection tuning."""

    model_config = ConfigDict(extra="allow")

    aggressiveness: int = Field(default=2, ge=0, le=3)
    silence_ms: int = Field(default=800, gt=0)


class AdvancedSettings(BaseModel):
    """Agent-loop and tool-execution limits."""

    model_config = ConfigDict(extra="allow")

    max_iterations: int = Field(default=5, gt=0)
    tool_timeout_s: int = Field(default=15, gt=0)
    vad: VadSettings = Field(default_factory=VadSettings)


class Settings(BaseModel):
    """The full `settings.json` shape (docs/11 §5). Unknown fields round-trip untouched."""

    model_config = ConfigDict(extra="allow")

    version: int = 1
    provider: ProviderSettings = Field(default_factory=ProviderSettings)
    voice: VoiceSettings = Field(default_factory=VoiceSettings)
    weather: WeatherSettings = Field(default_factory=WeatherSettings)
    ui: UiSettings = Field(default_factory=UiSettings)
    advanced: AdvancedSettings = Field(default_factory=AdvancedSettings)


_SECTION_MODELS: dict[str, type[BaseModel]] = {
    "provider": ProviderSettings,
    "voice": VoiceSettings,
    "weather": WeatherSettings,
    "ui": UiSettings,
    "advanced": AdvancedSettings,
}


def load_settings(path: Path) -> Settings:
    """Load `Settings` from `path`.

    Missing file -> defaults. Corrupt JSON / non-object top level -> defaults (whole file
    quarantined, with a warning). A single invalid *section* (e.g. `voice` has a bad type)
    falls back to that section's defaults with a warning, while other valid sections and
    unknown fields are kept — one bad section shouldn't blank the whole file.
    """
    if not path.is_file():
        return Settings()

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("%s is corrupt (%s); using defaults", path, exc)
        return Settings()

    if not isinstance(raw, dict):
        logger.warning("%s is not a JSON object; using defaults", path)
        return Settings()

    merged: dict[str, Any] = {
        key: value for key, value in raw.items() if key not in _SECTION_MODELS
    }
    merged["version"] = raw.get("version", 1)

    for key, model_cls in _SECTION_MODELS.items():
        try:
            merged[key] = model_cls.model_validate(raw.get(key, {}))
        except ValidationError as exc:
            logger.warning("%s section %r is invalid (%s); using defaults", path, key, exc)
            merged[key] = model_cls()

    return Settings.model_validate(merged)


def write_secret_to_env(data_dir: Path, key: str, value: str) -> None:
    """Atomically upsert one `KEY=value` line in the data-dir `.env` file (docs/10 §4).

    Secrets never get written to `settings.json` (NFR-8) — this is their one persistence
    path. `key` is the full env var name (e.g. `NOVA_GEMINI_API_KEY`). Preserves any other
    lines already in the file.
    """
    env_path = data_dir / ".env"
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.is_file() else []

    prefix = f"{key}="
    new_line = f"{key}={value}"
    for i, line in enumerate(lines):
        if line.startswith(prefix):
            lines[i] = new_line
            break
    else:
        lines.append(new_line)

    atomic_write_text(env_path, "\n".join(lines) + "\n", tmp_prefix=".env.")


def save_settings(settings: Settings, path: Path) -> None:
    """Write `settings.json` atomically: temp file in the same dir, then `os.replace`."""
    payload = json.dumps(settings.model_dump(mode="json"), indent=2)
    atomic_write_text(path, payload)
