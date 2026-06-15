# Copyright (c) 2026, Dhwani RIS and contributors
# For license information, please see license.txt

"""Ingest endpoint for SDK-captured mobile push failures.

The SDK aggregates terminal push failures per drain (by signature) and POSTs
one record per signature here. We UPSERT by the client-supplied signature —
verbatim, never recomputed (spec §6) — accumulate the occurrence count, keep a
rolling window of the most-recent 5 example payloads, and render a replayable
CURL per example with the host and token redacted to placeholders.
"""

import json
from datetime import datetime
from datetime import timezone
from typing import Any
from urllib.parse import urlsplit
from urllib.parse import urlunsplit

import frappe
from frappe import _
from frappe.utils import now_datetime

MAX_EXAMPLES = 5


def render_curl(method: str, request_url: str, request_payload: str | None) -> str:
	"""Build a replayable CURL with host + token as placeholders.

	The stored URL is the production host; a developer replays against a
	dev/staging bench, so the host is emitted as `{{HOST}}` and the auth token
	as `{{TOKEN}}`. Headers are a canonical set (the endpoint never sees the
	client's real headers, and the token is a placeholder anyway).
	"""
	parts = urlsplit(request_url or "")
	path_only = urlunsplit(("", "", parts.path, parts.query, parts.fragment))
	lines = [
		f"curl -X {method} '{{{{HOST}}}}{path_only}'",
		"  -H 'Authorization: Bearer {{TOKEN}}'",
		"  -H 'Content-Type: application/json'",
	]
	if request_payload:
		# single-quote-safe: close, escaped quote, reopen
		safe = request_payload.replace("'", "'\\''")
		lines.append(f"  -d '{safe}'")
	return " \\\n".join(lines)


def _millis_to_datetime(millis: Any) -> datetime | None:
	"""Convert client UTC epoch-millis to a naive UTC datetime (Frappe stores
	naive datetimes). Returns None when absent/invalid."""
	if not millis:
		return None
	try:
		return datetime.fromtimestamp(int(millis) / 1000, tz=timezone.utc).replace(tzinfo=None)
	except (TypeError, ValueError, OSError):
		return None


def _append_examples(doc, incoming: list[dict[str, Any]]) -> None:
	"""Append incoming examples, render their CURL, evict to most-recent 5."""
	for ex in incoming or []:
		doc.append(
			"examples",
			{
				"mobile_uuid": ex.get("mobile_uuid"),
				"request_payload": ex.get("request_payload"),
				"response_body": ex.get("response_body"),
				"occurred_at": _millis_to_datetime(ex.get("occurred_at_millis")),
				"curl_command": render_curl(doc.request_method, doc.request_url, ex.get("request_payload")),
			},
		)
	# Rolling last-N: keep the most-recent MAX_EXAMPLES by occurred_at. The
	# tuple key sorts None-dated rows first (oldest) without comparing
	# datetime against None.
	rows = sorted(
		doc.examples,
		key=lambda r: (r.occurred_at is not None, r.occurred_at or datetime.min),
	)
	if len(rows) > MAX_EXAMPLES:
		keep = {id(r) for r in rows[-MAX_EXAMPLES:]}
		doc.examples = [r for r in doc.examples if id(r) in keep]
		for i, r in enumerate(doc.examples):
			r.idx = i + 1


@frappe.whitelist(methods=["POST"])
def report_error(payload: Any) -> dict[str, str]:
	"""UPSERT one aggregated error-log record by signature.

	Args:
	    payload: dict (or JSON string) produced by the SDK's ErrorLogCollector.
	"""
	if isinstance(payload, str):
		try:
			payload = json.loads(payload)
		except (ValueError, TypeError):
			frappe.throw(_("`payload` must be a JSON object"), frappe.ValidationError)
	if not isinstance(payload, dict):
		frappe.throw(_("`payload` must be an object"), frappe.ValidationError)

	signature = (payload.get("signature") or "").strip()
	if not signature:
		frappe.throw(_("`signature` is required"), frappe.ValidationError)

	count = int(payload.get("occurrence_count") or 1)
	roles = payload.get("error_user_roles") or []
	roles_str = ", ".join(roles) if isinstance(roles, list) else str(roles)
	error_user = payload.get("error_user") or ""

	existing = frappe.db.get_value("Mobile Error Log", {"signature": signature}, "name")
	if existing:
		doc = frappe.get_doc("Mobile Error Log", existing)
		doc.occurrence_count = (doc.occurrence_count or 0) + count
	else:
		doc = frappe.new_doc("Mobile Error Log")
		doc.signature = signature
		doc.doctype_name = payload.get("doctype_name")
		doc.operation = payload.get("operation")
		doc.http_status = payload.get("http_status")
		doc.exc_type = payload.get("exc_type")
		doc.request_method = payload.get("request_method")
		doc.request_url = payload.get("request_url")
		doc.occurrence_count = count

	# Always refresh the volatile fields with the latest snapshot.
	doc.last_seen = now_datetime()
	doc.error_user_roles = roles_str
	if error_user:
		doc.error_user = error_user
		doc.error_user_link = error_user  # convenience; ignore_links on save
	doc.trace_id = payload.get("trace_id") or None
	if payload.get("app_version"):
		doc.app_version = payload.get("app_version")
	if payload.get("device"):
		doc.device = payload.get("device")

	_append_examples(doc, payload.get("examples"))

	# ignore_links: a deactivated/renamed error_user must never fail the insert
	# (spec §9 #2). ignore_permissions: the doctype has no create perm by design.
	doc.flags.ignore_links = True
	doc.flags.ignore_permissions = True
	doc.save(ignore_permissions=True)
	# No explicit commit: this whitelisted endpoint is reached over HTTP, and Frappe
	# commits the request transaction on a successful response.
	return {"status": "ok", "name": doc.name}
