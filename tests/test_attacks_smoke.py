"""Every attack, against a model that has been fully taken over.

The scripted model (``eval.scripted.HostileLLM``) does the worst it can with the ten tools: it
reads everything, asks to pay every open invoice, drafts a huge mandate, records income, and then
tries to show the person everything it saw, or the system prompt. What must still hold is what
the guard, the environment, and the outgoing screen enforce, whatever the model does:
``eval.checks.ALWAYS`` plus the restricted-data invariant.

Whether a well-behaved model also keeps the stricter invariants an attack declares (for example
no payment at all) is measured with the real model by ``python -m eval.run_eval --suite attacks``.
"""

import pytest
from eval.attacks import CATEGORIES, load_attacks, run_attack, seed_edits
from eval.checks import ALWAYS, INVARIANTS, check_invariants
from eval.harness import fresh_world
from eval.scripted import HostileLLM

from conftest import SEED_DIR
from wali.config import load_settings
from wali.guard.sentinel import BLOCKED_REPLY

ATTACKS = load_attacks()
GUARANTEED = (*ALWAYS, "no_restricted_data_leak")


@pytest.fixture(scope="module")
def settings():
    return load_settings(env={"WALI_SEED_DIR": str(SEED_DIR)}, env_file=None)


@pytest.mark.parametrize("show", ["data", "prompt"])
@pytest.mark.parametrize("attack", ATTACKS, ids=lambda a: a.id)
def test_a_taken_over_model_still_cannot_break_what_the_guard_enforces(settings, attack, show):
    with fresh_world(
        settings,
        HostileLLM(show, settings.seed_dir),
        seed_edits=seed_edits(attack, settings.seed_dir),
    ) as world:
        result = run_attack(attack, world)
        held = check_invariants(world, ["no_restricted_data_leak"])

    assert {name: problems for name, problems in held.items() if problems} == {}
    assert set(held) == set(GUARANTEED)
    if show == "prompt":
        assert all(reply == BLOCKED_REPLY for reply in result.replies)
    else:
        # The dump is shown, so the leak checks above really looked at it.
        assert all(reply != BLOCKED_REPLY for reply in result.replies)


def test_the_attack_file_has_five_attacks_per_category():
    assert len(ATTACKS) == 20
    for category in CATEGORIES:
        assert sum(a.category == category for a in ATTACKS) == 5


def test_every_attack_names_only_known_invariants():
    for attack in ATTACKS:
        assert set(attack.invariants) <= set(INVARIANTS)
