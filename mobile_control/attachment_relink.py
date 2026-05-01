"""Mobile attachment relink hook.

The SDK uploads pending attachments BEFORE the parent INSERT/UPDATE so that
the parent payload can carry the resolved file_url. Each upload is sent
**fully unattached**: no `dt`, no `dn`. Frappe v16's File controller
rejects `attached_to_doctype` with empty `attached_to_name`
(file.py:151), so partial-attach uploads are not viable; the SDK leaves
all `attached_to_*` columns NULL and lets the post-save hooks rewire.

After the parent doc is saved:

  - **Parent docs:** Frappe's stock `attach_files_to_document`
    (registered on `*.on_update` in apps/frappe/frappe/hooks.py:155-166)
    walks the parent's Attach/Attach Image fields, finds File rows where
    all three `attached_to_*` are NULL and the `file_url` matches, and
    rewires them to (doc.doctype, doc.name, df.fieldname). We rely on
    that for parents.

  - **Child rows:** stock skips children. In v16, child rows save via
    raw `db_update()` (frappe/model/document.py:613-648) — no lifecycle
    hooks fire, so `attach_files_to_document` never reaches them. This
    hook fills that gap by walking the parent's child tables on the
    parent's `on_update` and replicating stock's relink logic for each
    child row.
"""

from __future__ import annotations

import frappe


_ATTACH_FIELDTYPES = ("Attach", "Attach Image")
_FILE_URL_PREFIXES = ("/files", "/private/files")


def relink_mobile_files(doc, method=None):
    """Catch-all `on_update` / `on_update_after_submit` hook.

    Fast-exits when the doc has no `mobile_uuid` (i.e. not a mobile-sync
    doctype). The check is one attribute lookup; the hook is registered
    on `*` so it fires on every save site-wide and the fast-exit is the
    cost paid by non-mobile saves.

    Walks the doc's child tables. Per-child relink is the value-add over
    stock — stock already handles the parent's own Attach fields.
    """
    if not getattr(doc, "mobile_uuid", None):
        return

    for tf in doc.meta.get_table_fields():
        for child in (doc.get(tf.fieldname) or []):
            _relink_attach_fields(child)


def _relink_attach_fields(target):
    """For each Attach/Attach Image field on `target` (a child row),
    rewire the matching unattached File row to point at `target.name`.

    Match shape mirrors stock `attach_files_to_document`:
      `(file_url, attached_to_doctype IS NULL, attached_to_name IS NULL,
        attached_to_field IS NULL)`

    Uses `frappe.db.set_value` (raw UPDATE, no controller hooks) so we
    don't recurse into our own `on_update` registration when File is
    updated.
    """
    for df in target.meta.get(
        "fields", {"fieldtype": ["in", list(_ATTACH_FIELDTYPES)]}
    ):
        value = target.get(df.fieldname) or ""
        if not value.startswith(_FILE_URL_PREFIXES):
            continue

        # Skip if already correctly linked (UPDATE re-saves, idempotency).
        if frappe.db.exists(
            "File",
            {
                "file_url": value,
                "attached_to_doctype": target.doctype,
                "attached_to_name": target.name,
                "attached_to_field": df.fieldname,
            },
        ):
            continue

        # Find the unattached File row uploaded by the SDK earlier in
        # this push. Match by (file_url, all attached_to_* IS NULL or
        # empty). When two child rows share the same file_url (Frappe's
        # content_hash dedup shares the disk blob but creates one File
        # row per upload), each iteration consumes one row at a time —
        # the next iteration's "is null" filter no longer matches the
        # row we just linked.
        unattached = frappe.db.sql(
            """
            SELECT name FROM `tabFile`
            WHERE file_url = %(file_url)s
              AND (attached_to_doctype IS NULL OR attached_to_doctype = '')
              AND (attached_to_name IS NULL OR attached_to_name = '')
              AND (attached_to_field IS NULL OR attached_to_field = '')
            ORDER BY creation ASC
            LIMIT 1
            """,
            {"file_url": value},
        )
        if not unattached:
            continue

        frappe.db.set_value(
            "File",
            unattached[0][0],
            {
                "attached_to_doctype": target.doctype,
                "attached_to_name": target.name,
                "attached_to_field": df.fieldname,
            },
        )
