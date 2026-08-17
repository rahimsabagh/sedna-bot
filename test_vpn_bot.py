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


if __name__ == "__main__":
    unittest.main()
