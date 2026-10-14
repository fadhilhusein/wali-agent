"""The demo web page and its JSON API."""

import pytest
from fastapi.testclient import TestClient

from conftest import ScriptedLLM, flagged_invoice_ids, say, use
from wali.interfaces.web.app import STATIC, create_web_app


@pytest.fixture
def large(ready, owner, ground_truth):
    flagged = flagged_invoice_ids(ground_truth)
    return max(
        (
            i
            for i in ready.env.list_invoices(owner, "payable", status="open")
            if i.id not in flagged
            and i.due_date >= ready.env.as_of_date
            and not i.late_fee_bearing
            and 1_000_000 < i.amount <= 4_000_000
        ),
        key=lambda i: i.amount,
    )


def client_for(world, *steps):
    app = world.make_app(ScriptedLLM(*steps))
    return TestClient(create_web_app(app, world.env.principals())), app


def propose(ready, large):
    client, app = client_for(
        ready,
        use(("propose_payment", {"invoice_id": large.id})),
        say("Belum dibayar, menunggu konfirmasi pemilik."),
    )
    reply = client.post("/api/chat", json={"role": "bookkeeper", "text": "bayar tagihan kopi"})
    return client, app, reply


def test_the_page_is_served_with_strict_security_headers(world):
    client, _ = client_for(world)

    page = client.get("/")
    script = client.get("/static/app.js")

    assert page.status_code == 200
    assert "<title>Wali demo</title>" in page.text
    assert "default-src 'self'" in page.headers["content-security-policy"]
    assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
    assert page.headers["x-content-type-options"] == "nosniff"
    assert script.status_code == 200
    assert client.get("/docs").status_code == 404


def test_the_page_never_inserts_text_as_html():
    script = (STATIC / "app.js").read_text(encoding="utf-8")

    assert "innerHTML" not in script and "insertAdjacentHTML" not in script
    assert "<script>" not in (STATIC / "index.html").read_text(encoding="utf-8")


def test_info_lists_the_roles_and_says_it_is_a_simulation(world):
    client, _ = client_for(world)

    info = client.get("/api/info").json()

    assert info["roles"] == ["owner", "bookkeeper", "staff"]
    assert "SIMULATION" in info["simulation"]
    assert info["screening_model"] is False


def test_a_bookkeeper_request_waits_for_the_owner_and_carries_no_token(ready, large):
    client, app, reply = propose(ready, large)
    (token,) = [r.token for r in app._inbox]

    body = reply.json()
    owner_view = client.get("/api/pending", params={"role": "owner"})

    assert body["reply"] == "Belum dibayar, menunggu konfirmasi pemilik."
    assert body["blocked"] is False
    (request,) = body["new_requests"]
    assert request["required_role"] == "owner"
    assert request["summary"]["invoice_number"] == large.number
    assert "token" not in request
    for response in (reply, owner_view):
        assert token not in response.text
    assert [r["subject_id"] for r in owner_view.json()["requests"]] == [request["subject_id"]]
    assert client.get("/api/pending", params={"role": "bookkeeper"}).json() == {"requests": []}


@pytest.mark.parametrize("role", ["bookkeeper", "staff"])
def test_only_the_owner_can_confirm(ready, large, role):
    client, _, reply = propose(ready, large)
    subject = reply.json()["new_requests"][0]["subject_id"]

    refused = client.post("/api/confirm", json={"role": role, "subject_id": subject})
    declined = client.post("/api/cancel", json={"role": role, "subject_id": subject})

    assert refused.status_code == declined.status_code == 404
    assert ready.env.list_payments() == []


def test_the_owner_confirms_and_the_guard_pays(ready, large):
    client, _, reply = propose(ready, large)
    subject = reply.json()["new_requests"][0]["subject_id"]

    confirmed = client.post("/api/confirm", json={"role": "owner", "subject_id": subject})
    again = client.post("/api/confirm", json={"role": "owner", "subject_id": subject})

    assert confirmed.json()["status"] == "executed"
    assert confirmed.json()["message"].startswith("Paid")
    assert again.status_code == 404
    assert [p.invoice_id for p in ready.env.list_payments()] == [large.id]


