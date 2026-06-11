# mobile_control/api/sync_details.py

"""Pre-flight sync manifest for the offline mobile mirror (#27 / SDK #49).

The mobile client sends the INCREMENTAL doctypes it is about to pull, each
with its own `since` watermark (the SDK's per-doctype pull cursor). The
server returns, per doctype, whether the user has any readable rows modified
since that watermark (`changed`), an advisory bounded count, and whether the
doctype's mobile meta watermark moved (`meta_bumped`). The SDK skips pulling
doctypes that are unchanged and not meta-bumped.

Permission model mirrors `bulk_fetch.py`: a doctype-level `has_permission`
gate plus `frappe.get_list` (which applies role perms AND User Permission
query conditions) so counts reflect only what the user could actually pull.
"""

import json
from typing import Any

import frappe
from frappe import _

# Cap the request list so a runaway client can't fan out unboundedly.
MAX_DOCTYPES = 100
# Advisory count is bounded — the SDK gates no decision on it (changed does).
COUNT_CAP = 500


def _parse_doctypes(raw: Any) -> list[tuple[str, str | None]]:
	if isinstance(raw, str):
		try:
			raw = json.loads(raw)
		except (ValueError, TypeError):
			frappe.throw(_("`doctypes` must be a JSON array"), frappe.ValidationError)
	if not isinstance(raw, list):
		frappe.throw(_("`doctypes` must be a list"), frappe.ValidationError)
	if len(raw) > MAX_DOCTYPES:
		frappe.throw(
			_("Request exceeds limit of {0} doctypes").format(MAX_DOCTYPES),
			frappe.ValidationError,
		)
	out: list[tuple[str, str | None]] = []
	for item in raw:
		if not isinstance(item, dict):
			continue
		dt = item.get("doctype")
		if not isinstance(dt, str) or not dt.strip():
			continue
		since = item.get("since")
		since = since if isinstance(since, str) and since.strip() else None
		out.append((dt.strip(), since))
	return out


def _meta_watermarks() -> dict[str, str]:
	"""Per-doctype mobile meta watermark from Mobile Configuration."""
	wm: dict[str, str] = {}
	try:
		config = frappe.get_single("Mobile Configuration")
		for row in config.table_lwis or []:
			if row.mobile_workspace_item and row.doctype_meta_modified_at:
				wm[row.mobile_workspace_item] = str(row.doctype_meta_modified_at)
	except Exception:
		frappe.log_error(f"sync_details meta watermark read failed: {frappe.get_traceback()}")
	return wm


@frappe.whitelist(methods=["POST"])
def get_sync_details(doctypes: Any) -> dict[str, Any]:
	parsed = _parse_doctypes(doctypes)
	meta_wm = _meta_watermarks()
	result: list[dict[str, Any]] = []
	for dt, since in parsed:
		try:
			if not frappe.db.exists("DocType", dt) or not frappe.has_permission(dt, "read"):
				result.append({"doctype": dt, "changed": False, "count": 0, "meta_bumped": False})
				continue
			# Strict `>` is REQUIRED, not a typo vs the pull's `>=`: `since`
			# only ever comes from a COMPLETED cursor (drain reached an empty
			# page), so every row `>= since` is already applied and new writes
			# are strictly `> since`. `>=` here would always re-match the
			# cursor's own last row and make `changed` perpetually true.
			filters = [["modified", ">", since]] if since else []
			# Single permission-accurate query per doctype (was two: existence +
			# count). `frappe.get_list` (NOT get_all) still applies role perms,
			# User Permissions, and permission_query_conditions, so results
			# reflect only what the user could actually pull. Bounded by COUNT_CAP.
			names = frappe.get_list(dt, filters=filters, limit_page_length=COUNT_CAP, pluck="name")
			changed = bool(names) or not since
			count = len(names) if changed else 0
			wm = meta_wm.get(dt)
			meta_bumped = bool(wm and since and wm > since)
			result.append({"doctype": dt, "changed": changed, "count": count, "meta_bumped": meta_bumped})
		except Exception:
			# Fail-safe: OMIT this doctype from the manifest on any error.
			# `doctypesToSkip` only skips doctypes PRESENT with changed==false,
			# so an omitted doctype is pulled — never wrongly skipped. One bad
			# doctype must not 500 the whole manifest (which would disable the
			# optimization for every doctype this cycle).
			frappe.log_error(f"sync_details({dt}) failed: {frappe.get_traceback()}")
			continue
	return {"doctypes": result, "delete_signals": 0}
