"""
VPN Sales Bot — Telethon | Sanaei Panel v3
==========================================
پیش‌نیازها:
    pip install telethon aiohttp aiofiles

تنظیمات در بخش CONFIG و INBOUNDS را پر کنید.
"""

import asyncio
import random
import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import aiohttp
from telethon import TelegramClient, events, Button

# ─────────────────────────────────────────────
#  CONFIG — همه تنظیمات اینجاست
# ─────────────────────────────────────────────
CONFIG = {
    # ── تلگرام ──────────────────────────────
    "API_ID": 123,
    "API_HASH": "",
    "BOT_TOKEN": "",

    # ── ادمین‌ها (آیدی عددی) ──────────────
    "ADMIN_IDS": [],
    "ADMIN_UNAME": "@",
    "CH_ID": "@",
    "CH_NAME": "",

    # ── پنل 3x-ui (Sanaei v3) ──────────────────
    "PANEL_URL": "http://0.0.0.0:2053/",
    "PANEL_API_TOKEN": "",
    "SUB_LINK": "http://ex.com:80/sub/",

    # ── اطلاعات پرداخت ──────────────────────
    "CARD_NUMBERS": [
        {"number": "", "owner": "علی پاکدل"},
    ],
    "CRYPTO_WALLET": "",
    "CRYPTO_TYPE": "Ton",

    # ── مسیر ذخیره دیتا ─────────────────────
    "DATA_FILE": "orders.json",
    "SESSION_NAME": "vpn_bot_session",

    # ── وضعیت فروش ───────────────────────────
    "SHOP_OPEN": True,
    "SHOP_CLOSED_MSG": "🔴 فروشگاه در حال حاضر تعطیل است.\nبه زودی بازمی‌گردیم 🙏",

    # ── روش‌های پرداخت فعال ──────────────────
    "PAYMENT_CARD_ENABLED": True,
    "PAYMENT_CRYPTO_ENABLED": True,

    # ── محدودیت ترافیک (GB) ──────────────────
    "MIN_GB": 1,
    "MAX_GB": 50,

    # ── مدت اعتبار پیش‌فرض (روز) ────────────
    "DEFAULT_DURATION_DAYS": 30,

    # ── پروکسی SOCKS5 ─────────────────────────
    "SOCKS5_PROXY": (),
    "SOCKS5_USER": "",
    "SOCKS5_PASS": "",

    # ── آمار روزانه ──────────────────────────
    "STATS_CHANNEL": None,
    "STATS_HOUR": 23,
    "STATS_MINUTE": 59,
}

# ─────────────────────────────────────────────
#  INBOUNDS — هر inbound یک سرویس مجزاست
#  قیمت per GB را برای هر کدام تنظیم کن
# ─────────────────────────────────────────────
INBOUNDS = [
    {
        "id": "alpha",
        "name": "🟢 سرویس آلفا",
        "inbound_id": 1,
        "price_per_gb_irr": 180_000,   # تومان به ازای هر گیگ
        "price_per_gb_TON": 0.48,      # TON به ازای هر گیگ
        "description": "مناسب استفاده معمولی",
    },
    {
        "id": "beta",
        "name": "🔵 سرویس بتا",
        "inbound_id": 2,
        "price_per_gb_irr": 250_000,
        "price_per_gb_TON": 0.65,
        "description": "سرعت بالاتر — مناسب دانلود",
    },
    {
        "id": "gamma",
        "name": "🟣 سرویس گاما",
        "inbound_id": 3,
        "price_per_gb_irr": 350_000,
        "price_per_gb_TON": 0.90,
        "description": "پریمیوم — کمترین تأخیر",
    },
]

# ─────────────────────────────────────────────
#  وضعیت‌های مکالمه
# ─────────────────────────────────────────────
STATE_IDLE            = "idle"
STATE_CHOOSE_INBOUND  = "choose_inbound"
STATE_ENTER_GB        = "enter_gb"
STATE_CONFIRM_ORDER   = "confirm_order"
STATE_CHOOSE_PAYMENT  = "choose_payment"
STATE_WAITING_RECEIPT = "waiting_receipt"

# ─────────────────────────────────────────────
#  لاگر
# ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("vpn_bot")