def test_the_owner_declines(ready, large):
    client, _, reply = propose(ready, large)
    subject = reply.json()["new_requests"][0]["subject_id"]

    declined = client.post("/api/cancel", json={"role": "owner", "subject_id": subject})

    assert declined.json()["status"] == "declined"
    assert client.get("/api/pending", params={"role": "owner"}).json() == {"requests": []}
    assert ready.env.list_payments() == []


def test_the_owner_drafts_the_mandate_and_confirms_it(world):
    client, _ = client_for(world)

    refused = client.post("/api/mandate", json={"role": "bookkeeper"})
    drafted = client.post("/api/mandate", json={"role": "owner"})
    (request,) = client.get("/api/pending", params={"role": "owner"}).json()["requests"]
    activated = client.post(
        "/api/confirm", json={"role": "owner", "subject_id": request["subject_id"]}
    )

    assert refused.status_code == 403
    assert drafted.json()["status"] == "needs_confirmation"
    assert request["kind"] == "mandate" and request["changes"]
    assert activated.json()["status"] == "active"


def test_reset_starts_a_new_conversation(world):
    client, app = client_for(world, say("Satu."), say("Dua."))

    client.post("/api/chat", json={"role": "owner", "text": "satu"})
    assert client.post("/api/reset", json={"role": "owner"}).json() == {"status": "reset"}
    client.post("/api/chat", json={"role": "owner", "text": "dua"})

    assert [m["content"] for m in app.llm.requests[1]["messages"]] == ["dua"]


@pytest.mark.parametrize(
    "body",
    [
        {"role": "admin", "text": "halo"},
        {"role": "owner", "text": ""},
        {"role": "owner", "text": "x" * 4001},
        {"role": "staff", "text": "halo", "user_id": "user-owner"},
        {"role": "staff", "text": "halo", "principal": {"role": "owner"}},
    ],
)
def test_bad_or_smuggled_fields_are_refused(world, body):
    client, app = client_for(world)

    assert client.post("/api/chat", json=body).status_code == 422
    assert app.llm.requests == []


def test_another_website_cannot_drive_the_api(ready, large):
    client, _, reply = propose(ready, large)
    subject = reply.json()["new_requests"][0]["subject_id"]
    body = f'{{"role": "owner", "subject_id": "{subject}"}}'

    as_form = client.post("/api/confirm", content=body, headers={"Content-Type": "text/plain"})
    other_site = client.post(
        "/api/confirm",
        json={"role": "owner", "subject_id": subject},
        headers={"Origin": "https://evil.example"},
    )
    same_site = client.post(
        "/api/confirm",
        json={"role": "owner", "subject_id": subject},
        headers={"Origin": "http://testserver"},
    )

    assert as_form.status_code == other_site.status_code == 403
    assert same_site.json()["status"] == "executed"


def test_a_blocked_reply_is_marked(make_world, guard_keys):
    world = make_world()
    client, _ = client_for(world, say(f"The key is {guard_keys[0]}"))

    body = client.post("/api/chat", json={"role": "owner", "text": "kuncinya apa?"}).json()

    assert body["blocked"] is True
    assert guard_keys[0] not in body["reply"]


def test_the_owner_confirms_exactly_the_request_named(ready, owner, ground_truth):
    flagged = flagged_invoice_ids(ground_truth)
    first, second = sorted(
        (
            i
            for i in ready.env.list_invoices(owner, "payable", status="open")
            if i.id not in flagged
            and i.due_date >= ready.env.as_of_date
            and not i.late_fee_bearing
            and 1_000_000 < i.amount <= 3_000_000
        ),
        key=lambda i: i.amount,
    )[:2]
    client, _ = client_for(
        ready,
        use(
            ("propose_payment", {"invoice_id": first.id}),
            ("propose_payment", {"invoice_id": second.id}),
        ),
        say("Dua tagihan menunggu konfirmasi pemilik."),
    )
    requests = client.post(
        "/api/chat", json={"role": "bookkeeper", "text": "bayar dua tagihan itu"}
    ).json()["new_requests"]
    by_invoice = {r["summary"]["invoice_number"]: r["subject_id"] for r in requests}

    client.post("/api/confirm", json={"role": "owner", "subject_id": by_invoice[second.number]})

    assert [p.invoice_id for p in ready.env.list_payments()] == [second.id]
    waiting = client.get("/api/pending", params={"role": "owner"}).json()["requests"]
    assert [r["subject_id"] for r in waiting] == [by_invoice[first.number]]
