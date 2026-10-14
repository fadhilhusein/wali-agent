"""Pieces shared by the CLI, the Telegram bot, and the web page."""

from __future__ import annotations

from typing import Any

from wali.app import WaliApp
from wali.guard.service import ConfirmationRequest, MandateDecision, MandateRequest
from wali.models import Principal

SIMULATION_NOTE = "SIMULATION: synthetic data, no real bank and no real money."

# The mandate from the build specification's example, used by /mandate in the demo.
DEMO_MANDATE = {
    "per_payment": "5000000",
    "per_week": "15000000",
    "confirm_above": "1000000",
    "min_cash_buffer": "3000000",
    "valid_days": 30,
    "bookkeeper_can_propose": True,
    "bookkeeper_max_propose": "5000000",
}


def verified_supplier_ids(app: WaliApp, owner: Principal) -> list[str]:
    """Suppliers that have invoiced the business and whose account is verified."""
    supplier_ids = sorted({i.counterparty_id for i in app.env.list_invoices(owner, "payable")})
    return [s for s in supplier_ids if app.env.get_supplier(owner, s).account_verified]


def draft_demo_mandate(app: WaliApp, owner: Principal) -> MandateDecision:
    """Draft the demo mandate for every verified supplier. It still needs the owner's
    confirmation, like any other draft."""
    request = MandateRequest(allowed_suppliers=verified_supplier_ids(app, owner), **DEMO_MANDATE)
    return app.guard.draft_mandate(owner, request)


def describe(request: ConfirmationRequest, number: int | None = None) -> str:
    """What the person is being asked to confirm, in full, before they decide. The token is
    never part of it."""
    label = f"[{number}] " if number is not None else ""
    lines = [f"{label}{request.kind.upper()} waiting for the {request.required_role}"]
    lines.append(f"    requested by: {request.requested_by}")
    summary = request.summary
    if summary is not None:
        lines += [
            f"    supplier:     {summary.supplier_name}",
            f"    invoice:      {summary.invoice_number} (due {summary.due_date.isoformat()})",
            f"    amount:       {summary.amount:,} {summary.currency}",
            f"    to account:   {summary.registered_account} (registered)",
            f"    balance after: {summary.balance_after:,} {summary.currency}",
        ]
    lines += [f"    - {change}" for change in request.changes]
    lines += [f"    ! {warning.message}" for warning in request.risk_warnings]
    lines.append(f"    expires at:   {request.expires_at.strftime('%H:%M:%S')}")
    return "\n".join(lines)


def request_view(request: ConfirmationRequest) -> dict[str, Any]:
    """A confirmation request as plain data for a client, without its token."""
    return request.model_dump(mode="json", exclude={"token"})
