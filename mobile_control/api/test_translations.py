from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests import UnitTestCase
from mobile_control.api import translations

MODULE = "mobile_control.api.translations"


def _row(**kw):
	return frappe._dict(kw)


def _my_call(gl):
	"""The endpoint's own get_list call (frappe.get_all routes through get_list too,
	so the global patch also catches frappe's internal translation loading)."""
	for c in gl.call_args_list:
		if c.kwargs.get("order_by") == "modified asc, name asc":
			return c
	raise AssertionError("translation get_list was not called")


def _rows():
	return [
		_row(
			name="a",
			source_text="Anaemia",
			context=None,
			translated_text="एनीमिया",
			language="hi",
			modified="2026-06-01 10:00:00.000000",
		),
		_row(
			name="b",
			source_text="Anaemia",
			context="disease",
			translated_text="रक्ताल्पता",
			language="hi",
			modified="2026-06-08 16:06:15.452527",
		),
	]


class TestGetTranslations(UnitTestCase):
	def setUp(self) -> None:
		self._orig_user = frappe.session.user
		frappe.set_user("Administrator")
		# Capturable header sink (no real request in unit tests).
		frappe.local.response_headers = {}

	def tearDown(self) -> None:
		frappe.set_user(self._orig_user)

	# ---- guards -------------------------------------------------------------
	# Guest rejection is enforced by @frappe.whitelist at the framework layer,
	# not in the function body, so it is not unit-tested here.
	def test_missing_lang_rejected(self) -> None:
		with self.assertRaises(frappe.ValidationError):
			translations.get_translations(lang="")

	def test_unknown_lang_rejected(self) -> None:
		with patch(f"{MODULE}.get_all_languages", return_value=["en", "hi", "gu"]):
			with self.assertRaises(frappe.ValidationError):
				translations.get_translations(lang="zz")

	# ---- full pull ----------------------------------------------------------
	def test_full_pull_returns_rows_and_watermark(self) -> None:
		with (
			patch(f"{MODULE}.get_all_languages", return_value=["en", "hi"]),
			patch(f"{MODULE}.frappe.get_list", return_value=_rows()) as gl,
		):
			res = translations.get_translations(lang="hi")
		self.assertEqual(res["lang"], "hi")
		self.assertIsNone(res["since"])
		self.assertEqual(res["count"], 2)
		self.assertFalse(res["has_more"])
		self.assertEqual(res["watermark"], "2026-06-08 16:06:15.452527")
		self.assertEqual(res["entries"][1]["context"], "disease")
		self.assertTrue(res["full_pull_token"])
		# full pull → no modified filter
		filters = _my_call(gl).kwargs["filters"]
		self.assertNotIn("modified", filters)

	# ---- delta --------------------------------------------------------------
	def test_delta_filters_by_since(self) -> None:
		with (
			patch(f"{MODULE}.get_all_languages", return_value=["en", "hi"]),
			patch(f"{MODULE}.frappe.get_list", return_value=_rows()[1:]) as gl,
		):
			res = translations.get_translations(lang="hi", since="2026-06-01 10:00:00.000000")
		self.assertEqual(res["since"], "2026-06-01 10:00:00.000000")
		self.assertEqual(res["count"], 1)
		filters = _my_call(gl).kwargs["filters"]
		self.assertEqual(filters["modified"], [">", "2026-06-01 10:00:00.000000"])

	def test_empty_delta_keeps_since_as_watermark(self) -> None:
		with (
			patch(f"{MODULE}.get_all_languages", return_value=["en", "hi"]),
			patch(f"{MODULE}.frappe.get_list", return_value=[]),
		):
			res = translations.get_translations(lang="hi", since="2026-06-08 16:06:15.452527")
		self.assertEqual(res["entries"], [])
		self.assertFalse(res["has_more"])
		self.assertEqual(res["watermark"], "2026-06-08 16:06:15.452527")

	# ---- pagination ---------------------------------------------------------
	def test_has_more_when_page_fills(self) -> None:
		with (
			patch(f"{MODULE}.get_all_languages", return_value=["en", "hi"]),
			patch(f"{MODULE}.frappe.get_list", return_value=_rows()) as gl,
		):
			res = translations.get_translations(lang="hi", limit_page_length=2)
		self.assertTrue(res["has_more"])
		self.assertEqual(_my_call(gl).kwargs["limit_page_length"], 2)

	# ---- parent language ----------------------------------------------------
	def test_parent_language_included_by_default(self) -> None:
		with (
			patch(f"{MODULE}.get_all_languages", return_value=["en", "es", "es-CO"]),
			patch(f"{MODULE}.get_parent_language", return_value="es"),
			patch(f"{MODULE}.frappe.get_list", return_value=[]) as gl,
		):
			translations.get_translations(lang="es-CO")
		self.assertEqual(sorted(_my_call(gl).kwargs["filters"]["language"][1]), ["es", "es-CO"])

	def test_include_parent_false_excludes_parent(self) -> None:
		with (
			patch(f"{MODULE}.get_all_languages", return_value=["en", "es", "es-CO"]),
			patch(f"{MODULE}.get_parent_language", return_value="es"),
			patch(f"{MODULE}.frappe.get_list", return_value=[]) as gl,
		):
			translations.get_translations(lang="es-CO", include_parent=0)
		self.assertEqual(_my_call(gl).kwargs["filters"]["language"], ["in", ["es-CO"]])

	# ---- caching ------------------------------------------------------------
	def test_sets_no_store_header(self) -> None:
		with (
			patch(f"{MODULE}.get_all_languages", return_value=["en", "hi"]),
			patch(f"{MODULE}.frappe.get_list", return_value=[]),
		):
			translations.get_translations(lang="hi")
		self.assertEqual(frappe.local.response_headers.get("Cache-Control"), "no-store")
