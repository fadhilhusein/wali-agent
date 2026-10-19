"""Entry points and edge input of the CLI and the web page, and the organiser placeholder.
Nothing here starts a server, calls a model, or touches the network."""

import datetime as dt

import pytest
from fastapi.testclient import TestClient

from conftest import ScriptedLLM, say
from wali.app import SetupError
from wali.interfaces import cli
from wali.interfaces.cli import run_cli
from wali.interfaces.web import app as web_app
from wali.interfaces.web.app import create_web_app
from wali.models import NewBookEntry
from wali.tools.base import ToolFailure
from wali.tools.organiser_env import OrganiserEnvironment

# --- CLI input handling ----------------------------------------------------------------------


def session(world, principals, lines, role="owner", llm=None):
    app = world.make_app(llm or ScriptedLLM())
    pending = iter(lines)
    printed = []

    def read(prompt):
        try:
            line = next(pending)
        except StopIteration:
            raise EOFError from None
        printed.append(f"{prompt}{line}")
        return line

    run_cli(app, principals, role=role, input_fn=read, output_fn=printed.append)
    return printed


def test_the_cli_greets_with_the_role_and_the_simulation_note(world, principals):
    printed = session(world, principals, [])

    assert "SIMULATION" in printed[0]
    assert printed[1].startswith("You are: owner (")


def test_blank_lines_are_skipped_and_do_not_reach_the_model(world, principals):
    llm = ScriptedLLM()

    session(world, principals, ["", "   ", "/quit"], llm=llm)

    assert llm.requests == []


@pytest.mark.parametrize("closing", [EOFError(), KeyboardInterrupt()])
def test_the_cli_ends_quietly_when_input_ends(world, principals, closing):
    app = world.make_app(ScriptedLLM())

    def read(prompt):
        raise closing

    printed = []
    run_cli(app, principals, input_fn=read, output_fn=printed.append)

    assert printed[-1] == ""


@pytest.mark.parametrize("leave", ["/quit", "/exit"])
def test_both_leave_commands_end_the_session(world, principals, leave):
    printed = session(world, principals, [leave, "/help"])

    assert not any("Commands:" in line for line in printed)


@pytest.mark.parametrize("argument", ["0", "-1", "1.5", "abc", "1 2"])
def test_a_confirm_or_cancel_number_must_be_a_positive_whole_number(world, principals, argument):
    printed = session(world, principals, [f"/confirm {argument}", f"/cancel {argument}"])

    assert printed.count("Give the number of the item, for example /confirm 1") == 2


def test_confirming_or_declining_an_item_that_does_not_exist_changes_nothing(world, principals):
    printed = session(world, principals, ["/confirm 7", "/cancel 7", "/cancel"])

    assert "There is no such item waiting for you." in printed
    assert printed.count("Nothing to decline.") == 2
    assert world.env.list_payments() == []


def test_the_bookkeeper_cannot_draft_the_mandate_from_the_cli(world, principals):
    printed = session(world, principals, ["/mandate"], role="bookkeeper")

    assert "guard> Only the owner can set or change the spending mandate." in printed
    assert world.guard.collect_confirmation_requests() == []


def test_the_review_list_is_empty_for_the_owner_when_nothing_is_flagged(world, principals):
    printed = session(world, principals, ["/review"])

    assert "Nothing is flagged (or your role cannot see the list)." in printed


def test_a_command_with_trailing_spaces_still_works(world, principals):
    printed = session(world, principals, ["/pending   "])

    assert "Nothing is waiting for your confirmation." in printed


def test_a_slash_in_the_middle_of_a_message_is_chat_not_a_command(world, principals):
    llm = ScriptedLLM(say("ok"))

    session(world, principals, ["bayar /confirm 1"], llm=llm)

    assert len(llm.requests) == 1


# --- CLI start-up ----------------------------------------------------------------------------


def test_the_cli_refuses_to_start_when_the_app_cannot_be_built(monkeypatch, capsys):
    def broken(settings):
        raise SetupError("no guard key")

    monkeypatch.setattr(cli, "load_settings", lambda: object())
    monkeypatch.setattr(cli, "build_app", broken)

    assert cli.main([]) == 1
    assert "Cannot start: no guard key" in capsys.readouterr().err


def test_the_cli_starts_the_chat_with_the_chosen_role(world, principals, monkeypatch):
    app = world.make_app(ScriptedLLM())
    started = {}
    monkeypatch.setattr(cli, "load_settings", lambda: object())
    monkeypatch.setattr(cli, "build_app", lambda settings: app)
    monkeypatch.setattr(
        cli, "run_cli", lambda a, p, role: started.update(app=a, role=role, roles=set(p))
    )

    assert cli.main(["--role", "bookkeeper"]) == 0
    assert started == {"app": app, "role": "bookkeeper", "roles": {"owner", "bookkeeper", "staff"}}


def test_the_cli_rejects_a_role_it_does_not_know():
    with pytest.raises(SystemExit) as stopped:
        cli.main(["--role", "admin"])

    assert stopped.value.code == 2


# --- Web page --------------------------------------------------------------------------------


