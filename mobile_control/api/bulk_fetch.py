# mobile_control/api/bulk_fetch.py

"""Bulk document fetch endpoint for the offline mobile mirror.

Replaces the SDK's N+1 pattern of one `/api/resource/<doctype>/<name>`
per row. The mobile client sends a list of names; the server returns
the corresponding `as_dict()` payloads in a single round-trip, with
child tables embedded.

Security model — derived from Frappe's official guidance
(https://github.com/frappe/erpnext/wiki/Code-Security-Guidelines):

  * `frappe.get_doc` does NOT check permission by default — every doc
    is gated through `doc.check_permission("read")` before it is
    appended to the response.
  * Doctype-level read access is verified up-front via
    `frappe.has_permission(doctype, "read")` so unauthorized users
    receive a single 403 instead of a list of silently-skipped names.
  * Child doctypes are explicitly rejected. Frappe's permission model
    is parent-anchored — children inherit access from their parent —
    so callers must fetch the parent (children are returned inside
    `as_dict()` automatically).
  * Names are bounded to MAX_BATCH per call so a runaway client cannot
    produce an unbounded SQL fan-out.

Returned shape: `[{...doc1}, {...doc2}, ...]` — the order may NOT match
the input, and missing / forbidden / non-existent names are silently
dropped. Callers must key by `name` themselves; they cannot assume a
positional join.
"""

import json
from typing import Any

import frappe
from frappe import _

# Hard cap to bound server work / response payload. The SDK chunks
# larger lists client-side; keep this in sync with the constant in
# `doctype_service.dart`.
MAX_BATCH = 200


def _parse_names(raw: Any) -> list[str]:
	"""Coerce the `names` argument to a list[str].

	Accepts: a JSON-encoded string (form-encoded body), a Python list,
	or a list-of-anything (each element is stringified). Rejects all
	other shapes with a ValidationError.
	"""
	if isinstance(raw, str):
		try:
			raw = json.loads(raw)
		except (ValueError, TypeError):
			frappe.throw(
				_("`names` must be a JSON array of strings"),
				frappe.ValidationError,
			)

	if not isinstance(raw, list):
		frappe.throw(_("`names` must be a list"), frappe.ValidationError)

	cleaned: list[str] = []
	for n in raw:
		if not isinstance(n, str):
			continue
		n = n.strip()
		if n:
			cleaned.append(n)
	return cleaned


@frappe.whitelist(methods=["POST"])
def get_docs_with_children(doctype: str, names: Any) -> list[dict[str, Any]]:
	"""Bulk-fetch full parent docs (with embedded child rows).

	Args:
	    doctype: Parent DocType name.
	    names:   List of document `name` values to fetch. May arrive as
	             a JSON string when the client sends form-encoded data.

	Returns:
	    List of `as_dict()` payloads for the docs the current session
	    user is allowed to read. Order is not preserved; missing /
	    forbidden / non-existent names are silently dropped.

	Raises:
	    PermissionError: User lacks read permission on the doctype, or
	        the doctype is a child table (must be fetched via parent).
	    ValidationError: doctype/names are missing or malformed, or the
	        batch exceeds MAX_BATCH.
	"""
	# Type / shape validation. Frappe v15+ also enforces the annotation
	# automatically, but explicit checks keep the failure mode clear.
	if not isinstance(doctype, str) or not doctype.strip():
		frappe.throw(_("`doctype` is required"), frappe.ValidationError)
	doctype = doctype.strip()

	parsed_names = _parse_names(names)
	if not parsed_names:
		return []

	if len(parsed_names) > MAX_BATCH:
		frappe.throw(
			_("Batch size {0} exceeds limit of {1}").format(len(parsed_names), MAX_BATCH),
			frappe.ValidationError,
		)

	# Reject child doctypes — they are not independently permissioned
	# in Frappe; clients should fetch the parent and read the embedded
	# children from `as_dict()`.
	meta = frappe.get_meta(doctype)
	if meta.istable:
		frappe.throw(
			_(
				"`{0}` is a child doctype; fetch its parent and read child rows from the returned document."
			).format(doctype),
			frappe.PermissionError,
		)

	# Doctype-level gate: fast 403 for users with zero access. This
	# also surfaces non-existent doctypes as PermissionError (Frappe
	# raises during `has_permission` lookup).
	if not frappe.has_permission(doctype, "read"):
		raise frappe.PermissionError(_("Not permitted to read {0}").format(doctype))

	out: list[dict[str, Any]] = []
	for name in parsed_names:
		try:
			doc = frappe.get_doc(doctype, name)
			# Per-row permission check. `check_permission` honors role
			# perms, User Permissions, permission conditions, and the
			# `if_owner` flag — exactly the same gating as
			# `/api/resource/<doctype>/<name>`.
			doc.check_permission("read")
		except (frappe.DoesNotExistError, frappe.PermissionError):
			# Silently skip — caller treats absent names as "you don't
			# have it" without distinguishing the two cases (this is
			# the same observable behaviour as the existing per-row
			# REST path, where 404/403 are handled identically).
			continue

		# `as_dict()` includes all standard fields plus child Table
		# rows as nested lists of dicts — same shape as
		# `/api/resource/<doctype>/<name>`.
		out.append(doc.as_dict())

	return out
