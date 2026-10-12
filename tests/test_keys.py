import base64
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.exceptions import InvalidSignature

from wali.config import read_env_file
from wali.guard.keys import KeyFormatError, generate_keypair, load_private_key, load_public_key

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "gen_guard_key.py"


def run_script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], capture_output=True, text=True, check=False
    )


def test_generated_pair_signs_and_verifies():
    private_b64, public_b64 = generate_keypair()
    signature = load_private_key(private_b64).sign(b"message")

    load_public_key(public_b64).verify(signature, b"message")
    with pytest.raises(InvalidSignature):
        load_public_key(public_b64).verify(signature, b"tampered")


def test_each_pair_is_different_and_other_keys_do_not_verify():
    private_a, public_a = generate_keypair()
    _, public_b = generate_keypair()

    assert public_a != public_b
    signature = load_private_key(private_a).sign(b"message")
    with pytest.raises(InvalidSignature):
        load_public_key(public_b).verify(signature, b"message")


@pytest.mark.parametrize(
    "encoded", ["", "not base64 !!", base64.b64encode(b"too short").decode(), "A" * 100]
)
def test_malformed_keys_are_rejected_without_echoing_them(encoded):
    for loader in (load_private_key, load_public_key):
        with pytest.raises(KeyFormatError) as excinfo:
            loader(encoded)
        if encoded:
            assert encoded not in str(excinfo.value)


def test_script_writes_env_file_without_printing_the_private_key(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("SIM_SEED=5\nWALI_GUARD_PRIVATE_KEY=\n", encoding="utf-8")

    result = run_script("--write-env", str(env_file))

    assert result.returncode == 0, result.stderr
    values = read_env_file(env_file)
    assert values["SIM_SEED"] == "5"
    private_b64, public_b64 = values["WALI_GUARD_PRIVATE_KEY"], values["WALI_GUARD_PUBLIC_KEY"]
    assert private_b64 not in result.stdout + result.stderr
    assert public_b64 in result.stdout
    signature = load_private_key(private_b64).sign(b"m")
    load_public_key(public_b64).verify(signature, b"m")


def test_script_refuses_to_replace_an_existing_key_unless_forced(tmp_path):
    env_file = tmp_path / ".env"
    assert run_script("--write-env", str(env_file)).returncode == 0
    first = read_env_file(env_file)

    refused = run_script("--write-env", str(env_file))
    assert refused.returncode == 1
    assert read_env_file(env_file) == first

    forced = run_script("--write-env", str(env_file), "--force")
    assert forced.returncode == 0
    assert read_env_file(env_file)["WALI_GUARD_PRIVATE_KEY"] != first["WALI_GUARD_PRIVATE_KEY"]
