# mobile_control/api/translations.py

"""Incremental, single-language translation sync for the offline mobile mirror.

Returns DB `Translation` rows for one language (plus its parent locale) using the
same `modified`-watermark + stable-order pagination convention as the doctype pulls
(`["modified", ">", since]`, `order_by modified asc, name asc`, `limit_*`). The client
stores the returned `watermark` and sends it back as `since` to pull only what changed.

See docs/superpowers/specs/2026-06-10-get-translations-incremental-sync-design.md.
"""

from __future__ import annotations

from typing import Any

import frappe
from frappe import _
from frappe.translate import get_all_languages
from frappe.translate import get_parent_language
from frappe.utils import cint
from frappe.utils import get_build_version
from frappe.utils import now

DEFAULT_PAGE_LENGTH = 500
MAX_PAGE_LENGTH = 2000

_FIELDS = ["source_text", "context", "translated_text", "language", "modified"]


def _set_no_store() -> None:
	"""Forbid HTTP caching. The cache key here is (lang, since) with no version in the
	URL, so a cached response for a fixed cursor would mask later changes until TTL.
	Freshness is the client's watermark, not an HTTP TTL.
	"""
	headers = getattr(frappe.local, "response_headers", None)
	if headers is not None:
		headers["Cache-Control"] = "no-store"


@frappe.whitelist(methods=["GET"])
def get_translations(
	lang: str | None = None,
	since: str | None = None,
	limit_start: int = 0,
	limit_page_length: int = DEFAULT_PAGE_LENGTH,
	include_parent: int = 1,
) -> dict[str, Any]:
	"""Incremental DB-`Translation` delta for a single language. Authenticated only."""
	if frappe.session.user == "Guest":
		frappe.throw(_("Authentication required"), frappe.AuthenticationError)

	lang = (lang or "").strip()
	if not lang:
		frappe.throw(_("`lang` is required"), frappe.ValidationError)

	allowed = get_all_languages() or []
	if allowed and lang not in allowed:
		frappe.throw(_("Unknown language: {0}").format(lang), frappe.ValidationError)

	page_length = min(max(cint(limit_page_length) or DEFAULT_PAGE_LENGTH, 1), MAX_PAGE_LENGTH)
	start = max(cint(limit_start), 0)

	langs = [lang]
	if cint(include_parent):
		parent = get_parent_language(lang)
		if parent and parent != lang:
			langs.append(parent)

	filters: dict[str, Any] = {"language": ["in", langs]}
	since = (since or "").strip() or None
	if since:
		filters["modified"] = [">", since]

	# `get_list` applies the caller's read permission on Translation (the Mobile User
	# role holds it via the Custom DocPerm fixture), so results are permission-accurate.
	rows = frappe.get_list(
		"Translation",
		filters=filters,
		fields=_FIELDS,
		order_by="modified asc, name asc",
		limit_start=start,
		limit_page_length=page_length,
	)

	entries = [
		{
			"source_text": r.source_text,
			"context": r.context,
			"translated_text": r.translated_text,
			"language": r.language,
			"modified": str(r.modified),
		}
		for r in rows
	]
	watermark = max((e["modified"] for e in entries), default=since)

	_set_no_store()

	return {
		"lang": lang,
		"since": since,
		"server_time": now(),
		"watermark": watermark,
		"full_pull_token": get_build_version(),
		"count": len(entries),
		"has_more": len(rows) == page_length,
		"entries": entries,
	}
