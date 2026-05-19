"""
VPN Sales Bot — Telethon | Sanaei Panel v3
==========================================
پیش‌نیازها:
    pip install telethon aiohttp aiofiles

تنظیمات در بخش CONFIG را پر کنید.
"""

import asyncio
import random
import json
import logging
import os
import re
import uuid
from datetime import datetime, timedelta
from typing import Optional

import aiohttp
from telethon import TelegramClient, events, Button
from telethon.network.connection.tcpfull import ConnectionTcpFull
from telethon.tl.types import InputMediaPhoto

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
    "CH_ID":"@",
    "CH_NAME":"",


    # ── پنل 3x-ui (Sanaei v3) ──────────────────
    "PANEL_URL": "http://0.0.0.0:2053/",   # بدون / انتهایی
    "PANEL_API_TOKEN": "",
    "PANEL_INBOUND_ID": 1,
    "SUB_LINK":"http://ex.com:80/sub/",
    # ── اطلاعات پرداخت ──────────────────────
    # چند شماره کارت — هر بار یکی رندوم به مشتری نشان داده می‌شود
    "CARD_NUMBERS": [
        {"number": "", "owner": "علی پاکدل"},
        {"number": "", "owner": "علی پاکدل"},
        {"number": "", "owner": "علی پاکدل"},
    ],
    "CRYPTO_WALLET":"",
    "CRYPTO_TYPE": "Ton",


    # ── مسیر ذخیره دیتا ─────────────────────
    "DATA_FILE": "orders.json",
    "SESSION_NAME": "vpn_bot_session",

    # ── وضعیت فروش ───────────────────────────
    # True = باز | False = بسته
    "SHOP_OPEN": True,
    "SHOP_CLOSED_MSG": "🔴 فروشگاه در حال حاضر تعطیل است.\nبه زودی بازمی‌گردیم 🙏",

    # ── روش‌های پرداخت فعال ──────────────────
    # هر کدام را False کنی آن روش مخفی می‌شود
    "PAYMENT_CARD_ENABLED": True,
    "PAYMENT_CRYPTO_ENABLED": True,

    # ── پروکسی SOCKS5 برای اتصال تلگرام ─────
    # None = بدون پروکسی | ("host", port) = فعال
    "SOCKS5_PROXY": (),           # مثال: ("127.0.0.1", 1080)
    "SOCKS5_USER": "",            # اختیاری
    "SOCKS5_PASS": "",            # اختیاری

    # ── آمار روزانه ──────────────────────────
    # آیدی چنل یا یوزرنیم (مثال: -1001234567890 یا "@mychannel")
    "STATS_CHANNEL": None,          # None = غیرفعال
    "STATS_HOUR": 23,               # ساعت ارسال (۰–۲۳)
    "STATS_MINUTE": 59,             # دقیقه ارسال
}

# ─────────────────────────────────────────────
#  کانفیگ‌های قابل فروش
# ─────────────────────────────────────────────
CONFIGS = [
    {
        "id": "basic_30",
        "name": "🟢 الفا — ۳۰ روزه",
        "duration_days": 30,
        "traffic_gb": 1,
        "price_irr": 180_000,
        "price_TON": 0.48,
        "description": "مناسب استفاده معمولی",
    },
    {
        "id": "pro_30",
        "name": "🔵 بتا — ۳۰ روزه",
        "duration_days": 30,
        "traffic_gb": 2,
        "price_irr": 360_000,
        "price_TON": 0.95,
        "description": " مناسب دانلود سبک",
    },
    {
        "id": "ultra_30",
        "name": "🟣 چارلی — ۳۰ روزه",
        "duration_days": 30,
        "traffic_gb": 3,
        "price_irr": 540_000,
        "price_TON": 1.4,
        "description": "مناسب اینستا و تلگرام و دانلود سبک",
    },
    {
        "id": "basic_90",
        "name": "🟡 دلتا — ۱ ماهه",
        "duration_days": 30,
        "traffic_gb": 5,
        "price_irr": 900_000,
        "price_TON": 2.3,
        "description": "مناسب استفاده های سنگین تر",
    },
    {
        "id": "pro_90",
        "name": "🔴 اکو — ۱ ماهه",
        "duration_days": 30,
        "traffic_gb": 10,
        "price_irr": 1650_000,
        "price_TON": 4.6,
        "description": "بهترین ارزش — پرمصرف",
    },
]

