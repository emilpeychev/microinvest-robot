#!/usr/bin/env python3
"""Unit tests for pattern_store SQLite-backed pattern store."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from test_utils import load_module

ps = load_module("pattern_store_test", "pattern_store.py")


class PatternStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.rules = Path(self.tmp.name)
        self.db = self.rules / "patterns.sqlite"
        ps.init_db(self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def _seed_clients(self):
        (self.rules / "clients.json").write_text(json.dumps([
            {
                "folder": "Client_A",
                "legal_name": "Айс Блинг ЕООД",
                "eik": "206818376",
                "vat_id": "BG206818376",
                "aliases": ["Ice Bling Ltd"],
            }
        ]), encoding="utf-8")
        ps.seed_clients(self.db, self.rules / "clients.json")

    def _seed_classes(self):
        (self.rules / "issuer_classes_seed.json").write_text(json.dumps([
            {
                "slug": "microinvest_bg_v1",
                "display_name": "Microinvest",
                "fingerprint": {
                    "must_contain_any": ["Microinvest Invoice Pro"],
                    "boost_tokens": [["доставчик", 10]],
                },
                "patterns": [
                    {"field": "date", "kind": "regex",
                     "pattern": r"Дата:\s*(\d{2}\.\d{2}\.\d{4})", "priority": 200},
                    {"field": "number", "kind": "regex",
                     "pattern": r"Номер:\s*(\S+)", "priority": 200},
                ],
            }
        ]), encoding="utf-8")
        ps.seed_issuer_classes(self.db, self.rules / "issuer_classes_seed.json")

    def test_init_and_seed_clients(self):
        self._seed_clients()
        c = ps.get_client(self.db, "Client_A")
        self.assertIsNotNone(c)
        self.assertEqual(c["legal_name"], "Айс Блинг ЕООД")
        self.assertEqual(c["eik"], "206818376")
        self.assertIn("Ice Bling Ltd", c["aliases"])

    def test_get_client_unknown_returns_none(self):
        self._seed_clients()
        self.assertIsNone(ps.get_client(self.db, "Client_Z"))

    def test_match_class_and_apply_patterns(self):
        self._seed_classes()
        text = "Microinvest Invoice Pro\nНомер: 0000000001\nДата: 17.03.2026\n"
        cid, score = ps.match_class(self.db, text)
        self.assertIsNotNone(cid)
        self.assertGreater(score, 0)
        out = ps.apply_class_patterns(self.db, cid, text)
        self.assertEqual(out.get("number"), "0000000001")
        self.assertEqual(out.get("date"), "17.03.2026")

    def test_match_class_no_fingerprint(self):
        self._seed_classes()
        text = "Some random text without the marker"
        cid, score = ps.match_class(self.db, text)
        self.assertIsNone(cid)
        self.assertEqual(score, 0)

    def test_verify_buyer_match_and_mismatch(self):
        self._seed_clients()
        text_match = "Получател: Айс Блинг ЕООД\nЕИК: 206818376\n"
        v = ps.verify_buyer(self.db, "Client_A", text_match)
        self.assertTrue(v["match"])
        self.assertEqual(v["mismatch_with"], [])

        # Same identifier but routed to wrong folder
        v2 = ps.verify_buyer(self.db, "Client_B", text_match)
        self.assertFalse(v2["match"])
        self.assertIn("Client_A", v2["mismatch_with"])

    def test_verify_buyer_missing_returns_no_match(self):
        self._seed_clients()
        v = ps.verify_buyer(self.db, "Client_A", "no identifying info here")
        self.assertFalse(v["match"])
        self.assertEqual(v["mismatch_with"], [])

    def test_counterparty_upsert_and_match(self):
        self._seed_clients()
        client = ps.get_client(self.db, "Client_A")
        ps.upsert_counterparty(
            self.db, client["id"], "Шел България ЕАД",
            supplier_vat="BG175232422", suggested_account="601/1",
        )
        cp = ps.match_counterparty(
            self.db, client["id"], supplier_name="Шел България ЕАД"
        )
        self.assertIsNotNone(cp)
        self.assertEqual(cp["suggested_account"], "601/1")
        self.assertEqual(cp["seen_count"], 1)
        # Re-upsert increments seen_count
        ps.upsert_counterparty(self.db, client["id"], "Шел България ЕАД",
                                supplier_vat="BG175232422")
        cp2 = ps.match_counterparty(self.db, client["id"],
                                     supplier_vat="BG175232422")
        self.assertEqual(cp2["seen_count"], 2)

    def test_match_counterparty_unknown_returns_none(self):
        self._seed_clients()
        client = ps.get_client(self.db, "Client_A")
        self.assertIsNone(
            ps.match_counterparty(self.db, client["id"], supplier_name="Nobody")
        )

    def test_learn_from_below_threshold_noop(self):
        text = "microinvest invoice pro\nfoo\n"
        new_id = ps.learn_from(
            self.db, file_name="x.pdf", text=text,
            fields={"Supplier/Customer": "Foo"},
            confidence=0.80, matched_class_id=None,
        )
        self.assertIsNone(new_id)

    def test_learn_from_above_threshold_creates_pending(self):
        text = "microinvest invoice pro " + "longtoken123 " * 5 + "\n" + "longtoken123 trailing"
        new_id = ps.learn_from(
            self.db, file_name="y.pdf", text=text,
            fields={"Supplier/Customer": "Bar"},
            confidence=0.97, matched_class_id=None,
        )
        self.assertIsNotNone(new_id)
        # Re-querying should now find that class
        cid, score = ps.match_class(self.db, text)
        self.assertEqual(cid, new_id)

    def test_learn_from_skipped_when_class_already_matched(self):
        text = "microinvest invoice pro hello world"
        new_id = ps.learn_from(
            self.db, file_name="z.pdf", text=text,
            fields={"Supplier/Customer": "Baz"},
            confidence=0.97, matched_class_id=42,
        )
        self.assertIsNone(new_id)

    def test_bootstrap_creates_db(self):
        with tempfile.TemporaryDirectory() as t:
            r = Path(t)
            db = ps.bootstrap(r)
            self.assertTrue(db.exists())


if __name__ == "__main__":
    unittest.main()
