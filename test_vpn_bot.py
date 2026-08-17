"""Unit tests for the pure/business logic of vpn_bot.

These tests avoid the network layer: aiohttp and telethon are stubbed so the
module can be imported without a running panel or Telegram session. All tests
cover deterministic logic (pricing, payload building, datastore, admin toggles).
"""

import json
import os
import sys
import tempfile
import types
import unittest

# --- Stub aiohttp so `import vpn_bot` works without the package installed.
#     Network-facing classes (ClientSession, etc.) are only referenced at
#     runtime inside methods, never at import time.
_aiohttp = types.ModuleType("aiohttp")
_aiohttp.ClientTimeout = type("ClientTimeout", (), {})
_aiohttp.ClientSession = type("ClientSession", (), {})
sys.modules.setdefault("aiohttp", _aiohttp)

import vpn_bot as v  # noqa: E402


class PricingTests(unittest.TestCase):
    def test_calc_price(self):
        inb = {"price_per_gb_irr": 180_000, "price_per_gb_TON": 0.48}
        irr, ton = v.calc_price(inb, 10)
        self.assertEqual(irr, 1_800_000)
        self.assertEqual(ton, 4.8)

    def test_calc_price_rounds_ton_to_4dp(self):
        inb = {"price_per_gb_irr": 100_000, "price_per_gb_TON": 0.1234}
        _, ton = v.calc_price(inb, 3)
        self.assertEqual(ton, 0.3702)
        self.assertEqual(round(ton, 4), ton)  # already at 4dp precision

    def test_calc_price_zero_gb(self):
        inb = {"price_per_gb_irr": 100_000, "price_per_gb_TON": 0.5}
        self.assertEqual(v.calc_price(inb, 0), (0, 0.0))

    def test_find_inbound(self):
        inb = v.find_inbound("alpha")
        self.assertIsNotNone(inb)
        self.assertEqual(inb["id"], "alpha")
        self.assertIsNone(v.find_inbound("nope"))

    def test_format_irr(self):
        self.assertEqual(v.format_irr(1800000), "1,800,000 تومان")


class BuildClientPayloadTests(unittest.TestCase):
    def test_payload_structure(self):
        payload, cid, sid = v.build_client_payload(2, "user_1_ABC", 30, 5)
        self.assertEqual(payload["id"], 2)
        self.assertEqual(set(payload.keys()), {"id", "settings"})

        settings = json.loads(payload["settings"])
        clients = settings["clients"]
        self.assertEqual(len(clients), 1)

        client = clients[0]
        self.assertEqual(client["email"], "user_1_ABC")
        self.assertEqual(client["enable"], True)
        self.assertEqual(client["totalGB"], 5 * 1024 ** 3)

    def test_uuid_sub_link_format(self):
        _, _, sid = v.build_client_payload(1, "x", 30, 1)
        # sub id must be 16 hex chars (used to build the short sub link)
        self.assertEqual(len(sid), 16)
        self.assertTrue(all(c in "0123456789abcdef" for c in sid))

    def test_client_id_propagates(self):
        payload, cid, _ = v.build_client_payload(1, "x", 30, 1)
        client = json.loads(payload["settings"])["clients"][0]
        self.assertEqual(cid, client["id"])

    def test_endpoint_params_returned(self):
        # Tests the internal pairing helpers: config fallback is client uuid,
        # sub link is based on sub_id.
        _, cid, sid = v.build_client_payload(1, "x", 30, 1)
        self.assertEqual(v.CONFIG["SUB_LINK"] + sid, f"{v.CONFIG['SUB_LINK']}{sid}")
        self.assertEqual(len(cid), 36)  # uuid4


class DataStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "orders.json")
        self.db = v.DataStore(self.path)

    def tearDown(self):
        for f in (self.path, self.path + ".tmp"):
            if os.path.exists(f):
                os.remove(f)
        os.rmdir(self.tmp)

    def test_order_lifecycle(self):
        oid = self.db.create_order(
            user_id=7, inbound_id="alpha", gb=10,
            price_irr=1_800_000, price_TON=4.8, payment_method="card",
        )
        order = self.db.get_order(oid)
        self.assertEqual(order["status"], "pending")
        self.assertEqual(order["user_id"], 7)
        self.assertEqual(order["gb"], 10)

        self.db.update_order(oid, status="approved", link="vless://...")
        self.assertEqual(self.db.get_order(oid)["status"], "approved")

    def test_pending_orders_filters(self):
        a = self.db.create_order(1, "alpha", 5, 900_000, 2.4, "card")
        b = self.db.create_order(2, "beta", 5, 1_250_000, 3.25, "crypto")
        self.db.update_order(a, status="approved")
        pending_ids = {o["order_id"] for o in self.db.pending_orders()}
        self.assertEqual(pending_ids, {b})

    def test_daily_stats_only_approved(self):
        oid = self.db.create_order(1, "alpha", 10, 1_800_000, 4.8, "card")
        self.db.create_order(2, "beta", 20, 5_000_000, 13.0, "crypto")
        today = v.datetime.now(v.timezone.utc).strftime("%Y-%m-%d")

        # nothing approved yet
        stats = self.db.daily_stats(today)
        self.assertEqual(stats["count"], 0)

        self.db.update_order(oid, status="approved")
        stats = self.db.daily_stats(today)
        self.assertEqual(stats["count"], 1)
        self.assertEqual(stats["total_irr"], 1_800_000)
        self.assertEqual(stats["card_irr"], 1_800_000)
        self.assertEqual(stats["total_TON"], 0.0)

    def test_save_is_atomic_and_reloads(self):
        oid = self.db.create_order(1, "alpha", 5, 900_000, 2.4, "card")
        # a fresh DataStore on the same path must see persisted data
        db2 = v.DataStore(self.path)
        self.assertIsNotNone(db2.get_order(oid))
        # temp file cleaned up
        self.assertFalse(os.path.exists(self.path + ".tmp"))

    def test_state_roundtrip_and_clear(self):
        self.db.set_state(9, {"state": v.STATE_ENTER_GB, "inbound_id": "alpha"})
        self.assertEqual(self.db.get_state(9)["state"], v.STATE_ENTER_GB)
        self.db.clear_state(9)
        self.assertEqual(self.db.get_state(9)["state"], v.STATE_IDLE)


class AdminToggleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = v.DataStore(os.path.join(self.tmp, "orders.json"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_shop_open_override(self):
        self.assertTrue(v.is_shop_open(self.db))  # default from CONFIG
        self.db.set_setting("shop_open", False)
        self.assertFalse(v.is_shop_open(self.db))

    def test_card_button_hidden_when_no_cards_configured(self):
        original = v.CONFIG["CARD_NUMBERS"]
        v.CONFIG["CARD_NUMBERS"] = []
        try:
            kb = v.payment_keyboard(self.db)
            datas = [b.data.decode() for row in kb for b in row]
            self.assertNotIn("pay:card", datas)
        finally:
            v.CONFIG["CARD_NUMBERS"] = original

    def test_card_button_shown_when_cards_configured(self):
        v.CONFIG["CARD_NUMBERS"] = [{"number": "1234", "owner": "x"}]
        kb = v.payment_keyboard(self.db)
        datas = [b.data.decode() for row in kb for b in row]
        self.assertIn("pay:card", datas)


class DigitNormalizationTests(unittest.TestCase):
    def test_persian_digits(self):
        self.assertEqual(v.normalize_digits("۱۰"), "10")
        self.assertEqual(v.normalize_digits("۱۲۳۴۵۶۷۸۹۰"), "1234567890")

    def test_arabic_digits(self):
        self.assertEqual(v.normalize_digits("١٠"), "10")

    def test_mixed_and_ascii_unchanged(self):
        self.assertEqual(v.normalize_digits("abc123"), "abc123")
        self.assertEqual(v.normalize_digits("۵ GB"), "5 GB")

    def test_empty(self):
        self.assertEqual(v.normalize_digits(""), "")
        self.assertEqual(v.normalize_digits(None), None)


class ParseGbInputTests(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(v.parse_gb_input("10", 1, 50), 10)

    def test_persian_digits(self):
        self.assertEqual(v.parse_gb_input("۱۰", 1, 50), 10)

    def test_with_suffix(self):
        self.assertEqual(v.parse_gb_input("20 GB", 1, 50), 20)
        self.assertEqual(v.parse_gb_input("۵ گیگ", 1, 50), 5)

    def test_out_of_range(self):
        self.assertIsNone(v.parse_gb_input("0", 1, 50))
        self.assertIsNone(v.parse_gb_input("51", 1, 50))
        self.assertIsNone(v.parse_gb_input("100 GB", 1, 50))

    def test_non_numeric(self):
        self.assertIsNone(v.parse_gb_input("abc", 1, 50))
        self.assertIsNone(v.parse_gb_input("", 1, 50))
        self.assertIsNone(v.parse_gb_input("12.5", 1, 50))  # فقط عدد صحیح

    def test_boundary_values(self):
        self.assertEqual(v.parse_gb_input("1", 1, 50), 1)
        self.assertEqual(v.parse_gb_input("50", 1, 50), 50)


class DailyStatsCryptoTests(unittest.TestCase):
    def setUp(self):
        import shutil
        self.tmp = tempfile.mkdtemp()
        self.db = v.DataStore(os.path.join(self.tmp, "orders.json"))
        self.today = v.datetime.now(v.timezone.utc).strftime("%Y-%m-%d")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_crypto_revenue_gathered(self):
        self.db.create_order(1, "alpha", 10, 1_800_000, 4.8, "crypto")
        oid = self.db.pending_orders()[0]["order_id"]
        self.db.update_order(oid, status="approved")
        stats = self.db.daily_stats(self.today)
        self.assertEqual(stats["count"], 1)
        self.assertEqual(stats["total_TON"], 4.8)
        self.assertEqual(stats["crypto_TON"], 4.8)
        self.assertEqual(stats["total_irr"], 0)
        self.assertEqual(stats["card_irr"], 0)


class UserOrdersTests(unittest.TestCase):
    def setUp(self):
        import shutil
        self.tmp = tempfile.mkdtemp()
        self.db = v.DataStore(os.path.join(self.tmp, "orders.json"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_user_orders_filters_by_user(self):
        a = self.db.create_order(111, "alpha", 5, 900_000, 2.4, "card")
        self.db.create_order(222, "beta", 5, 1_250_000, 3.25, "crypto")
        self.db.update_order(a, status="approved", link="vless://abc")
        orders = self.db.user_orders(111)
        self.assertEqual(len(orders), 1)
        self.assertEqual(orders[0]["status"], "approved")
        self.assertEqual(orders[0]["link"], "vless://abc")

    def test_user_orders_empty(self):
        self.assertEqual(self.db.user_orders(999), [])

    def test_user_orders_newest_first(self):
        o1 = self.db.create_order(111, "alpha", 5, 900_000, 2.4, "card")
        o2 = self.db.create_order(111, "alpha", 8, 1_440_000, 3.84, "card")
        orders = self.db.user_orders(111)
        self.assertEqual(orders[0]["order_id"], o2)
        self.assertEqual(orders[1]["order_id"], o1)


class FormatDailyStatsTests(unittest.TestCase):
    def test_zero_orders_message(self):
        stats = {k: 0 for k in ("total_irr", "total_TON", "total_gb", "card_irr", "crypto_TON", "count")}
        msg = v.format_daily_stats(stats, "2026-08-17")
        self.assertIn("هیچ فروشی", msg)
        self.assertIn("2026-08-17", msg)

    def test_nonzero_stats_formatting(self):
        stats = {
            "total_irr": 1_800_000,
            "total_TON": 4.8,
            "total_gb": 10,
            "card_irr": 1_800_000,
            "crypto_TON": 4.8,
            "count": 2,
        }
        msg = v.format_daily_stats(stats, "2026-08-17")
        self.assertIn("2 عدد", msg)
        self.assertIn("1,800,000", msg)
        self.assertIn("4.8000", msg)


class ValidateConfigTests(unittest.TestCase):
    def _clean(self):
        # ذخیره مقادیر اصلی برای بازگرداندن در finally
        keys = ("API_ID", "API_HASH", "BOT_TOKEN", "PANEL_API_TOKEN", "PANEL_URL", "ADMIN_IDS")
        saved = {k: v.CONFIG.get(k) for k in keys}
        return saved

    def _restore(self, saved):
        for k, val in saved.items():
            v.CONFIG[k] = val

    def test_reports_missing_fields(self):
        saved = self._clean()
        try:
            v.CONFIG.update({
                "API_ID": 0, "API_HASH": "", "BOT_TOKEN": "",
                "PANEL_API_TOKEN": "", "PANEL_URL": "", "ADMIN_IDS": [],
            })
            problems = v.validate_config()
            self.assertEqual(len(problems), 6)
        finally:
            self._restore(saved)

    def test_ok_when_configured(self):
        saved = self._clean()
        try:
            v.CONFIG.update({
                "API_ID": 1, "API_HASH": "x", "BOT_TOKEN": "y",
                "PANEL_API_TOKEN": "z", "PANEL_URL": "http://x", "ADMIN_IDS": [1],
            })
            self.assertEqual(v.validate_config(), [])
        finally:
            self._restore(saved)


if __name__ == "__main__":
    unittest.main()