# ─────────────────────────────────────────────
#  وضعیت‌های مکالمه
# ─────────────────────────────────────────────
STATE_IDLE = "idle"
STATE_CHOOSE_CONFIG = "choose_config"
STATE_CHOOSE_PAYMENT = "choose_payment"
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
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

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
    def create_order(self, user_id: int, config_id: str, payment_method: str) -> str:
        order_id = str(uuid.uuid4())[:8].upper()
        self._data["orders"][order_id] = {
            "order_id": order_id,
            "user_id": user_id,
            "config_id": config_id,
            "payment_method": payment_method,
            "status": "pending",
            "created_at": datetime.utcnow().isoformat(),
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
        """آمار سفارش‌های تایید شده یک روز مشخص (فرمت: YYYY-MM-DD)."""
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
            cfg = next((c for c in CONFIGS if c["id"] == o.get("config_id", "")), None)
            if not cfg:
                continue
            stats["count"] += 1
            stats["total_gb"] += cfg["traffic_gb"]
            if o.get("payment_method") == "card":
                stats["card_irr"] += cfg["price_irr"]
                stats["total_irr"] += cfg["price_irr"]
            else:
                stats["crypto_TON"] += cfg["price_TON"]
                stats["total_TON"] += cfg["price_TON"]
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
#  کلاینت پنل 3x-ui (Sanaei v3) — REST API
#  احراز هویت: Bearer token (Settings → Security → API Token)
#  مستندات: /panel/api/  |  envelope: {success, msg, obj}
# ─────────────────────────────────────────────
class SanaeiPanel:
    def __init__(self, base_url: str, api_token: str):
        self.base = base_url.rstrip("/")
        self._token = api_token
        # هدرهای پایه — Bearer token CSRF را bypass می‌کند
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
        """
        کلاینت جدید روی inbound مشخص می‌سازد.
        بر اساس مستندات رسمی 3x-ui:
          POST /panel/api/inbounds/addClient
          body: { "id": <inbound_id>, "settings": "<json_string>" }

        لینک کانفیگ را از:
          GET /panel/api/inbounds/getClientLinks/:id/:email
        می‌گیرد — نیازی به ساخت دستی لینک نیست.
        """
        expire_ms = int(
            (datetime.utcnow() + timedelta(days=duration_days)).timestamp() * 1000
        )
        traffic_bytes = traffic_gb * 1024 ** 3
        client_id = str(uuid.uuid4())
        sub_id = str(uuid.uuid4()).replace("-", "")[:16]

        # settings باید JSON string باشد (نه آبجکت تو در تو)
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
        settings_str = json.dumps({"clients": [client_obj]})

        payload = {
            "id": inbound_id,
            "settings": settings_str,
        }

        resp = await self._post("/panel/api/inbounds/addClient", payload)
        if not resp or not resp.get("success"):
            log.error(f"addClient failed: {resp}")
            return None, None

        log.info(f"Client '{email}' created on inbound {inbound_id}")

        # دریافت لینک کانفیگ از API رسمی
        links_resp = await self._get(
            f"/panel/api/inbounds/getClientLinks/{inbound_id}/{email}"
        )
        config_link: str = client_id  # fallback
        if links_resp and links_resp.get("success"):
            links: list = links_resp.get("obj", [])
            if links:
                config_link = "\n".join(links)
        else:
            log.warning("getClientLinks returned empty, falling back to UUID")

        # سابلینک — مسیر استاندارد 3x-ui
        sub_link = f"{CONFIG["SUB_LINK"]}{sub_id}"



        return config_link, sub_link

    async def test_connection(self) -> bool:
        """اتصال به پنل را تست می‌کند."""
        resp = await self._get("/panel/api/inbounds/list")
        return bool(resp and resp.get("success"))


# ─────────────────────────────────────────────
#  توابع کمکی UI
# ─────────────────────────────────────────────
def config_keyboard():
    """کیبورد انتخاب کانفیگ."""
    buttons = []
    for cfg in CONFIGS:
        label = f"{cfg['name']} | {cfg['price_irr']:,} ت"
        buttons.append([Button.inline(label, data=f"cfg:{cfg['id']}")])
    buttons.append([Button.inline("❌ انصراف", data="cancel")])
    return buttons


def admin_order_keyboard(order_id: str):
    return [
        [
            Button.inline("✅ تایید و ارسال کانفیگ", data=f"adm:approve:{order_id}"),
            Button.inline("❌ رد", data=f"adm:reject:{order_id}"),
        ]
    ]


def find_config(config_id: str) -> Optional[dict]:
    return next((c for c in CONFIGS if c["id"] == config_id), None)


def format_irr(amount: int) -> str:
    return f"{amount:,} تومان"


def is_shop_open(db: "DataStore") -> bool:
    """وضعیت فروشگاه — runtime override مقدم بر CONFIG است."""
    override = db.get_setting("shop_open")
    return CONFIG["SHOP_OPEN"] if override is None else override


def is_card_enabled(db: "DataStore") -> bool:
    override = db.get_setting("payment_card")
    return CONFIG["PAYMENT_CARD_ENABLED"] if override is None else override


def is_crypto_enabled(db: "DataStore") -> bool:
    override = db.get_setting("payment_crypto")
    return CONFIG["PAYMENT_CRYPTO_ENABLED"] if override is None else override


def payment_keyboard(db: "DataStore") -> list:
    """کیبورد پرداخت — فقط روش‌های فعال نمایش داده می‌شوند."""
    buttons = []
    if is_card_enabled(db):
        buttons.append([Button.inline("💳 کارت به کارت", data="pay:card")])
    if is_crypto_enabled(db):
        buttons.append([Button.inline("₿ ارز دیجیتال (TON)", data="pay:crypto")])
    buttons.append([Button.inline("❌ انصراف", data="cancel")])
    return buttons


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
    shop_btn = "🔴 بستن فروش" if is_shop_open(db) else "🟢 باز کردن فروش"
    card_btn = "❌ غیرفعال کارت" if is_card_enabled(db) else "✅ فعال کردن کارت"
    crypto_btn = "❌ غیرفعال کریپتو" if is_crypto_enabled(db) else "✅ فعال کردن کریپتو"
    return [
        [Button.inline(shop_btn, data="adm:toggle:shop")],
        [
            Button.inline(card_btn, data="adm:toggle:card"),
            Button.inline(crypto_btn, data="adm:toggle:crypto"),
        ],
        [Button.inline("🔄 بروزرسانی وضعیت", data="adm:status")],
    ]


# ─────────────────────────────────────────────
#  ربات اصلی
# ─────────────────────────────────────────────
async def main():
    # ── بارگذاری config.json از پنل وب (اگه وجود داشت) ──
    if os.path.exists("config.json"):
        with open("config.json", "r", encoding="utf-8") as _f:
            _ext = json.load(_f)
        # کلیدهای اصلی را override می‌کند
        for _k, _v in _ext.items():
            if _k in CONFIG and _k != "settings":
                CONFIG[_k] = _v
        # پلن‌ها را هم override می‌کند
        if _ext.get("CONFIGS"):
            CONFIGS.clear()
            CONFIGS.extend(_ext["CONFIGS"])
        log.info("config.json بارگذاری شد")

    db = DataStore(CONFIG["DATA_FILE"])
    panel = SanaeiPanel(
        CONFIG["PANEL_URL"],
        CONFIG["PANEL_API_TOKEN"],
    )

    # ── ساخت TelegramClient با پروکسی اختیاری ──
    proxy_cfg = CONFIG["SOCKS5_PROXY"]
    if proxy_cfg:
        import socks as _socks  # python-socks or PySocks
        host, port = proxy_cfg
        # فرمت صحیح Telethon: (type, host, port[, rdns, user, pass])
        if CONFIG["SOCKS5_USER"]:
            proxy = (_socks.SOCKS5, host, port, True,
                     CONFIG["SOCKS5_USER"], CONFIG["SOCKS5_PASS"])
        else:
            proxy = (_socks.SOCKS5, host, port)
        client = TelegramClient(
            CONFIG["SESSION_NAME"],
            CONFIG["API_ID"],
            CONFIG["API_HASH"],
            proxy=proxy,
        )
        log.info(f"پروکسی SOCKS5 فعال: {host}:{port}")
    else:
        client = TelegramClient(
            CONFIG["SESSION_NAME"],
            CONFIG["API_ID"],
            CONFIG["API_HASH"],
        )

    await client.start(bot_token=CONFIG["BOT_TOKEN"])  # type: ignore[misc]
    log.info("ربات راه‌اندازی شد ✅")

    # ══════════════════════════════════════════
    #  /start
    # ══════════════════════════════════════════
    @client.on(events.NewMessage(pattern=r"^/start$"))
    async def cmd_start(event):
        user = await event.get_sender()

        # چک وضعیت فروشگاه
        if not is_shop_open(db):
            await event.respond(CONFIG["SHOP_CLOSED_MSG"])
            return

        db.set_state(user.id, {"state": STATE_CHOOSE_CONFIG})
        text = (
            f"👋 سلام {user.first_name} عزیز!\n\n"
            f"به فروشگاه {CONFIG['CH_NAME']} خوش آمدی 🛡️\n"
            "یکی از پلن‌های زیر را انتخاب کن:\n\n"
        )
        for cfg in CONFIGS:
            text += (
                f"**{cfg['name']}**\n"
                f"  • ترافیک: {cfg['traffic_gb']} GB\n"
                f"  • مدت: {cfg['duration_days']} روز\n"
                f"  • قیمت: {format_irr(cfg['price_irr'])} | {cfg['price_TON']} TON\n"
                f"  • {cfg['description']}\n\n"
            )
        await event.respond(text, buttons=config_keyboard(), parse_mode="markdown")

    # ══════════════════════════════════════════
    #  /admin — پنل مدیریت ادمین
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
    #  /orders — ادمین
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
            cfg = find_config(o["config_id"])
            text = (
                f"🔔 سفارش `{o['order_id']}`\n"
                f"کاربر: `{o['user_id']}`\n"
                f"پلن: {cfg['name'] if cfg else o['config_id']}\n"
                f"پرداخت: {o['payment_method']}\n"
                f"تاریخ: {o['created_at'][:16]}\n"
            )
            await event.respond(text, buttons=admin_order_keyboard(o["order_id"]), parse_mode="markdown")

    # ══════════════════════════════════════════
    #  Callback Query — کلیک دکمه‌ها
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

        # ── انتخاب کانفیگ ────────────────────────
        if data.startswith("cfg:"):
            config_id = data.split(":", 1)[1]
            cfg = find_config(config_id)
            if not cfg:
                await event.answer("کانفیگ یافت نشد!", alert=True)
                return

            state = db.get_state(user_id)
            if state.get("state") not in (STATE_CHOOSE_CONFIG, STATE_IDLE):
                await event.answer("لطفاً مکالمه را با /start شروع کن.", alert=True)
                return

            db.set_state(user_id, {"state": STATE_CHOOSE_PAYMENT, "config_id": config_id})
            text = (
                f"✅ پلن انتخابی: **{cfg['name']}**\n\n"
                f"💰 قیمت: {format_irr(cfg['price_irr'])} | {cfg['price_TON']} TON\n\n"
                "روش پرداخت را انتخاب کن:"
            )
            await event.edit(text, buttons=payment_keyboard(db), parse_mode="markdown")
            return

        # ── انتخاب روش پرداخت ────────────────────
        if data.startswith("pay:"):
            method = data.split(":", 1)[1]
            state = db.get_state(user_id)
            if state.get("state") != STATE_CHOOSE_PAYMENT:
                await event.answer("ابتدا پلن را انتخاب کن.", alert=True)
                return

            config_id: str = state.get("config_id") or ""
            if not config_id:
                await event.answer("خطا: پلن یافت نشد. /start را بزن.", alert=True)
                return

            cfg = find_config(config_id)
            if not cfg:
                await event.answer("پلن نامعتبر است.", alert=True)
                return

            order_id = db.create_order(user_id, config_id, method)
            db.set_state(user_id, {
                "state": STATE_WAITING_RECEIPT,
                "config_id": config_id,
                "order_id": order_id,
                "payment_method": method,
            })

            if method == "card":
                _card = random.choice(CONFIG["CARD_NUMBERS"])
                text = (
                    f"💳 **پرداخت کارت به کارت**\n\n"
                    f"مبلغ: **{format_irr(cfg['price_irr'])}**\n"
                    f"شماره کارت: `{_card['number']}`\n"
                    f"به نام: {_card['owner']}\n\n"
                    f"🔢 کد سفارش: `{order_id}`\n\n"
                    "پس از واریز، **عکس یا متن رسید** را اینجا ارسال کن."
                )
            else:
                text = (
                    f"₿ **پرداخت با {CONFIG['CRYPTO_TYPE']}**\n\n"
                    f"مبلغ: **{cfg['price_TON']} TON**\n"
                    f"آدرس ولت: `{CONFIG['CRYPTO_WALLET']}`\n\n"
                    f"🔢 کد سفارش: `{order_id}`\n\n"
                    "پس از واریز، **هش تراکنش (TXID)** را اینجا ارسال کن."
                )

            await event.edit(text, buttons=[[Button.inline("❌ انصراف", data="cancel")]], parse_mode="markdown")
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

            cfg = find_config(order["config_id"])
            if not cfg:
                await event.edit(f"❌ پلن سفارش `{order_id}` در سیستم یافت نشد.")
                return

            await event.edit(f"⏳ در حال ایجاد کانفیگ برای سفارش `{order_id}`...", parse_mode="markdown")

            email = f"user_{order['user_id']}_{order_id}".lower()
            _result = await panel.add_client(
                inbound_id=CONFIG["PANEL_INBOUND_ID"],
                email=email,
                duration_days=cfg["duration_days"],
                traffic_gb=cfg["traffic_gb"],
            )
            config_link, sub_link = _result if _result is not None else (None, None)

            if not config_link:
                db.update_order(order_id, status="panel_error")
                await event.edit(f"❌ خطا در ایجاد کانفیگ روی پنل! سفارش `{order_id}` را دستی بررسی کن.")
                return

            db.update_order(order_id, status="approved", link=config_link, sub_link=sub_link)

            # ارسال به کاربر
            sub_line = f"\n🔄 **سابلینک (برای بروزرسانی خودکار):**\n`{sub_link}`\n" if sub_link else ""
            user_text = (
                f"✅ **سفارش شما تایید شد!**\n\n"
                f"پلن: {cfg['name']}\n"
                f"ترافیک: {cfg['traffic_gb']} GB\n"
                f"مدت اعتبار: {cfg['duration_days']} روز\n\n"
                f"🔗 **لینک کانفیگ:**\n`{config_link}`\n"
                f"{sub_line}\n"
                "این لینک را در نرم‌افزار VPN خود وارد کنید.\n"
                "برای خرید مجدد /start را بزنید.\n"
                f" آدرس کانال: {CONFIG['CH_ID']} \n"
                f"پشتیبانی: {CONFIG['ADMIN_UNAME']}"

            )
            try:
                await client.send_message(order["user_id"], user_text, parse_mode="markdown")
                db.clear_state(order["user_id"])
                await event.edit(f"✅ کانفیگ با موفقیت ایجاد و برای کاربر `{order['user_id']}` ارسال شد.", parse_mode="markdown")
            except Exception as e:
                log.error(f"Failed to send config to user: {e}")
                await event.edit(f"⚠️ کانفیگ ایجاد شد اما ارسال به کاربر ناموفق بود.\n\nلینک:\n`{config_link}`", parse_mode="markdown")

            # اطلاع‌رسانی خرید به چنل آمار
            if CONFIG.get("STATS_CHANNEL"):
                pay_method = "💳 کارت به کارت" if order["payment_method"] == "card" else "₿ ارز دیجیتال"
                price_str = (
                    f"{cfg['price_irr']:,} تومان"
                    if order["payment_method"] == "card"
                    else f"{cfg['price_TON']} TON"
                )
                sale_msg = (
                    f"🛒 **فروش جدید**\n\n"
                    f"📦 پلن: {cfg['name']}\n"
                    f"🌐 ترافیک: {cfg['traffic_gb']} GB\n"
                    f"📅 مدت: {cfg['duration_days']} روز\n"
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

        # fallback
        await event.answer()

    # ══════════════════════════════════════════
    #  دریافت رسید (عکس یا متن)
    # ══════════════════════════════════════════
    @client.on(events.NewMessage())
    async def on_message(event):
        if event.message.via_bot_id:
            return
        if event.message.text and event.message.text.startswith("/"):
            return

        user_id = event.sender_id
        state = db.get_state(user_id)

        if state.get("state") != STATE_WAITING_RECEIPT:
            return

        order_id: str = state.get("order_id") or ""
        if not order_id:
            await event.respond("سفارشی یافت نشد. با /start مجدداً شروع کن.")
            return
        order = db.get_order(order_id)
        if not order:
            await event.respond("سفارشی یافت نشد. با /start مجدداً شروع کن.")
            return

        # ذخیره رسید
        receipt_text = event.message.text or ""
        has_photo = bool(event.message.photo)
        db.update_order(order_id, receipt=receipt_text, has_photo=has_photo)

        await event.respond(
            f"✅ رسید شما دریافت شد.\n"
            f"کد سفارش: `{order_id}`\n\n"
            "پس از تأیید توسط ادمین، کانفیگ برایت ارسال می‌شود. ⏳",
            parse_mode="markdown",
        )

        # اطلاع به ادمین‌ها
        cfg = find_config(order["config_id"])
        user = await event.get_sender()
        admin_text = (
            f"📦 **رسید جدید دریافت شد**\n\n"
            f"سفارش: `{order_id}`\n"
            f"کاربر: [{user.first_name}](tg://user?id={user_id}) (`{user_id}`)\n"
            f"پلن: {cfg['name'] if cfg else order['config_id']}\n"
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

    # ══════════════════════════════════════════
    #  ارسال آمار روزانه به چنل
    # ══════════════════════════════════════════
    async def send_daily_stats():
        """هر روز در ساعت تعیین شده آمار فروش را به چنل ارسال می‌کند."""
        channel = CONFIG.get("STATS_CHANNEL")
        if not channel:
            return
        target_h = CONFIG["STATS_HOUR"]
        target_m = CONFIG["STATS_MINUTE"]

        while True:
            now = datetime.utcnow()
            # محاسبه زمان تا ارسال بعدی
            next_run = now.replace(hour=target_h, minute=target_m, second=0, microsecond=0)
            if now >= next_run:
                next_run += timedelta(days=1)
            wait_sec = (next_run - now).total_seconds()
            log.info(f"آمار روزانه: {wait_sec/3600:.1f} ساعت دیگر ارسال می‌شود.")
            await asyncio.sleep(wait_sec)

            # آمار روز جاری (UTC)
            today = datetime.utcnow().strftime("%Y-%m-%d")
            stats = db.daily_stats(today)

            if stats["count"] == 0:
                msg = (
                    f"📊 **آمار فروش — {today}**\n\n"
                    "امروز هیچ فروشی ثبت نشد."
                )
            else:
                msg = (
                    f"📊 **آمار فروش — {today}**\n\n"
                    f"🛒 تعداد فروش: **{stats['count']} عدد**\n"
                    f"📦 ترافیک فروخته‌شده: **{stats['total_gb']} GB**\n\n"
                    f"💰 درآمد کل:\n"
                    f"  • کارت به کارت: **{stats['card_irr']:,} تومان**\n"
                    f"  • ارز دیجیتال: **{stats['crypto_TON']:.2f} TON**\n\n"
                    f"💵 جمع تومانی: **{stats['total_irr']:,} تومان**\n"
                    f"💲 جمع TON: **{stats['total_TON']:.2f} TON**"
                )

            try:
                await client.send_message(channel, msg, parse_mode="markdown")
                log.info(f"آمار روزانه {today} به چنل ارسال شد.")
            except Exception as e:
                log.error(f"ارسال آمار روزانه ناموفق: {e}")

    if CONFIG.get("STATS_CHANNEL"):
        asyncio.ensure_future(send_daily_stats())

    log.info("ربات در حال اجراست... (Ctrl+C برای توقف)")
    result = client.run_until_disconnected()
    if result is not None:
        await result  # type: ignore[misc]


if __name__ == "__main__":
    asyncio.run(main())