# ─────────────────────────────────────────────
#  دیتاستور ساده (JSON روی دیسک)
# ─────────────────────────────────────────────
class DataStore:
    def __init__(self, path: str):
        self.path = path
        self._data = {"orders": {}, "user_states": {}}
        self._load()

    def _load(self):
        if os.path.exists(self.path):
            with open(self.path, "r", encoding="utf-8") as f:
                self._data = json.load(f)

    def _save(self):
        # Write to a temp file then atomically replace, so a crash mid-write
        # never leaves orders.json truncated/corrupt (which would crash the
        # bot on next startup via json.load).
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    # ── وضعیت کاربر ─────────────────────────
    def get_state(self, user_id: int) -> dict:
        return self._data["user_states"].get(str(user_id), {"state": STATE_IDLE})

    def set_state(self, user_id: int, state_data: dict):
        self._data["user_states"][str(user_id)] = state_data
        self._save()

    def clear_state(self, user_id: int):
        self._data["user_states"].pop(str(user_id), None)
        self._save()

    # ── سفارش‌ها ──────────────────────────────
    def create_order(
        self,
        user_id: int,
        inbound_id: str,
        gb: int,
        price_irr: int,
        price_TON: float,
        payment_method: str,
    ) -> str:
        order_id = str(uuid.uuid4())[:8].upper()
        self._data["orders"][order_id] = {
            "order_id": order_id,
            "user_id": user_id,
            "inbound_id": inbound_id,       # id سرویس (نه شماره inbound پنل)
            "gb": gb,
            "price_irr": price_irr,
            "price_TON": price_TON,
            "duration_days": CONFIG["DEFAULT_DURATION_DAYS"],
            "payment_method": payment_method,
            "status": "pending",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self._save()
        return order_id

    def get_order(self, order_id: str) -> Optional[dict]:
        return self._data["orders"].get(order_id)

    def update_order(self, order_id: str, **kwargs):
        if order_id in self._data["orders"]:
            self._data["orders"][order_id].update(kwargs)
            self._save()

    def pending_orders(self) -> list:
        return [o for o in self._data["orders"].values() if o["status"] == "pending"]

    def daily_stats(self, date_str: str) -> dict:
        stats = {
            "total_irr": 0,
            "total_TON": 0.0,
            "total_gb": 0,
            "card_irr": 0,
            "crypto_TON": 0.0,
            "count": 0,
        }
        for o in self._data["orders"].values():
            if o.get("status") != "approved":
                continue
            if not o.get("created_at", "").startswith(date_str):
                continue
            stats["count"] += 1
            stats["total_gb"] += o.get("gb", 0)
            if o.get("payment_method") == "card":
                stats["card_irr"] += o.get("price_irr", 0)
                stats["total_irr"] += o.get("price_irr", 0)
            else:
                stats["crypto_TON"] += o.get("price_TON", 0.0)
                stats["total_TON"] += o.get("price_TON", 0.0)
        return stats

    # ── تنظیمات runtime ──────────────────────
    def get_setting(self, key: str, default=None):
        return self._data.get("settings", {}).get(key, default)

    def set_setting(self, key: str, value):
        if "settings" not in self._data:
            self._data["settings"] = {}
        self._data["settings"][key] = value
        self._save()


# ─────────────────────────────────────────────
#  کلاینت پنل 3x-ui (Sanaei v3)
# ─────────────────────────────────────────────
class SanaeiPanel:
    def __init__(self, base_url: str, api_token: str):
        self.base = base_url.rstrip("/")
        self._headers = {
            "Authorization": f"Bearer {api_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        self._timeout = aiohttp.ClientTimeout(total=20)

    def _session(self) -> aiohttp.ClientSession:
        return aiohttp.ClientSession(headers=self._headers)

    async def _get(self, path: str) -> Optional[dict]:
        url = f"{self.base}{path}"
        try:
            async with self._session() as s:
                async with s.get(url, ssl=False, timeout=self._timeout) as r:
                    return await r.json()
        except Exception as e:
            log.error(f"GET {path} error: {e}")
            return None

    async def _post(self, path: str, payload: dict) -> Optional[dict]:
        url = f"{self.base}{path}"
        try:
            async with self._session() as s:
                async with s.post(url, json=payload, ssl=False, timeout=self._timeout) as r:
                    return await r.json()
        except Exception as e:
            log.error(f"POST {path} error: {e}")
            return None

    async def add_client(
        self,
        inbound_id: int,
        email: str,
        duration_days: int,
        traffic_gb: int,
    ) -> tuple[Optional[str], Optional[str]]:
        payload, client_id, sub_id = build_client_payload(
            inbound_id, email, duration_days, traffic_gb
        )

        resp = await self._post("/panel/api/inbounds/addClient", payload)
        if not resp or not resp.get("success"):
            log.error(f"addClient failed: {resp}")
            return None, None

        log.info(f"Client '{email}' created on inbound {inbound_id}")

        links_resp = await self._get(
            f"/panel/api/inbounds/getClientLinks/{inbound_id}/{email}"
        )
        config_link: str = client_id  # fallback
        if links_resp and links_resp.get("success"):
            links: list = links_resp.get("obj", [])
            if links:
                # ریمارک پنل رو با email کلاینت جایگزین کن
                fixed = []
                for lnk in links:
                    if "#" in lnk:
                        lnk = lnk.rsplit("#", 1)[0] + "#" + email
                    fixed.append(lnk)
                config_link = "\n".join(fixed)
        else:
            log.warning("getClientLinks returned empty, falling back to UUID")

        sub_link = f"{CONFIG['SUB_LINK']}{sub_id}"
        return config_link, sub_link

    async def test_connection(self) -> bool:
        resp = await self._get("/panel/api/inbounds/list")
        return bool(resp and resp.get("success"))


# ─────────────────────────────────────────────
#  توابع کمکی
# ─────────────────────────────────────────────
def find_inbound(inbound_id: str) -> Optional[dict]:
    return next((i for i in INBOUNDS if i["id"] == inbound_id), None)


def build_client_payload(
    inbound_id: int,
    email: str,
    duration_days: int,
    traffic_gb: int,
) -> tuple[dict, str, str]:
    """ساخت payload نهایی برای addClient پنل 3x-ui.

    Returns:
        (payload, client_id, sub_id) — client_id/sub_id برای لینک کانفیگ و سابلینک
        مورد نیاز هستند، اینجا تولید می‌شوند تا خالص و قابل تست باشند.
    """
    expire_ms = int(
        (datetime.now(timezone.utc) + timedelta(days=duration_days)).timestamp() * 1000
    )
    traffic_bytes = traffic_gb * 1024 ** 3
    client_id = str(uuid.uuid4())
    sub_id = str(uuid.uuid4()).replace("-", "")[:16]

    client_obj = {
        "id": client_id,
        "email": email,
        "enable": True,
        "expiryTime": expire_ms,
        "totalGB": traffic_bytes,
        "limitIp": 2,
        "flow": "",
        "tgId": "",
        "subId": sub_id,
    }
    payload = {"id": inbound_id, "settings": json.dumps({"clients": [client_obj]})}
    return payload, client_id, sub_id


def calc_price(inbound: dict, gb: int) -> tuple[int, float]:
    """قیمت کل را بر اساس نرخ per-GB محاسبه می‌کند."""
    irr = inbound["price_per_gb_irr"] * gb
    ton = round(inbound["price_per_gb_TON"] * gb, 4)
    return irr, ton


def format_irr(amount: int) -> str:
    return f"{amount:,} تومان"


def inbound_keyboard() -> list:
    """کیبورد انتخاب سرویس."""
    buttons = []
    for inb in INBOUNDS:
        label = f"{inb['name']} | {format_irr(inb['price_per_gb_irr'])}/GB"
        buttons.append([Button.inline(label, data=f"inb:{inb['id']}")])
    buttons.append([Button.inline("❌ انصراف", data="cancel")])
    return buttons


def confirm_keyboard() -> list:
    return [
        [
            Button.inline("✅ تایید و ادامه", data="confirm:yes"),
            Button.inline("❌ انصراف", data="cancel"),
        ]
    ]


def payment_keyboard(db: "DataStore") -> list:
    buttons = []
    # فقط وقتی شماره کارتی واقعاً تنظیم شده نمایش بده تا کاربر به بن‌بست نخوره
    if is_card_enabled(db) and CONFIG["CARD_NUMBERS"]:
        buttons.append([Button.inline("💳 کارت به کارت", data="pay:card")])
    if is_crypto_enabled(db):
        buttons.append([Button.inline("₿ ارز دیجیتال (TON)", data="pay:crypto")])
    buttons.append([Button.inline("❌ انصراف", data="cancel")])
    return buttons


def admin_order_keyboard(order_id: str) -> list:
    return [
        [
            Button.inline("✅ تایید و ارسال کانفیگ", data=f"adm:approve:{order_id}"),
            Button.inline("❌ رد", data=f"adm:reject:{order_id}"),
        ]
    ]


def is_shop_open(db: "DataStore") -> bool:
    override = db.get_setting("shop_open")
    return CONFIG["SHOP_OPEN"] if override is None else override


def is_card_enabled(db: "DataStore") -> bool:
    override = db.get_setting("payment_card")
    return CONFIG["PAYMENT_CARD_ENABLED"] if override is None else override


def is_crypto_enabled(db: "DataStore") -> bool:
    override = db.get_setting("payment_crypto")
    return CONFIG["PAYMENT_CRYPTO_ENABLED"] if override is None else override


def admin_status_text(db: "DataStore") -> str:
    shop = "🟢 باز" if is_shop_open(db) else "🔴 بسته"
    card = "✅ فعال" if is_card_enabled(db) else "❌ غیرفعال"
    crypto = "✅ فعال" if is_crypto_enabled(db) else "❌ غیرفعال"
    return (
        f"⚙️ **وضعیت فروشگاه**\n\n"
        f"فروش: {shop}\n"
        f"کارت به کارت: {card}\n"
        f"ارز دیجیتال: {crypto}\n"
    )


def admin_panel_keyboard(db: "DataStore") -> list:
    shop_btn   = "🔴 بستن فروش"      if is_shop_open(db)    else "🟢 باز کردن فروش"
    card_btn   = "❌ غیرفعال کارت"   if is_card_enabled(db)  else "✅ فعال کردن کارت"
    crypto_btn = "❌ غیرفعال کریپتو" if is_crypto_enabled(db) else "✅ فعال کردن کریپتو"
    return [
        [Button.inline(shop_btn, data="adm:toggle:shop")],
        [
            Button.inline(card_btn,   data="adm:toggle:card"),
            Button.inline(crypto_btn, data="adm:toggle:crypto"),
        ],
        [Button.inline("🔄 بروزرسانی وضعیت", data="adm:status")],
    ]


# ─────────────────────────────────────────────
#  ربات اصلی
# ─────────────────────────────────────────────
async def main():
    # بارگذاری config.json خارجی (اختیاری)
    if os.path.exists("config.json"):
        with open("config.json", "r", encoding="utf-8") as _f:
            _ext = json.load(_f)
        for _k, _v in _ext.items():
            if _k in CONFIG and _k != "settings":
                CONFIG[_k] = _v
        if _ext.get("INBOUNDS"):
            INBOUNDS.clear()
            INBOUNDS.extend(_ext["INBOUNDS"])
        log.info("config.json بارگذاری شد")

    db = DataStore(CONFIG["DATA_FILE"])
    panel = SanaeiPanel(CONFIG["PANEL_URL"], CONFIG["PANEL_API_TOKEN"])

    # ساخت TelegramClient
    proxy_cfg = CONFIG["SOCKS5_PROXY"]
    if proxy_cfg:
        import socks as _socks
        host, port = proxy_cfg
        if CONFIG["SOCKS5_USER"]:
            proxy = (_socks.SOCKS5, host, port, True,
                     CONFIG["SOCKS5_USER"], CONFIG["SOCKS5_PASS"])
        else:
            proxy = (_socks.SOCKS5, host, port)
        client = TelegramClient(
            CONFIG["SESSION_NAME"], CONFIG["API_ID"], CONFIG["API_HASH"], proxy=proxy
        )
        log.info(f"پروکسی SOCKS5 فعال: {host}:{port}")
    else:
        client = TelegramClient(
            CONFIG["SESSION_NAME"], CONFIG["API_ID"], CONFIG["API_HASH"]
        )

    await client.start(bot_token=CONFIG["BOT_TOKEN"])
    log.info("ربات راه‌اندازی شد ✅")

    # ══════════════════════════════════════════
    #  /start — انتخاب سرویس
    # ══════════════════════════════════════════
    @client.on(events.NewMessage(pattern=r"^/start$"))
    async def cmd_start(event):
        user = await event.get_sender()

        if not is_shop_open(db):
            await event.respond(CONFIG["SHOP_CLOSED_MSG"])
            return

        db.set_state(user.id, {"state": STATE_CHOOSE_INBOUND})

        text = (
            f"👋 سلام {user.first_name} عزیز!\n\n"
            f"به فروشگاه {CONFIG['CH_NAME']} خوش آمدی 🛡️\n\n"
            "یکی از سرویس‌های زیر را انتخاب کن:\n\n"
        )
        for inb in INBOUNDS:
            text += (
                f"**{inb['name']}**\n"
                f"  • نرخ: {format_irr(inb['price_per_gb_irr'])} / هر گیگ\n"
                f"  • {inb['description']}\n\n"
            )
        text += f"📅 مدت اعتبار همه سرویس‌ها: {CONFIG['DEFAULT_DURATION_DAYS']} روز"

        await event.respond(text, buttons=inbound_keyboard(), parse_mode="markdown")

    # ══════════════════════════════════════════
    #  /admin
    # ══════════════════════════════════════════
    @client.on(events.NewMessage(pattern=r"^/admin$"))
    async def cmd_admin(event):
        user = await event.get_sender()
        if user.id not in CONFIG["ADMIN_IDS"]:
            return
        await event.respond(
            admin_status_text(db),
            buttons=admin_panel_keyboard(db),
            parse_mode="markdown",
        )

    # ══════════════════════════════════════════
    #  /orders
    # ══════════════════════════════════════════
    @client.on(events.NewMessage(pattern=r"^/orders$"))
    async def cmd_orders(event):
        user = await event.get_sender()
        if user.id not in CONFIG["ADMIN_IDS"]:
            return
        pending = db.pending_orders()
        if not pending:
            await event.respond("هیچ سفارش در انتظاری وجود ندارد.")
            return
        for o in pending:
            inb = find_inbound(o["inbound_id"])
            text = (
                f"🔔 سفارش `{o['order_id']}`\n"
                f"کاربر: `{o['user_id']}`\n"
                f"سرویس: {inb['name'] if inb else o['inbound_id']}\n"
                f"ترافیک: {o['gb']} GB\n"
                f"مبلغ: {format_irr(o['price_irr'])} | {o['price_TON']} TON\n"
                f"پرداخت: {o['payment_method']}\n"
                f"تاریخ: {o['created_at'][:16]}\n"
            )
            await event.respond(
                text, buttons=admin_order_keyboard(o["order_id"]), parse_mode="markdown"
            )

    # ══════════════════════════════════════════
    #  Callback Query
    # ══════════════════════════════════════════
    @client.on(events.CallbackQuery())
    async def on_callback(event):
        user_id = event.sender_id
        data = event.data.decode()

        # ── انصراف ──────────────────────────────
        if data == "cancel":
            db.clear_state(user_id)
            await event.edit("❌ عملیات لغو شد. برای شروع مجدد /start را بزن.")
            return

        # ── انتخاب سرویس (inbound) ───────────────
        if data.startswith("inb:"):
            inbound_key = data.split(":", 1)[1]
            inb = find_inbound(inbound_key)
            if not inb:
                await event.answer("سرویس یافت نشد!", alert=True)
                return

            state = db.get_state(user_id)
            if state.get("state") not in (STATE_CHOOSE_INBOUND, STATE_IDLE):
                await event.answer("لطفاً مکالمه را با /start شروع کن.", alert=True)
                return

            db.set_state(user_id, {
                "state": STATE_ENTER_GB,
                "inbound_id": inbound_key,
            })

            min_gb = CONFIG["MIN_GB"]
            max_gb = CONFIG["MAX_GB"]
            text = (
                f"✅ سرویس انتخابی: **{inb['name']}**\n"
                f"💰 نرخ: {format_irr(inb['price_per_gb_irr'])} به ازای هر گیگ\n\n"
                f"📦 چند گیگابایت ترافیک می‌خوای؟\n"
                f"(عدد صحیح بین {min_gb} تا {max_gb} ارسال کن)"
            )
            await event.edit(
                text,
                buttons=[[Button.inline("❌ انصراف", data="cancel")]],
                parse_mode="markdown",
            )
            return

        # ── تایید سفارش ─────────────────────────
        if data == "confirm:yes":
            state = db.get_state(user_id)
            if state.get("state") != STATE_CONFIRM_ORDER:
                await event.answer("خطا: وضعیت نامعتبر. /start را بزن.", alert=True)
                return

            db.set_state(user_id, {**state, "state": STATE_CHOOSE_PAYMENT})
            await event.edit(
                "💳 روش پرداخت را انتخاب کن:",
                buttons=payment_keyboard(db),
            )
            return

        # ── انتخاب روش پرداخت ────────────────────
        if data.startswith("pay:"):
            method = data.split(":", 1)[1]
            state = db.get_state(user_id)
            if state.get("state") != STATE_CHOOSE_PAYMENT:
                await event.answer("ابتدا سرویس و ترافیک را انتخاب کن.", alert=True)
                return

            inbound_key = state.get("inbound_id", "")
            gb = state.get("gb", 0)
            inb = find_inbound(inbound_key)
            if not inb or not gb:
                await event.answer("خطا. /start را بزن.", alert=True)
                return

            price_irr, price_TON = calc_price(inb, gb)

            # جلوگیری از کرش (IndexError) وقتی هیچ شماره کارتی تنظیم نشده
            if method == "card" and not CONFIG["CARD_NUMBERS"]:
                await event.answer(
                    "کارت به کارت در حال حاضر در دسترس نیست. روش دیگری را انتخاب کن.",
                    alert=True,
                )
                return

            order_id = db.create_order(
                user_id=user_id,
                inbound_id=inbound_key,
                gb=gb,
                price_irr=price_irr,
                price_TON=price_TON,
                payment_method=method,
            )
            db.set_state(user_id, {
                "state": STATE_WAITING_RECEIPT,
                "inbound_id": inbound_key,
                "gb": gb,
                "order_id": order_id,
                "payment_method": method,
            })

            if method == "card":
                _card = random.choice(CONFIG["CARD_NUMBERS"])
                text = (
                    f"💳 **پرداخت کارت به کارت**\n\n"
                    f"سرویس: {inb['name']}\n"
                    f"ترافیک: {gb} GB | مدت: {CONFIG['DEFAULT_DURATION_DAYS']} روز\n"
                    f"مبلغ: **{format_irr(price_irr)}**\n\n"
                    f"شماره کارت: `{_card['number']}`\n"
                    f"به نام: {_card['owner']}\n\n"
                    f"🔢 کد سفارش: `{order_id}`\n\n"
                    "پس از واریز، **عکس یا متن رسید** را اینجا ارسال کن."
                )
            else:
                text = (
                    f"₿ **پرداخت با {CONFIG['CRYPTO_TYPE']}**\n\n"
                    f"سرویس: {inb['name']}\n"
                    f"ترافیک: {gb} GB | مدت: {CONFIG['DEFAULT_DURATION_DAYS']} روز\n"
                    f"مبلغ: **{price_TON} TON**\n\n"
                    f"آدرس ولت: `{CONFIG['CRYPTO_WALLET']}`\n\n"
                    f"🔢 کد سفارش: `{order_id}`\n\n"
                    "پس از واریز، **هش تراکنش (TXID)** را اینجا ارسال کن."
                )

            await event.edit(
                text,
                buttons=[[Button.inline("❌ انصراف", data="cancel")]],
                parse_mode="markdown",
            )
            return

        # ── ادمین: تایید سفارش ──────────────────
        if data.startswith("adm:approve:"):
            sender = await event.get_sender()
            if sender.id not in CONFIG["ADMIN_IDS"]:
                await event.answer("دسترسی ندارید!", alert=True)
                return

            order_id = data.split(":", 2)[2]
            order = db.get_order(order_id)
            if not order:
                await event.answer("سفارش یافت نشد!", alert=True)
                return
            if order["status"] != "pending":
                await event.answer("این سفارش قبلاً پردازش شده.", alert=True)
                return

            inb = find_inbound(order["inbound_id"])
            if not inb:
                await event.edit(f"❌ سرویس سفارش `{order_id}` در سیستم یافت نشد.")
                return

            await event.edit(
                f"⏳ در حال ایجاد کانفیگ برای سفارش `{order_id}`...",
                parse_mode="markdown",
            )

            email = f"user_{order['user_id']}_{order_id}".lower()
            _result = await panel.add_client(
                inbound_id=inb["inbound_id"],
                email=email,
                duration_days=order["duration_days"],
                traffic_gb=order["gb"],
            )
            config_link, sub_link = _result if _result is not None else (None, None)

            if not config_link:
                db.update_order(order_id, status="panel_error")
                await event.edit(
                    f"❌ خطا در ایجاد کانفیگ روی پنل! سفارش `{order_id}` را دستی بررسی کن."
                )
                return

            db.update_order(order_id, status="approved", link=config_link, sub_link=sub_link)

            sub_line = (
                f"\n🔄 **سابلینک (بروزرسانی خودکار):**\n`{sub_link}`\n"
                if sub_link else ""
            )
            user_text = (
                f"✅ **سفارش شما تایید شد!**\n\n"
                f"سرویس: {inb['name']}\n"
                f"ترافیک: {order['gb']} GB\n"
                f"مدت اعتبار: {order['duration_days']} روز\n\n"
                f"🔗 **لینک کانفیگ:**\n`{config_link}`\n"
                f"{sub_line}\n"
                "این لینک را در نرم‌افزار VPN خود وارد کنید.\n"
                "برای خرید مجدد /start را بزنید.\n"
                f"آدرس کانال: {CONFIG['CH_ID']}\n"
                f"پشتیبانی: {CONFIG['ADMIN_UNAME']}"
            )
            try:
                await client.send_message(order["user_id"], user_text, parse_mode="markdown")
                db.clear_state(order["user_id"])
                await event.edit(
                    f"✅ کانفیگ با موفقیت ایجاد و برای کاربر `{order['user_id']}` ارسال شد.",
                    parse_mode="markdown",
                )
            except Exception as e:
                log.error(f"Failed to send config to user: {e}")
                await event.edit(
                    f"⚠️ کانفیگ ایجاد شد اما ارسال به کاربر ناموفق بود.\n\nلینک:\n`{config_link}`",
                    parse_mode="markdown",
                )

            # اطلاع‌رسانی به چنل آمار
            if CONFIG.get("STATS_CHANNEL"):
                pay_method = "💳 کارت به کارت" if order["payment_method"] == "card" else "₿ ارز دیجیتال"
                price_str = (
                    format_irr(order["price_irr"])
                    if order["payment_method"] == "card"
                    else f"{order['price_TON']} TON"
                )
                sale_msg = (
                    f"🛒 **فروش جدید**\n\n"
                    f"📦 سرویس: {inb['name']}\n"
                    f"🌐 ترافیک: {order['gb']} GB\n"
                    f"📅 مدت: {order['duration_days']} روز\n"
                    f"💰 مبلغ: {price_str}\n"
                    f"💳 روش: {pay_method}\n"
                    f"🔢 سفارش: `{order_id}`"
                )
                try:
                    await client.send_message(CONFIG["STATS_CHANNEL"], sale_msg, parse_mode="markdown")
                except Exception as e:
                    log.error(f"ارسال به چنل آمار ناموفق: {e}")
            return

        # ── ادمین: رد سفارش ─────────────────────
        if data.startswith("adm:reject:"):
            sender = await event.get_sender()
            if sender.id not in CONFIG["ADMIN_IDS"]:
                await event.answer("دسترسی ندارید!", alert=True)
                return

            order_id = data.split(":", 2)[2]
            order = db.get_order(order_id)
            if not order or order["status"] != "pending":
                await event.answer("سفارش یافت‌نشد یا قبلاً پردازش شده.", alert=True)
                return

            db.update_order(order_id, status="rejected")
            db.clear_state(order["user_id"])

            try:
                await client.send_message(
                    order["user_id"],
                    f"❌ **سفارش شما رد شد.**\n\n"
                    f"کد سفارش: `{order_id}`\n\n"
                    "در صورت نیاز با پشتیبانی در ارتباط باشید.\n"
                    "برای تلاش مجدد /start را بزنید.",
                    parse_mode="markdown",
                )
            except Exception as e:
                log.error(f"Failed to notify user of rejection: {e}")

            await event.edit(f"❌ سفارش `{order_id}` رد شد.", parse_mode="markdown")
            return

        # ── ادمین: toggle وضعیت‌ها ───────────────
        if data.startswith("adm:toggle:"):
            sender = await event.get_sender()
            if sender.id not in CONFIG["ADMIN_IDS"]:
                await event.answer("دسترسی ندارید!", alert=True)
                return
            key = data.split(":", 2)[2]
            if key == "shop":
                new_val = not is_shop_open(db)
                db.set_setting("shop_open", new_val)
            elif key == "card":
                new_val = not is_card_enabled(db)
                db.set_setting("payment_card", new_val)
            elif key == "crypto":
                new_val = not is_crypto_enabled(db)
                db.set_setting("payment_crypto", new_val)
            await event.edit(
                admin_status_text(db),
                buttons=admin_panel_keyboard(db),
                parse_mode="markdown",
            )
            return

        # ── ادمین: بروزرسانی وضعیت ───────────────
        if data == "adm:status":
            sender = await event.get_sender()
            if sender.id not in CONFIG["ADMIN_IDS"]:
                await event.answer("دسترسی ندارید!", alert=True)
                return
            await event.edit(
                admin_status_text(db),
                buttons=admin_panel_keyboard(db),
                parse_mode="markdown",
            )
            return

        await event.answer()

    # ══════════════════════════════════════════
    #  دریافت پیام متنی — ورود گیگ یا رسید
    # ══════════════════════════════════════════
    @client.on(events.NewMessage())
    async def on_message(event):
        if event.message.via_bot_id:
            return
        if event.message.text and event.message.text.startswith("/"):
            return

        user_id = event.sender_id
        state = db.get_state(user_id)
        current_state = state.get("state")

        # ── ورود تعداد گیگ ──────────────────────
        if current_state == STATE_ENTER_GB:
            text = (event.message.text or "").strip()
            min_gb = CONFIG["MIN_GB"]
            max_gb = CONFIG["MAX_GB"]

            if not text.isdigit():
                await event.respond(
                    f"⚠️ لطفاً یک عدد صحیح بین {min_gb} تا {max_gb} وارد کن."
                )
                return

            gb = int(text)
            if gb < min_gb or gb > max_gb:
                await event.respond(
                    f"⚠️ مقدار باید بین {min_gb} و {max_gb} گیگابایت باشد."
                )
                return

            inbound_key = state.get("inbound_id", "")
            inb = find_inbound(inbound_key)
            if not inb:
                await event.respond("خطا: سرویس یافت نشد. /start را بزن.")
                return

            price_irr, price_TON = calc_price(inb, gb)

            db.set_state(user_id, {
                "state": STATE_CONFIRM_ORDER,
                "inbound_id": inbound_key,
                "gb": gb,
            })

            confirm_text = (
                f"📋 **خلاصه سفارش**\n\n"
                f"سرویس: {inb['name']}\n"
                f"ترافیک: **{gb} GB**\n"
                f"مدت اعتبار: **{CONFIG['DEFAULT_DURATION_DAYS']} روز**\n\n"
                f"💰 قیمت: **{format_irr(price_irr)}**\n"
                f"💲 معادل: **{price_TON} TON**\n\n"
                "آیا تایید می‌کنی؟"
            )
            await event.respond(
                confirm_text,
                buttons=confirm_keyboard(),
                parse_mode="markdown",
            )
            return

        # ── دریافت رسید پرداخت ──────────────────
        if current_state == STATE_WAITING_RECEIPT:
            order_id: str = state.get("order_id") or ""
            if not order_id:
                await event.respond("سفارشی یافت نشد. با /start مجدداً شروع کن.")
                return
            order = db.get_order(order_id)
            if not order:
                await event.respond("سفارشی یافت نشد. با /start مجدداً شروع کن.")
                return

            receipt_text = event.message.text or ""
            has_photo = bool(event.message.photo)
            db.update_order(order_id, receipt=receipt_text, has_photo=has_photo)

            await event.respond(
                f"✅ رسید شما دریافت شد.\n"
                f"کد سفارش: `{order_id}`\n\n"
                "پس از تأیید توسط ادمین، کانفیگ برایت ارسال می‌شود. ⏳",
                parse_mode="markdown",
            )

            inb = find_inbound(order["inbound_id"])
            user = await event.get_sender()
            admin_text = (
                f"📦 **رسید جدید دریافت شد**\n\n"
                f"سفارش: `{order_id}`\n"
                f"کاربر: [{user.first_name}](tg://user?id={user_id}) (`{user_id}`)\n"
                f"سرویس: {inb['name'] if inb else order['inbound_id']}\n"
                f"ترافیک: {order['gb']} GB\n"
                f"مبلغ: {format_irr(order['price_irr'])} | {order['price_TON']} TON\n"
                f"روش پرداخت: {order['payment_method']}\n"
            )
            if receipt_text:
                admin_text += f"متن رسید: `{receipt_text}`\n"
            if has_photo:
                admin_text += "📷 عکس رسید ضمیمه شده\n"

            for admin_id in CONFIG["ADMIN_IDS"]:
                try:
                    if has_photo:
                        await client.send_message(admin_id, admin_text, parse_mode="markdown")
                        await client.forward_messages(admin_id, event.message, event.chat_id)
                        await client.send_message(
                            admin_id, f"⬆️ رسید سفارش `{order_id}`",
                            buttons=admin_order_keyboard(order_id), parse_mode="markdown"
                        )
                    else:
                        await client.send_message(
                            admin_id, admin_text,
                            buttons=admin_order_keyboard(order_id), parse_mode="markdown"
                        )
                except Exception as e:
                    log.error(f"Failed to notify admin {admin_id}: {e}")
            return

    # ══════════════════════════════════════════
    #  آمار روزانه
    # ══════════════════════════════════════════
    async def send_daily_stats():
        channel = CONFIG.get("STATS_CHANNEL")
        if not channel:
            return
        target_h = CONFIG["STATS_HOUR"]
        target_m = CONFIG["STATS_MINUTE"]

        while True:
            now = datetime.now(timezone.utc)
            next_run = now.replace(hour=target_h, minute=target_m, second=0, microsecond=0)
            if now >= next_run:
                next_run += timedelta(days=1)
            await asyncio.sleep((next_run - now).total_seconds())

            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            stats = db.daily_stats(today)

            if stats["count"] == 0:
                msg = f"📊 **آمار فروش — {today}**\n\nامروز هیچ فروشی ثبت نشد."
            else:
                msg = (
                    f"📊 **آمار فروش — {today}**\n\n"
                    f"🛒 تعداد فروش: **{stats['count']} عدد**\n"
                    f"📦 ترافیک فروخته‌شده: **{stats['total_gb']} GB**\n\n"
                    f"💰 درآمد کل:\n"
                    f"  • کارت به کارت: **{stats['card_irr']:,} تومان**\n"
                    f"  • ارز دیجیتال: **{stats['crypto_TON']:.4f} TON**\n\n"
                    f"💵 جمع تومانی: **{stats['total_irr']:,} تومان**\n"
                    f"💲 جمع TON: **{stats['total_TON']:.4f} TON**"
                )
            try:
                await client.send_message(channel, msg, parse_mode="markdown")
                log.info(f"آمار روزانه {today} ارسال شد.")
            except Exception as e:
                log.error(f"ارسال آمار روزانه ناموفق: {e}")

    if CONFIG.get("STATS_CHANNEL"):
        asyncio.ensure_future(send_daily_stats())

    log.info("ربات در حال اجراست... (Ctrl+C برای توقف)")
    result = client.run_until_disconnected()
    if result is not None:
        await result


if __name__ == "__main__":
    asyncio.run(main())
