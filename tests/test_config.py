from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from wali.config import ConfigError, load_settings, read_env_file


def test_defaults_when_nothing_is_set():
    settings = load_settings(env={}, env_file=None)

    assert settings.agent_model is None
    assert settings.sentinel_model is None
    assert settings.guard_private_key is None
    assert settings.default_currency == "IDR"
    assert settings.sim_fail_rate == 0.0
    assert settings.agent_max_steps == 8
    assert settings.confirm_token_ttl_seconds == 300
    assert settings.tz.utcoffset(None) == timedelta(hours=7)


def test_values_are_parsed_into_types():
    settings = load_settings(
        env={
            "SIM_FAIL_RATE": "0.25",
            "SIM_SEED": "7",
            "WALI_DB_PATH": "tmp/x.db",
            "WALI_RECON_MISMATCH_MAX_RATIO": "0.1",
            "MANUAL_MINUTES_PER_ITEM": "3.5",
            "WALI_AGENT_MODEL": "some-model",
        },
        env_file=None,
    )

    assert settings.sim_fail_rate == 0.25
    assert settings.sim_seed == 7
    assert settings.db_path == Path("tmp/x.db")
    assert settings.recon_mismatch_max_ratio == Decimal("0.1")
    assert settings.manual_minutes_per_item == Decimal("3.5")
    assert settings.agent_model == "some-model"


def test_empty_values_count_as_unset():
    settings = load_settings(env={"SIM_FAIL_RATE": "", "WALI_AGENT_MODEL": "  "}, env_file=None)

    assert settings.sim_fail_rate == 0.0
    assert settings.agent_model is None


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("SIM_FAIL_RATE", "1.5"),
        ("SIM_FAIL_RATE", "-0.1"),
        ("SIM_SEED", "abc"),
        ("WALI_AGENT_MAX_STEPS", "0"),
        ("WALI_CONFIRM_TOKEN_TTL_SECONDS", "0"),
        ("WALI_RECON_AMOUNT_TOLERANCE", "-1"),
        ("MANUAL_MINUTES_PER_ITEM", "0"),
        ("WALI_DEFAULT_CURRENCY", "RUPIAH"),
    ],
)
def test_invalid_values_fail_closed(name, value):
    with pytest.raises(ConfigError) as excinfo:
        load_settings(env={name: value}, env_file=None)

    assert name in str(excinfo.value)


def test_secrets_are_not_shown_in_repr_or_errors():
    secret = "super-secret-value-123"
    settings = load_settings(
        env={"ANTHROPIC_API_KEY": secret, "WALI_GUARD_PRIVATE_KEY": secret}, env_file=None
    )

    assert secret not in repr(settings)
    assert secret not in settings.model_dump_json()
    assert settings.anthropic_api_key.get_secret_value() == secret

    with pytest.raises(ConfigError) as excinfo:
        load_settings(env={"SIM_SEED": secret}, env_file=None)
    assert secret not in str(excinfo.value)


def test_settings_are_immutable():
    settings = load_settings(env={}, env_file=None)

    with pytest.raises(Exception, match="frozen"):
        settings.sim_seed = 1


def test_env_file_is_read_and_overridden_by_env(tmp_path):
    env_file = tmp_path / ".env"
    lines = [
        "# a comment",
        "",
        "SIM_SEED=11",
        "WALI_AGENT_MODEL='from-file'",
        "not a valid line",
        "SIM_FAIL_RATE=0.5",
    ]
    env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    assert read_env_file(env_file) == {
        "SIM_SEED": "11",
        "WALI_AGENT_MODEL": "from-file",
        "SIM_FAIL_RATE": "0.5",
    }

    settings = load_settings(env={"SIM_SEED": "99"}, env_file=env_file)
    assert settings.sim_seed == 99
    assert settings.agent_model == "from-file"
    assert settings.sim_fail_rate == 0.5


def test_missing_env_file_is_fine(tmp_path):
    assert read_env_file(tmp_path / "absent.env") == {}