def web(world, principals=None, *steps):
    app = world.make_app(ScriptedLLM(*steps))
    return TestClient(
        create_web_app(app, principals or world.env.principals()), base_url="http://127.0.0.1:8000"
    ), app


def test_a_role_missing_from_the_business_is_not_found_and_not_listed(world):
    without_staff = {k: v for k, v in world.env.principals().items() if k != "staff"}
    client, _ = web(world, without_staff)

    assert client.get("/api/info").json()["roles"] == ["owner", "bookkeeper"]
    assert client.post("/api/chat", json={"role": "staff", "text": "halo"}).status_code == 404
    assert client.get("/api/pending", params={"role": "staff"}).status_code == 404


def test_an_unknown_role_in_the_query_is_refused(world):
    client, _ = web(world)

    assert client.get("/api/pending", params={"role": "admin"}).status_code == 422
    assert client.get("/api/pending").status_code == 422


@pytest.mark.parametrize("path", ["/api/confirm", "/api/cancel"])
def test_confirming_or_declining_an_unknown_id_is_404(world, path):
    client, _ = web(world)

    reply = client.post(path, json={"role": "owner", "subject_id": "nope"})

    assert reply.status_code == 404


@pytest.mark.parametrize("subject", ["", "x" * 101])
def test_a_subject_id_must_be_between_1_and_100_characters(world, subject):
    client, _ = web(world)

    reply = client.post("/api/confirm", json={"role": "owner", "subject_id": subject})

    assert reply.status_code == 422


def test_a_message_of_exactly_the_maximum_length_is_accepted(world):
    client, app = web(world, None, say("ok"))

    reply = client.post("/api/chat", json={"role": "owner", "text": "x" * 4000})

    assert reply.status_code == 200
    assert len(app.llm.requests) == 1


def test_a_failing_mandate_draft_is_a_503_without_details(world, monkeypatch):
    def broken(app, owner):
        raise ToolFailure("database path /secret/place")

    monkeypatch.setattr(web_app, "draft_demo_mandate", broken)
    client, _ = web(world)

    reply = client.post("/api/mandate", json={"role": "owner"})

    assert reply.status_code == 503
    assert "secret" not in reply.text


def test_security_headers_are_on_error_replies_too(world):
    client, _ = web(world)

    reply = client.get("/api/pending", params={"role": "admin"})

    assert reply.headers["x-content-type-options"] == "nosniff"
    assert reply.headers["cache-control"] == "no-store"


def test_a_post_without_json_content_type_is_refused_before_it_reaches_the_app(world):
    client, app = web(world)

    reply = client.post(
        "/api/reset", content='{"role": "owner"}', headers={"content-type": "text/plain"}
    )

    assert reply.status_code == 403
    assert app.llm.requests == []


# --- Web start-up ----------------------------------------------------------------------------


@pytest.fixture
def served(world, monkeypatch):
    """Replace the real server and app builder; record what the entry point would run."""
    import uvicorn

    app = world.make_app(ScriptedLLM())
    ran = {}
    monkeypatch.setattr(web_app, "load_settings", lambda: object())
    monkeypatch.setattr(web_app, "build_app", lambda settings: app)
    monkeypatch.setattr(uvicorn, "run", lambda api, host, port: ran.update(host=host, port=port))
    return ran


def test_the_web_page_listens_on_this_computer_by_default(served, capsys):
    assert web_app.main([]) == 0

    assert served == {"host": "127.0.0.1", "port": 8000}
    assert "WARNING" not in capsys.readouterr().err


def test_listening_on_another_address_prints_a_warning_about_the_missing_login(served, capsys):
    assert web_app.main(["--host", "0.0.0.0", "--port", "9000"]) == 0

    assert served == {"host": "0.0.0.0", "port": 9000}
    assert "anyone who can reach it can act as the owner" in capsys.readouterr().err


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1"])
def test_loopback_addresses_do_not_warn(served, capsys, host):
    web_app.main(["--host", host])

    assert "WARNING" not in capsys.readouterr().err


def test_the_web_page_does_not_start_when_set_up_wrongly(monkeypatch, capsys):
    def broken(settings):
        raise SetupError("no guard key")

    monkeypatch.setattr(web_app, "load_settings", lambda: object())
    monkeypatch.setattr(web_app, "build_app", broken)

    assert web_app.main([]) == 1
    assert "Cannot start: no guard key" in capsys.readouterr().err


# --- Organiser placeholder -------------------------------------------------------------------


def test_every_method_of_the_organiser_environment_says_it_is_not_implemented(owner):
    env = OrganiserEnvironment()
    day = dt.date(2026, 10, 1)
    calls = [
        lambda: env.get_balance(owner),
        lambda: env.list_transactions(owner, day, day),
        lambda: env.list_invoices(owner, "payable"),
        lambda: env.get_supplier(owner, "sup-1"),
        lambda: env.get_book_entries(owner, day, day),
        lambda: env.record_book_entry(
            owner,
            NewBookEntry(date=day, amount=1, direction="in", category="c", description=""),
        ),
        lambda: env.execute_payment(None),
    ]

    for call in calls:
        with pytest.raises(NotImplementedError, match="not implemented yet"):
            call()
