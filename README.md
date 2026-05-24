# 🛡️ VPN Sales Bot

ربات تلگرام برای فروش اتوماتیک VPN با اتصال مستقیم به پنل **3x-ui (Sanaei v3)**.

کاربر سرویس و حجم ترافیک دلخواه را انتخاب می‌کند، قیمت لحظه‌ای محاسبه می‌شود، پس از تأیید رسید توسط ادمین، کانفیگ به‌صورت خودکار ساخته و ارسال می‌شود.

---

## ✨ امکانات

- انتخاب سرویس از چند inbound مجزا با قیمت‌گذاری مستقل
- ورود حجم ترافیک دلخواه توسط کاربر (۱ تا ۵۰ GB)
- محاسبه قیمت لحظه‌ای به تومان و TON
- پشتیبانی از پرداخت کارت به کارت و ارز دیجیتال (TON)
- ارسال خودکار کانفیگ و سابلینک پس از تأیید ادمین
- پنل ادمین برای باز/بستن فروش و مدیریت روش‌های پرداخت
- آمار فروش روزانه در کانال تلگرام
- پشتیبانی از پروکسی SOCKS5
- ذخیره سفارش‌ها در فایل JSON

---

## 📋 پیش‌نیازها

- Python 3.10+
- پنل 3x-ui (Sanaei v3) با API Token فعال
- اکانت تلگرام برای ساخت ربات از [@BotFather](https://t.me/BotFather)
- `API_ID` و `API_HASH` از [my.telegram.org](https://my.telegram.org)

---

## 🚀 نصب

```bash
git clone https://github.com/your-username/vpn-bot.git
cd vpn-bot
pip install telethon aiohttp
```

---

## ⚙️ تنظیمات

تنظیمات اصلی در بالای فایل `vpn_bot.py` در دو بخش `CONFIG` و `INBOUNDS` قرار دارد.

### CONFIG

| کلید | توضیح |
|------|-------|
| `API_ID` / `API_HASH` | از my.telegram.org |
| `BOT_TOKEN` | از @BotFather |
| `ADMIN_IDS` | لیست آیدی عددی ادمین‌ها |
| `PANEL_URL` | آدرس پنل بدون slash انتهایی — مثال: `http://1.2.3.4:2053` |
| `PANEL_API_TOKEN` | از Settings → API Tokens در پنل |
| `SUB_LINK` | آدرس پایه سابلینک — مثال: `http://1.2.3.4:80/sub/` |
| `CARD_NUMBERS` | لیست شماره کارت‌ها برای پرداخت |
| `CRYPTO_WALLET` | آدرس ولت TON |
| `MIN_GB` / `MAX_GB` | محدوده ترافیک قابل انتخاب |
| `DEFAULT_DURATION_DAYS` | مدت اعتبار پیش‌فرض (روز) |
| `SOCKS5_PROXY` | پروکسی اختیاری — مثال: `("127.0.0.1", 2080)` |
| `STATS_CHANNEL` | آیدی کانال برای آمار روزانه — مثال: `@mychannel` |

### INBOUNDS

هر آیتم یک سرویس مجزا با inbound_id و قیمت مستقل است:

```python
INBOUNDS = [
    {
        "id": "alpha",               # شناسه داخلی (یکتا)
        "name": "🟢 سرویس آلفا",    # نام نمایشی در ربات
        "inbound_id": 1,             # شماره inbound در پنل 3x-ui
        "price_per_gb_irr": 180_000, # قیمت هر GB به تومان
        "price_per_gb_TON": 0.48,    # قیمت هر GB به TON
        "description": "مناسب استفاده معمولی",
    },
    # سرویس‌های بیشتر...
]
```

---

## ▶️ اجرا

```bash
python vpn_bot.py
```

برای اجرای دائمی با `systemd`:

```ini
[Unit]
Description=VPN Sales Bot
After=network.target

[Service]
WorkingDirectory=/path/to/vpn-bot
ExecStart=/usr/bin/python3 vpn_bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now vpn-bot
```

---

## 📱 دستورات ربات

| دستور | توضیح |
|-------|-------|
| `/start` | شروع فرایند خرید |
| `/admin` | پنل مدیریت (فقط ادمین) |
| `/orders` | لیست سفارش‌های در انتظار (فقط ادمین) |

---

## 🔄 Flow خرید

```
/start
  ↓
انتخاب سرویس
  ↓
ورود تعداد گیگابایت
  ↓
نمایش قیمت + تأیید
  ↓
انتخاب روش پرداخت
  ↓
ارسال رسید
  ↓
تأیید ادمین → ارسال خودکار کانفیگ + سابلینک
```

---

## 🗂️ ساختار فایل‌ها

```
vpn-bot/
├── vpn_bot.py      # کد اصلی
├── orders.json     # سفارش‌ها (ساخته می‌شود خودکار)
└── README.md
```

---

## ⚠️ نکات مهم

- مقدار `PANEL_URL` نباید slash انتهایی داشته باشه: `http://1.2.3.4:2053` ✅ نه `http://1.2.3.4:2053/` ❌
- اگر پنل subpath دارد (مثلاً `/xui/`), آن را در URL وارد نکنید — فقط `host:port`
- API Token را از بخش **Settings → API Tokens** پنل بگیرید، نه از پسورد ادمین
- `ADMIN_IDS` باید **عدد صحیح** باشد نه string: `[123456789]` ✅ نه `["123456789"]` ❌

---

## 📦 وابستگی‌ها

```
telethon
aiohttp
```

---

## 📄 لایسنس

 AGPL-3.0 license 
