"""Typed settings, loaded from environment variables and an optional ``.env`` file.

Loading fails closed: an invalid value raises ``ConfigError`` instead of falling back to a
default. Error messages name the offending variable but never echo its value, because some
variables hold secrets.
"""

from __future__ import annotations

import datetime as dt
import os
from collections.abc import Mapping
from datetime import timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

DEFAULT_ENV_FILE = Path(".env")

# Environment variable name -> Settings field name.
_ENV_TO_FIELD: dict[str, str] = {
    "ANTHROPIC_API_KEY": "anthropic_api_key",
    "WALI_AGENT_MODEL": "agent_model",
    "WALI_SENTINEL_MODEL": "sentinel_model",
    "WALI_LLM_PROVIDER": "llm_provider",
    "WALI_LLM_API_KEY": "llm_api_key",
    "WALI_LLM_TEMPERATURE": "llm_temperature",
    "WALI_LLM_BASE_URL": "llm_base_url",
    "WALI_LLM_MAX_TOKENS": "llm_max_tokens",
    "WALI_LLM_EFFORT": "llm_effort",
    "WALI_LLM_REFUSAL_FALLBACK": "llm_refusal_fallback",
    "WALI_LLM_TIMEOUT_SECONDS": "llm_timeout_seconds",
    "WALI_GUARD_PRIVATE_KEY": "guard_private_key",
    "WALI_GUARD_PUBLIC_KEY": "guard_public_key",
    "WALI_ENVIRONMENT": "environment",
    "WALI_DB_PATH": "db_path",
    "WALI_GUARD_DB_PATH": "guard_db_path",
    "WALI_SEED_DIR": "seed_dir",
    "WALI_AUDIT_LOG_PATH": "audit_log_path",
    "WALI_SIM_TODAY": "sim_today",
    "WALI_HISTORY_MAX_TURNS": "history_max_turns",
    "WALI_DEFAULT_CURRENCY": "default_currency",
    "WALI_UTC_OFFSET_HOURS": "utc_offset_hours",
    "SIM_FAIL_RATE": "sim_fail_rate",
    "SIM_SEED": "sim_seed",
    "WALI_RECON_DATE_WINDOW_DAYS": "recon_date_window_days",
    "WALI_RECON_AMOUNT_TOLERANCE": "recon_amount_tolerance",
    "WALI_RECON_MISMATCH_MAX_RATIO": "recon_mismatch_max_ratio",
    "WALI_AGENT_MAX_STEPS": "agent_max_steps",
    "WALI_CONFIRM_TOKEN_TTL_SECONDS": "confirm_token_ttl_seconds",
    "WALI_PROPOSALS_PER_HOUR": "proposals_per_hour",
    "WALI_SENTINEL_STRICT_TURN": "sentinel_strict_turn",
    "MANUAL_MINUTES_PER_ITEM": "manual_minutes_per_item",
}
_FIELD_TO_ENV = {field: env for env, field in _ENV_TO_FIELD.items()}


class ConfigError(ValueError):
    """Raised when the configuration is invalid."""


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    # LLM. Model names are configuration only; there is deliberately no default.
    anthropic_api_key: SecretStr | None = None
    agent_model: str | None = None
    sentinel_model: str | None = None
    # anthropic: the Anthropic SDK (the default, as in the specification).
    # openai_compatible: any endpoint that speaks the OpenAI chat-completions format.
    llm_provider: Literal["anthropic", "openai_compatible"] = "anthropic"
    # The key for an openai_compatible endpoint. Not used by the anthropic provider.
    llm_api_key: SecretStr | None = None
    # Sent only by the openai_compatible provider. Current Claude models accept none.
    llm_temperature: float | None = Field(default=None, ge=0, le=2)
    # anthropic: only for an Anthropic-compatible endpoint other than Anthropic's own.
    # openai_compatible: required, for example https://api.example.com/v1
    llm_base_url: str | None = None
    llm_max_tokens: int = Field(16000, ge=256, le=128000)
    # How much the model thinks. None leaves the model's own default.
    llm_effort: Literal["low", "medium", "high", "xhigh", "max"] | None = None
    # Let the API re-run a request on another model if a safety classifier declines it.
    # None means: on for Anthropic's own endpoint, off when llm_base_url is set.
    llm_refusal_fallback: bool | None = None
    llm_timeout_seconds: float = Field(120.0, gt=0, le=600)

    # Guard signing key (Ed25519, base64 of the raw 32 bytes).
    guard_private_key: SecretStr | None = None
    guard_public_key: str | None = None

    # Which environment to run against.
    environment: Literal["sim", "organiser"] = "sim"

    # Storage.
    db_path: Path = Path("data/wali.db")
    guard_db_path: Path = Path("data/guard.db")
    seed_dir: Path = Path("data/seed")
    audit_log_path: Path = Path("data/audit.jsonl")

    # The date the simulation treats as today. None means the day after the seed data ends.
    sim_today: dt.date | None = None
    # User turns kept in a chat session before older ones are dropped.
    history_max_turns: int = Field(30, ge=4, le=200)

    # Locale.
    default_currency: str = Field("IDR", min_length=3, max_length=3)
    utc_offset_hours: int = Field(7, ge=-12, le=14)

    # Simulated environment failure injection.
    sim_fail_rate: float = Field(0.0, ge=0.0, le=1.0)
    sim_seed: int = 42

    # Reconciliation tolerances.
    recon_date_window_days: int = Field(3, ge=0, le=31)
    recon_amount_tolerance: Decimal = Field(Decimal("0"), ge=0)
    recon_mismatch_max_ratio: Decimal = Field(Decimal("0.05"), ge=0, le=1)

    # Agent and guard.
    agent_max_steps: int = Field(8, ge=1, le=50)
    confirm_token_ttl_seconds: int = Field(300, ge=1, le=3600)
    proposals_per_hour: int = Field(10, ge=1)
    # False: text flagged in a record makes payments for THAT invoice or supplier wait for the
    # owner. True: it also makes every payment in the same conversation turn wait.
    sentinel_strict_turn: bool = False

    # PLACEHOLDER until the finance analyst supplies a figure from real interviews.
    manual_minutes_per_item: Decimal = Field(Decimal("5"), gt=0)

    @property
    def tz(self) -> timezone:
        """The business timezone as a fixed UTC offset."""
        return timezone(timedelta(hours=self.utc_offset_hours))


def read_env_file(path: Path) -> dict[str, str]:
    """Parse ``KEY=VALUE`` lines. Blank lines and ``#`` comments are ignored."""
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def load_settings(
    env: Mapping[str, str] | None = None,
    env_file: Path | None = DEFAULT_ENV_FILE,
) -> Settings:
    """Build settings from ``env_file`` overlaid with ``env`` (default: the process environment).

    Unknown variables are ignored and empty values count as unset.
    """
    source: dict[str, str] = {}
    if env_file is not None:
        source.update(read_env_file(env_file))
    source.update(os.environ if env is None else env)

    values = {
        field: source[name].strip()
        for name, field in _ENV_TO_FIELD.items()
        if source.get(name, "").strip()
    }
    try:
        return Settings.model_validate(values)
    except ValidationError as exc:
        problems = "; ".join(
            f"{_FIELD_TO_ENV.get(str(err['loc'][0]), err['loc'][0])}: {err['msg']}"
            for err in exc.errors(include_input=False, include_url=False)
        )
        raise ConfigError(f"Invalid configuration: {problems}") from None
