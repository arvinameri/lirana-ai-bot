import os
import json
import asyncio
import httpx
import jdatetime
import re
import logging

from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from sqlalchemy import select, func
from app.db.database import async_session_maker
from app.services.ai_handler import get_ai_response, get_product_by_id
import pandas as pd  # اضافه شده برای تولید اکسل
from app.db.models.user import User, Payment
import inspect


USER_LOCKS: dict[int, asyncio.Lock] = {}


# ─────────── بارگذاری تنظیمات ───────────
load_dotenv()

BOT_TOKEN = os.getenv("BALE_BOT_TOKEN")
BASE_URL = f"https://tapi.bale.ai/bot{BOT_TOKEN}"

# ادمین‌ها
ADMIN_IDS = json.loads(os.getenv("ADMIN_IDS", "[967485572]"))

# ثابت‌ها
FREE_QUESTION_LIMIT = 3

# مسیر تصاویر
BANNER_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app", "assets", "banners")
WELCOME_PREVIEW_PATH = os.path.join(BANNER_DIR, "welcome_preview.jpg")
ONBOARDING_START_PATH = os.path.join(BANNER_DIR, "onboarding_start.jpg")
PROFILE_COMPLETE_PATH = os.path.join(BANNER_DIR, "profile_complete.jpg") 
# ─────────── مسیر تصاویر ───────────
# این دو ثابت جدید را کنار مسیرهای عکس‌ها اضافه/جایگزین کن

DIGIPAY_CLOSED_PATH = os.path.join(
    BANNER_DIR,
    "اعتبار-دیجی_پی-تا-اطلاع-ثانوی-قطع-می_باشد.jpg",
)

SNAPPAY_CLOSED_PATH = os.path.join(
    BANNER_DIR,
    "اعتبار-اسنپ-تا-اطلاع-ثانوی-قطع-می_باشد.jpg",
)


# عکس‌های جدید درخواستی کارفرما
INSTALLMENT_MENU_PATH = os.path.join(BANNER_DIR, "installment_menu.jpg")
SNAPPAY_PATH = os.path.join(BANNER_DIR, "snappay.jpg")
DIGIPAY_PATH = os.path.join(BANNER_DIR, "digipay.jpg")
TOROBPAY_PATH = os.path.join(BANNER_DIR, "torobpay.jpg")
WALLET_VIP_PATH = os.path.join(BANNER_DIR, "wallet_vip.jpg")

# مسیر عکس ارسال پیام همگانی
BROADCAST_LIRANA_PATH = os.path.join(BANNER_DIR, "broadcast_lirana.jpg")

PRODUCTS_IMAGE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app", "assets", "products")

# وضعیت ادمین‌ها
admin_states = {}


# ─────────── تابع استخراج لینک و ساخت دکمه شیشه‌ای ───────────
def extract_links_and_create_inline_kb(text: str):
    url_pattern = r'(https?://[^\s]+)'
    urls = re.findall(url_pattern, text)
    
    clean_text = re.sub(url_pattern, '', text).strip()
    
    reply_markup = None
    if urls:
        inline_keyboard = []
        for url in urls:
            inline_keyboard.append([{"text": "🛒 Open Product", "url": url}])
        reply_markup = {"inline_keyboard": inline_keyboard}
        
    return clean_text, reply_markup


# ─────────── تابع پیدا کردن محصول در پاسخ AI ───────────


# ─────────── تابع استخراج اسم کوچیک ───────────
def extract_first_name(full_name: str) -> str:
    if full_name and full_name.strip():
        return full_name.strip().split()[0]
    return "کاربر"


# ─────────── بررسی ادمین بودن ───────────
def is_admin(bale_id: int) -> bool:
    return bale_id in ADMIN_IDS


# ─────────── متن‌های ثابت ربات ───────────

WELCOME_PREVIEW = """🌸 به لیرانا خوش اومدی!

اولین هوش مصنوعی اختصاصی پوست و مو در ایران 🇮🇷

💎 تحلیل هوشمند پوست
💊 پیشنهاد روتین درمانی اختصاصی
🛍️ معرفی بهترین محصولات متناسب با پوست شما

برای شروع، دکمه /start رو بزن 👇"""

ONBOARDING_START = """🌟 سلام! من لیرانا هستم، دستیار هوشمند مراقبت از پوست و موی تو!

برای اینکه بتونم بهترین مشاوره رو بهت بدم، لازمه یه پروفایل پوستی برات بسازم.

👤 لطفاً نام و نام خانوادگیت رو وارد کن:"""

FINAL_WELCOME_TEXT = """✅ عالیه! پروفایل پوستی شما تکمیل شد!

حالا می‌تونی از امکانات لیرانا استفاده کنی:

💡 مشاوره هوشمند پوست و مو (۳ سوال رایگان هدیه)
🛍️ مشاهده محصولات مناسب پوست شما
💳 خرید اقساطی محصولات

از منوی پایین شروع کن 👇"""

ABOUT_TEXT = """🌸 درباره لیرانا

لیرانا اولین هوش مصنوعی اختصاصی پوست و مو در ایران است.

🔬 تحلیل هوشمند نوع پوست
💊 طراحی روتین درمانی شخصی‌سازی‌شده
🛍️ پیشنهاد محصولات تخصصی

⚠️ این سیستم به عنوان اولین هوش مصنوعی پوست ایران ثبت شده و هرگونه الگوبرداری یا کپی‌برداری از متدولوژی و محتوای آن، تحت پیگرد قانونی قرار خواهد گرفت.

📞 پشتیبانی: 09178639822
🌐 سایت: liranabeauty.com"""


CHARGE_TEXT = """💎 برای فعال‌سازی اشتراک VIP (سوالات نامحدود تا ۴۰ روز):

💰 مبلغ اشتراک: ۴۰۰ هزار تومان

🏦 شماره کارت:
5892 1017 0305 5976
به نام: یسنا ساورعلیا

✅ بعد از واریز، عکس فیش رو همینجا بفرست.
یا «لغو / 🔙 برگشت» رو بزن."""

BROADCAST_TEXT = """🚀 آینده کسب‌وکارهای ایرانی با هوش مصنوعی کلید خورد!
‌
بالاخره پس از ماه‌ها تحقیق و توسعه، از اولین هوش مصنوعی زیبایی در ایران در بستر پیام‌رسان بله رونمایی شد. 💎🇮🇷
‌
پروژه لیرانا (Lirana)، نمونه‌ای موفق از پیوند «وب‌سایت» و «بات‌های فوق‌هوشمند» است که استانداردهای جدیدی را در تجربه کاربری (UX) خلق کرده است. 🧩✨
‌
🔹 چه چیزی لیرانا را متمایز می‌کند؟
✅ تحلیل هوشمند نیازهای زیبایی
✅ مدیریت زمان و نوبت‌دهی خودکار بدون دخالت انسانی
✅ تعامل مستقیم و زنده با مشتری در پیام‌رسان بله
✅ هماهنگی کامل با پلتفرم سایت‌ساز
‌
اگر به دنبال این هستید که ببینید چطور هوش مصنوعی می‌تواند یک بیزینس سنتی را به یک غول تکنولوژی تبدیل کند، حتماً ربات لیرانا را تست کنید. 🤖👇
‌
📍 مشاهده و تست ربات در بله:
🆔 @liranabeautybot
‌
🌐 وب‌سایت رسمی:
🔗 liranabeauty.com
‌
لیرانا؛ هوش مصنوعی در خدمت زیبایی شما 🧠💄"""

# ─────────── کیبوردها ───────────

MAIN_KEYBOARD = {
    "keyboard": [
        [{"text": "💡 شروع مشاوره (۳ سوال هدیه)"}],
        [{"text": "💰 کیف پول و شارژ هوش مصنوعی"}, {"text": "⚙️ ویرایش پروفایل پوستی"}],
        [{"text": "🛍️ ورود به سایت و محصولات"}, {"text": "💳 خرید اقساطی محصولات"}],
        [{"text": "ℹ️ درباره لیرانا و پشتیبانی"}],
    ],
    "resize_keyboard": True,
}

ADMIN_KEYBOARD = {
    "keyboard": [
        [{"text": "📊 گزارش‌گیری و خروجی اکسل"}, {"text": "🔍 فیلتر اکسل شماره‌ها"}],
        [{"text": "🧾 بررسی فیش‌های در انتظار"}, {"text": "📢 ارسال پیام تبلیغاتی"}],
        [{"text": "👁️ ورود به منوی کاربری (تست ربات)"}],
    ],
    "resize_keyboard": True,
}

# ─────────── کیبوردها ───────────
# CONFIRM_BROADCAST_KEYBOARD فعلی را با این نسخه جایگزین کن

CONFIRM_BROADCAST_KEYBOARD = {
    "keyboard": [
        [{"text": "✅ تایید و ارسال همگانی"}],
        [{"text": "✏️ ویرایش متن پیام"}],
        [{"text": "لغو"}],
    ],
    "resize_keyboard": True,
}

# این کیبورد جدید را کنار کیبوردها اضافه کن

BACK_ONLY_KEYBOARD = {
    "keyboard": [
        [{"text": "🔙 برگشت"}],
    ],
    "resize_keyboard": True,
}

# کیبورد دریافت شماره تماس کاربر جدید
ASK_PHONE_KEYBOARD = {
    "keyboard": [
        [
            {
                "text": "📱 ارسال شماره موبایل",
                "request_contact": True,
            }
        ],
    ],
    "resize_keyboard": True,
    "one_time_keyboard": True,
}


CANCEL_KEYBOARD = {
    "keyboard": [[{"text": "لغو"}, {"text": "🔙 برگشت"}]],
    "resize_keyboard": True,
}

INSTALLMENT_KEYBOARD = {
    "keyboard": [
        [{"text": "اسنپ‌پی"}, {"text": "دیجی‌پی"}, {"text": "ترب‌پی"}],
        [{"text": "🔙 برگشت"}]
    ],
    "resize_keyboard": True,
}

INSTALLMENT_DETAIL_KEYBOARD = {
    "keyboard": [
        [{"text": "📚 آموزش و نحوه خرید"}],
        [{"text": "🔙 برگشت"}]
    ],
    "resize_keyboard": True,
}

SKIN_TYPE_KEYBOARD = {
    "keyboard": [
        [{"text": "چرب"}, {"text": "خشک"}],
        [{"text": "مختلط"}, {"text": "حساس و خیلی خشک"}],
        [{"text": "نمیدونم 😑🤦🏻‍♀️"}],
    ],
    "resize_keyboard": True,
}

# کیبورد جدید مخصوص ویرایش پوست با دکمه برگشت
SKIN_TYPE_EDIT_KEYBOARD = {
    "keyboard": [
        [{"text": "چرب"}, {"text": "خشک"}],
        [{"text": "مختلط"}, {"text": "حساس و خیلی خشک"}],
        [{"text": "نمیدونم 😑🤦🏻‍♀️"}],
        [{"text": "🔙 برگشت"}],
    ],
    "resize_keyboard": True,
}

MONTH_KEYBOARD = {
    "keyboard": [
        [{"text": "فروردین"}, {"text": "اردیبهشت"}, {"text": "خرداد"}],
        [{"text": "تیر"}, {"text": "مرداد"}, {"text": "شهریور"}],
        [{"text": "مهر"}, {"text": "آبان"}, {"text": "آذر"}],
        [{"text": "دی"}, {"text": "بهمن"}, {"text": "اسفند"}],
    ],
    "resize_keyboard": True,
}

DAY_KEYBOARD = {
    "keyboard": [
        [{"text": str(i)} for i in range(1, 7)],
        [{"text": str(i)} for i in range(7, 13)],
        [{"text": str(i)} for i in range(13, 19)],
        [{"text": str(i)} for i in range(19, 25)],
        [{"text": str(i)} for i in range(25, 32)],
    ],
    "resize_keyboard": True,
}

YEAR_KEYBOARD = {
    "keyboard": [
        [{"text": str(y)} for y in range(1400, 1394, -1)],
        [{"text": str(y)} for y in range(1394, 1388, -1)],
        [{"text": str(y)} for y in range(1388, 1382, -1)],
        [{"text": str(y)} for y in range(1382, 1376, -1)],
        [{"text": str(y)} for y in range(1376, 1370, -1)],
        [{"text": str(y)} for y in range(1370, 1364, -1)],
        [{"text": str(y)} for y in range(1364, 1358, -1)],
        [{"text": str(y)} for y in range(1358, 1352, -1)],
        [{"text": str(y)} for y in range(1352, 1346, -1)],
        [{"text": str(y)} for y in range(1346, 1340, -1)],
        [{"text": str(y)} for y in range(1340, 1334, -1)],
        [{"text": str(y)} for y in range(1334, 1329, -1)],
    ],
    "resize_keyboard": True,
}

VALID_MONTHS = [
    "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
    "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند",
]

MONTH_MAP = {name: str(i).zfill(2) for i, name in enumerate(VALID_MONTHS, 1)}

VALID_SKINS = ["چرب", "خشک", "مختلط", "حساس و خیلی خشک", "نمیدونم 😑🤦🏻‍♀️"]


# ═══════════════════════════════════════════
#  توابع ارسال پیام و عکس و داکیومنت
# ═══════════════════════════════════════════

async def send_message(chat_id, text, reply_markup=None):
    payload = {
        "chat_id": chat_id,
        "text": text,
    }

    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)

    timeout = httpx.Timeout(20.0, connect=10.0)

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(f"{BASE_URL}/sendMessage", json=payload)
            resp.raise_for_status()
            data = resp.json()

            if not data.get("ok", False):
                print(f"❌ Bale sendMessage rejected: {data}")
                return {
                    "ok": False,
                    "error": data,
                }

            return data

    except httpx.TimeoutException as e:
        print(f"❌ timeout در send_message: {e}")
        return {
            "ok": False,
            "error": "timeout",
        }

    except httpx.HTTPError as e:
        print(f"❌ HTTP error در send_message: {e}")
        return {
            "ok": False,
            "error": str(e),
        }

    except Exception as e:
        print(f"❌ خطا در ارسال پیام: {e}")
        return {
            "ok": False,
            "error": str(e),
        }



async def send_photo(chat_id, photo, caption=None, reply_markup=None):
    payload = {
        "chat_id": chat_id,
        "photo": photo,
    }

    if caption:
        payload["caption"] = caption

    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)

    timeout = httpx.Timeout(30.0, connect=10.0)

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(f"{BASE_URL}/sendPhoto", json=payload)
            resp.raise_for_status()
            data = resp.json()

            if not data.get("ok", False):
                print(f"❌ Bale sendPhoto rejected: {data}")
                return {
                    "ok": False,
                    "error": data,
                }

            return data

    except httpx.TimeoutException as e:
        print(f"❌ timeout در send_photo: {e}")
        return {
            "ok": False,
            "error": "timeout",
        }

    except httpx.HTTPError as e:
        print(f"❌ HTTP error در send_photo: {e}")
        return {
            "ok": False,
            "error": str(e),
        }

    except Exception as e:
        print(f"❌ خطا در ارسال عکس: {e}")
        return {
            "ok": False,
            "error": str(e),
        }



async def send_local_photo(chat_id, file_path, caption=None, reply_markup=None):
    if not os.path.exists(file_path):
        print(f"⚠️ فایل تصویر یافت نشد: {file_path}")
        if caption:
            await send_message(chat_id, caption, reply_markup=reply_markup)
        return {
            "ok": False,
            "error": "file_not_found",
        }

    data = {
        "chat_id": str(chat_id),
    }

    if caption:
        data["caption"] = caption

    if reply_markup:
        data["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)

    timeout = httpx.Timeout(60.0, connect=15.0)

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            with open(file_path, "rb") as f:
                files = {
                    "photo": ("photo.jpg", f, "image/jpeg"),
                }
                resp = await client.post(
                    f"{BASE_URL}/sendPhoto",
                    data=data,
                    files=files,
                )

            resp.raise_for_status()
            data_json = resp.json()

            if not data_json.get("ok", False):
                print(f"❌ Bale sendLocalPhoto rejected: {data_json}")
                if caption:
                    await send_message(chat_id, caption, reply_markup=reply_markup)
                return {
                    "ok": False,
                    "error": data_json,
                }

            return data_json

    except httpx.TimeoutException as e:
        print(f"❌ timeout در send_local_photo: {e}")
        if caption:
            await send_message(chat_id, caption, reply_markup=reply_markup)
        return {
            "ok": False,
            "error": "timeout",
        }

    except httpx.HTTPError as e:
        print(f"❌ HTTP error در send_local_photo: {e}")
        if caption:
            await send_message(chat_id, caption, reply_markup=reply_markup)
        return {
            "ok": False,
            "error": str(e),
        }

    except Exception as e:
        print(f"❌ خطا در ارسال عکس محلی: {e}")
        if caption:
            await send_message(chat_id, caption, reply_markup=reply_markup)
        return {
            "ok": False,
            "error": str(e),
        }



async def send_local_document(chat_id, file_path, caption=None, reply_markup=None):
    if not os.path.exists(file_path):
        print(f"⚠️ فایل داکیومنت یافت نشد: {file_path}")
        return {
            "ok": False,
            "error": "file_not_found",
        }

    data = {
        "chat_id": str(chat_id),
    }

    if caption:
        data["caption"] = caption

    if reply_markup:
        data["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)

    timeout = httpx.Timeout(60.0, connect=15.0)

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            with open(file_path, "rb") as f:
                files = {
                    "document": (
                        os.path.basename(file_path),
                        f,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                }
                resp = await client.post(
                    f"{BASE_URL}/sendDocument",
                    data=data,
                    files=files,
                )

            resp.raise_for_status()
            data_json = resp.json()

            if not data_json.get("ok", False):
                print(f"❌ Bale sendDocument rejected: {data_json}")
                return {
                    "ok": False,
                    "error": data_json,
                }

            return data_json

    except httpx.TimeoutException as e:
        print(f"❌ timeout در send_local_document: {e}")
        return {
            "ok": False,
            "error": "timeout",
        }

    except httpx.HTTPError as e:
        print(f"❌ HTTP error در send_local_document: {e}")
        return {
            "ok": False,
            "error": str(e),
        }

    except Exception as e:
        print(f"❌ خطا در ارسال داکیومنت محلی: {e}")
        return {
            "ok": False,
            "error": str(e),
        }



def normalize_phone_number(phone):
    if pd.isna(phone):
        return ""
    p = str(phone).strip().replace("+", "").replace(" ", "")
    if p.endswith(".0"):
        p = p[:-2]
    
    if p.startswith("0098"):
        p = p[2:]
    elif p.startswith("09"):
        p = "98" + p[1:]
    elif p.startswith("9") and len(p) == 10: 
        p = "98" + p
        
    return p


async def download_file(file_id, save_path):
    timeout = httpx.Timeout(60.0, connect=15.0)

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(f"{BASE_URL}/getFile", params={"file_id": file_id})
            resp.raise_for_status()
            data = resp.json()

            if not data.get("ok", False):
                print(f"❌ getFile rejected: {data}")
                return False

            file_path = data["result"]["file_path"]
            download_url = f"https://tapi.bale.ai/file/bot{BOT_TOKEN}/{file_path}"

            file_resp = await client.get(download_url)
            file_resp.raise_for_status()

            with open(save_path, "wb") as f:
                f.write(file_resp.content)

            return True

    except Exception as e:
        print(f"❌ خطا در دانلود فایل: {e}")
        return False



# ═══════════════════════════════════════════
#  ساخت متن کیف پول
# ═══════════════════════════════════════════

def build_wallet_text(user) -> str:
    first_name = extract_first_name(user.full_name)

    if user.is_vip:
        expiry_text = ""
        if user.vip_expiry:
            try:
                tehran_tz = timezone(timedelta(hours=3, minutes=30))
                expiry_tehran = user.vip_expiry.astimezone(tehran_tz)
                j_date = jdatetime.datetime.fromgregorian(datetime=expiry_tehran)
                expiry_text = f"\n📅 اعتبار تا: {j_date.strftime('%Y/%m/%d')}"
            except Exception:
                expiry_text = ""

        return (
            f"💰 کیف پول {first_name}:\n\n"
            f"🔹 وضعیت اشتراک VIP: ✅ فعال{expiry_text}\n\n"
            f"✨ شما اشتراک VIP دارید و سوالاتتون نامحدوده! 💎"
            )
    else:
        remaining = max(0, FREE_QUESTION_LIMIT - (user.ai_question_count or 0))
        return (
            f"💰 کیف پول {first_name}:\n\n"
            f"🔹 وضعیت اشتراک VIP: ❌ غیرفعال\n"
            f"🔹 سوالات رایگان باقی‌مانده: {remaining} از {FREE_QUESTION_LIMIT}\n\n"
            f"{CHARGE_TEXT}"
        )


# ═══════════════════════════════════════════
#  تابع ارسال پیام ترغیبی بعد از اتمام سهمیه
# ═══════════════════════════════════════════
async def send_vip_promo_after_delay(chat_id: int, delay_seconds: int = 900):
    await asyncio.sleep(delay_seconds)
    
    async with async_session_maker() as session:
        result = await session.execute(
            select(User).where(User.bale_id == chat_id)
        )
        user = result.scalar_one_or_none()
        
        if user and not user.is_vip:
            first_name = extract_first_name(user.full_name)
            
            promo_text = (
                f"دلم برات تنگ شد {first_name} جان! 🥺🌸\n\n"
                f"می‌بینم که {FREE_QUESTION_LIMIT} تا سوال رایگانت تموم شده، ولی هنوز کلی حرف در مورد روتین پوستیت موند که بهت نگفتم!\n\n"
                f"میدونستی داشتن یه مشاور تخصصی که همیشه در دسترست باشه، چقدر می‌تونه جلوی خرید محصولات اشتباه و هدر رفتن پولت رو بگیره؟ 💸❌\n\n"
                f"💎 با تهیه اشتراک VIP لیرانا:\n"
                f"✨ هر ساعتی از شبانه‌روز می‌تونی سوالات پوست و مو بپرسی (نامحدود)\n"
                f"✨ روتین و محصولات دقیقا مختص پوست خودت رو دریافت می‌کنی\n"
                f"✨ تا رسیدن به یه پوست شفاف و سالم، من قدم به قدم کنارتم 🥰\n\n"
                f"فقط با ۴۰۰ هزار تومن برای ۴۰ روز کامل، یه متخصص پوست همیشه تو گوشیت داری! 📱🩺\n\n"
                f"👇 برای فعال‌سازی، از منوی پایین روی دکمه «💰 کیف پول و شارژ» کلیک کن تا سریع برگردیم به گپ زدنمون!"
            )
            
            await send_message(chat_id, promo_text, reply_markup=MAIN_KEYBOARD)

def clean_ai_output(text: str) -> str:
    if not text:
        return ""

    text = str(text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    invisible_chars = [
        "\u200b",
        "\u200c",
        "\u200d",
        "\ufeff",
    ]

    for ch in invisible_chars:
        text = text.replace(ch, "")

    markdown_markers = [
        chr(96) * 3,
        "**",
        "__",
        chr(96),
    ]

    for marker in markdown_markers:
        text = text.replace(marker, "")

    lines = []

    for line in text.split("\n"):
        lines.append(line.strip())

    text = "\n".join(lines)

    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")

    return text.strip()


def split_message_for_bale(text: str, limit: int = 3500) -> list[str]:
    if not text:
        return []

    text = text.strip()

    if len(text) <= limit:
        return [text]

    parts = []
    current = ""

    for paragraph in text.split("\n"):
        paragraph = paragraph.strip()

        if not paragraph:
            candidate = current + "\n\n"

            if current and len(candidate) <= limit:
                current = candidate
            else:
                if current.strip():
                    parts.append(current.strip())

                current = ""

            continue

        if current:
            candidate = current + "\n" + paragraph
        else:
            candidate = paragraph

        if len(candidate) <= limit:
            current = candidate
            continue

        if current.strip():
            parts.append(current.strip())

        current = ""

        if len(paragraph) <= limit:
            current = paragraph
            continue

        words = paragraph.split(" ")
        chunk = ""

        for word in words:
            if chunk:
                candidate_word = chunk + " " + word
            else:
                candidate_word = word

            if len(candidate_word) <= limit:
                chunk = candidate_word
            else:
                if chunk.strip():
                    parts.append(chunk.strip())

                chunk = word

        if chunk.strip():
            current = chunk.strip()

    if current.strip():
        parts.append(current.strip())

    return parts


def extract_chat_id_from_update(update: dict) -> int | None:
    """
    Extract chat_id from a Bale update.

    Supports:
    - message
    - edited_message
    - callback_query.message
    - callback_query.from as fallback
    """

    if not isinstance(update, dict):
        return None

    message = update.get("message") or update.get("edited_message")

    if isinstance(message, dict):
        chat = message.get("chat")

        if isinstance(chat, dict):
            chat_id = chat.get("id")

            if chat_id is not None:
                try:
                    return int(chat_id)
                except (TypeError, ValueError):
                    return None

    callback_query = update.get("callback_query")

    if isinstance(callback_query, dict):
        callback_message = callback_query.get("message")

        if isinstance(callback_message, dict):
            chat = callback_message.get("chat")

            if isinstance(chat, dict):
                chat_id = chat.get("id")

                if chat_id is not None:
                    try:
                        return int(chat_id)
                    except (TypeError, ValueError):
                        return None

        callback_from = callback_query.get("from")

        if isinstance(callback_from, dict):
            user_id = callback_from.get("id")

            if user_id is not None:
                try:
                    return int(user_id)
                except (TypeError, ValueError):
                    return None

    return None




# این helperها را قبل از process_update بگذار
# مثلاً بعد از clean_ai_output / split_message_for_bale

# ✅ جایگزین این helperها در main.py کن
# از normalize_ai_result تا send_ai_products را با نسخه‌های زیر جایگزین کن.

def normalize_ai_result(ai_result):
    """
    خروجی ai_handler را به شکل استاندارد تبدیل می‌کند:
    return: (answer_text: str, product_ids: list[int])
    """
    if isinstance(ai_result, dict):
        answer = ai_result.get("answer") or ai_result.get("text") or ""
        raw_product_ids = ai_result.get("product_ids") or []

        product_ids: list[int] = []

        if isinstance(raw_product_ids, list):
            for item in raw_product_ids:
                try:
                    product_id = int(str(item).strip())
                    if product_id > 0:
                        product_ids.append(product_id)
                except (TypeError, ValueError):
                    continue

        # حذف تکراری‌ها با حفظ ترتیب
        seen = set()
        unique_product_ids = []
        for pid in product_ids:
            if pid not in seen:
                seen.add(pid)
                unique_product_ids.append(pid)

        return str(answer).strip(), unique_product_ids

    if isinstance(ai_result, str):
        return ai_result.strip(), []

    return "", []


async def maybe_await(value):
    """
    اگر خروجی awaitable باشد await می‌شود، وگرنه همان مقدار برمی‌گردد.
    """
    if inspect.isawaitable(value):
        return await value
    return value


def format_price_toman(value) -> str:
    try:
        value_int = int(float(str(value).replace(",", "").strip()))
        if value_int <= 0:
            return ""
        return f"{value_int:,} تومان"
    except (TypeError, ValueError):
        return ""


def safe_join_product_image_path(image_filename: str) -> str | None:
    """
    جلوگیری از path traversal و ساخت مسیر امن عکس محصول.
    فقط نام فایل داخل PRODUCTS_IMAGE_DIR مجاز است.
    """
    if not image_filename:
        return None

    image_filename = str(image_filename).strip()

    # اگر آدرس URL باشد، مسیر لوکال نیست
    if image_filename.startswith(("http://", "https://")):
        return None

    safe_name = os.path.basename(image_filename)
    if not safe_name:
        return None

    image_path = os.path.abspath(os.path.join(PRODUCTS_IMAGE_DIR, safe_name))
    products_dir = os.path.abspath(PRODUCTS_IMAGE_DIR)

    if not image_path.startswith(products_dir + os.sep):
        return None

    return image_path


def trim_caption_for_photo(caption: str, limit: int = 950) -> str:
    """
    کپشن عکس در اکثر پیام‌رسان‌ها محدودتر از متن عادی است.
    برای جلوگیری از fail شدن sendPhoto، کپشن محصول را کوتاه می‌کنیم.
    """
    caption = caption.strip()

    if len(caption) <= limit:
        return caption

    return caption[:limit].rstrip() + "..."


def build_product_caption(product: dict, *, for_photo: bool = False) -> str:
    name_fa = product.get("name_fa") or product.get("title") or "محصول پیشنهادی"
    name_en = product.get("name_en") or ""
    skin_type = product.get("skin_type") or ""
    description = (product.get("description") or "").strip()
    in_stock = product.get("in_stock", True)

    discounted = product.get("price_discounted")
    original = product.get("price_original")

    price_line = ""
    discounted_text = format_price_toman(discounted)
    original_text = format_price_toman(original)

    if discounted_text:
        price_line = f"💰 قیمت: {discounted_text}"
        if original_text and str(original).strip() != str(discounted).strip():
            price_line += f"\n🏷 قیمت قبل: {original_text}"
    elif original_text:
        price_line = f"💰 قیمت: {original_text}"

    stock_line = "✅ موجود" if in_stock else "❌ ناموجود"

    lines = [
        "🛍️ محصول پیشنهادی لیرانا",
        "",
        f"✨ {name_fa}",
    ]

    if name_en:
        lines.append(f"🔹 {name_en}")

    if skin_type:
        lines.append(f"🧴 مناسب برای: {skin_type}")

    if price_line:
        lines.append(price_line)

    lines.append(f"📦 وضعیت: {stock_line}")

    if description:
        # برای عکس کوتاه‌تر، برای متن عادی بلندتر
        desc_limit = 280 if for_photo else 500
        short_description = description[:desc_limit].strip()
        if len(description) > desc_limit:
            short_description += "..."

        lines.append("")
        lines.append(short_description)

    caption = "\n".join(lines)

    if for_photo:
        caption = trim_caption_for_photo(caption)

    return caption


def build_product_inline_keyboard(product: dict):
    product_url = (
        product.get("product_url")
        or product.get("url")
        or product.get("link")
    )

    if not product_url:
        return None

    product_url = str(product_url).strip()

    if not product_url.startswith(("http://", "https://")):
        return None

    return {
        "inline_keyboard": [
            [
                {
                    "text": "🛒 مشاهده و خرید محصول",
                    "url": product_url,
                }
            ]
        ]
    }


async def send_product_card(chat_id: int, product: dict) -> bool:
    """
    محصول را همراه عکس و دکمه خرید ارسال می‌کند.
    اگر عکس نبود یا ارسال عکس شکست خورد، متن + دکمه خرید ارسال می‌شود.
    """
    inline_markup = build_product_inline_keyboard(product)

    image_filename = (
        product.get("image_filename")
        or product.get("image")
        or product.get("photo")
    )

    image_path = safe_join_product_image_path(image_filename) if image_filename else None

    # 1) تلاش برای ارسال عکس محصول
    if image_path and os.path.exists(image_path):
        photo_caption = build_product_caption(product, for_photo=True)

        result = await send_local_photo(
            chat_id,
            image_path,
            caption=photo_caption,
            reply_markup=inline_markup,
        )

        if isinstance(result, dict) and result.get("ok"):
            return True

        print(f"⚠️ ارسال عکس محصول ناموفق بود؛ fallback به پیام متنی. path={image_path}")

    elif image_filename:
        print(f"⚠️ عکس محصول پیدا نشد یا مسیر نامعتبر است: {image_filename}")

    # 2) fallback: ارسال کارت به صورت متن
    text_caption = build_product_caption(product, for_photo=False)

    result = await send_message(
        chat_id,
        text_caption,
        reply_markup=inline_markup,
    )

    return isinstance(result, dict) and result.get("ok")


async def send_ai_answer_text(chat_id: int, answer_text: str) -> bool:
    """
    متن جواب AI را تمیز، لینک‌های داخلش را تبدیل به inline button،
    و در چند پیام قابل ارسال برای بله ارسال می‌کند.
    """
    clean_text = clean_ai_output(answer_text)

    if not clean_text:
        return False

    clean_text, inline_markup = extract_links_and_create_inline_kb(clean_text)

    # اگر کل متن فقط لینک بود، حداقل یک متن قابل ارسال داشته باشیم
    if not clean_text and inline_markup:
        clean_text = "برای مشاهده لینک زیر را انتخاب کنید:"

    message_parts = split_message_for_bale(clean_text)

    if not message_parts:
        return False

    for index, part in enumerate(message_parts):
        is_last = index == len(message_parts) - 1

        # دکمه خروج از چت فقط روی آخرین پیام مشاوره بیاید.
        # اگر AI لینک داشت، inline لینک اولویت دارد.
        reply_markup = inline_markup if (is_last and inline_markup) else None
        if is_last and not reply_markup:
            reply_markup = CANCEL_KEYBOARD

        result = await send_message(
            chat_id,
            part,
            reply_markup=reply_markup,
        )

        if not (isinstance(result, dict) and result.get("ok")):
            return False

    return True


async def send_ai_products(chat_id: int, product_ids: list) -> bool:
    """
    product_ids برگشتی از ai_handler را می‌گیرد،
    محصول کامل را از get_product_by_id می‌گیرد،
    و هر محصول را با عکس + لینک خرید می‌فرستد.

    True:
        - product_ids خالی بوده
        - یا حداقل یک محصول معتبر با موفقیت ارسال شده

    False:
        - product_ids وجود داشته ولی هیچ محصولی ارسال نشده
        - یا ارسال یکی از کارت‌های محصول شکست خورده
    """
    if not product_ids:
        return True

    sent_any_product = False

    for product_id in product_ids:
        try:
            product = await maybe_await(get_product_by_id(product_id))
        except Exception as e:
            print(f"❌ خطا در get_product_by_id برای product_id={product_id}: {e}")
            continue

        if not product:
            print(f"⚠️ محصولی برای product_id={product_id} پیدا نشد.")
            continue

        ok = await send_product_card(chat_id, product)

        if not ok:
            print(f"❌ ارسال کارت محصول ناموفق بود. product_id={product_id}")
            return False

        sent_any_product = True
        await asyncio.sleep(0.2)

    return sent_any_product


# این helper را بعد از normalize_phone_number یا کنار helperهای عمومی اضافه کن

def normalize_contact_phone_to_local(phone: str) -> str:
    """
    شماره ارسال‌شده با دکمه contact را به فرمت داخلی 09xxxxxxxxx تبدیل می‌کند.
    ورودی‌های قابل قبول:
    +98912...
    98912...
    0098912...
    0912...
    """
    if not phone:
        return ""

    p = str(phone).strip()
    p = p.replace("+", "").replace(" ", "").replace("-", "")

    if p.startswith("0098"):
        p = p[2:]  # 0098912... -> 98912...

    if p.startswith("98") and len(p) == 12:
        p = "0" + p[2:]  # 98912... -> 0912...

    return p

async def process_update(update):

    # ────── Callback Query ──────
    if "callback_query" in update:
        callback = update["callback_query"]
        cb_data = callback.get("data", "")
        cb_chat_id = callback["from"]["id"]

        if cb_data.startswith("approve_"):
            target_id = int(cb_data.split("_")[1])
            async with async_session_maker() as session:
                result = await session.execute(
                    select(User).where(User.bale_id == target_id)
                )
                target_user = result.scalar_one_or_none()
                if target_user and target_user.pending_receipt_file_id:
                    # ذخیره در تاریخچه پرداخت‌ها
                    new_payment = Payment(
                        bale_id=target_user.bale_id,
                        file_id=target_user.pending_receipt_file_id,
                        status="approved"
                    )
                    session.add(new_payment)
                    
                    target_user.is_vip = True
                    tehran_tz = timezone(timedelta(hours=3, minutes=30))
                    target_user.vip_expiry = datetime.now(tehran_tz) + timedelta(days=40)
                    target_user.pending_receipt_file_id = None  # حذف فیش از لیست انتظار
                    await session.commit()

                    first_name = extract_first_name(target_user.full_name)
                    await send_message(
                        target_id,
                        f"🎉 تبریک {first_name} عزیز!\n✅ اشتراک VIP شما فعال شد.\n📅 مدت: ۴۰ روز\n\nاز منوی پایین استفاده کن 👇",
                        reply_markup=MAIN_KEYBOARD,
                    )
                    await send_message(cb_chat_id, f"✅ اشتراک VIP برای {first_name} (ID: {target_id}) فعال شد و در تاریخچه ثبت شد.")
            return

        if cb_data.startswith("reject_"):
            target_id = int(cb_data.split("_")[1])
            async with async_session_maker() as session:
                result = await session.execute(
                    select(User).where(User.bale_id == target_id)
                )
                target_user = result.scalar_one_or_none()
                if target_user and target_user.pending_receipt_file_id:
                    # ذخیره در تاریخچه پرداخت‌ها
                    new_payment = Payment(
                        bale_id=target_user.bale_id,
                        file_id=target_user.pending_receipt_file_id,
                        status="rejected"
                    )
                    session.add(new_payment)
                    
                    target_user.pending_receipt_file_id = None # حذف فیش از لیست انتظار
                    await session.commit()
                    first_name = extract_first_name(target_user.full_name)
                else:
                    first_name = "کاربر"

            await send_message(
                target_id,
                "❌ متأسفانه فیش پرداختی شما تایید نشد.\nلطفاً مجدد تلاش کنید یا با پشتیبانی تماس بگیرید: 09178639822",
                reply_markup=MAIN_KEYBOARD,
            )
            await send_message(cb_chat_id, f"❌ فیش {first_name} (ID: {target_id}) رد شد و در تاریخچه ثبت شد.")
            return

    # ────── پیام عادی ──────
    message = update.get("message")
    if not message:
        return

    chat_id = message["chat"]["id"]
    text = message.get("text", "").strip()

    # ────── دریافت یا ساخت کاربر ──────
    async with async_session_maker() as session:
        result = await session.execute(
            select(User).where(User.bale_id == chat_id)
        )
        user = result.scalar_one_or_none()

        _is_admin = is_admin(chat_id)

        # ══════════ منطق دکمه برگشت / لغو سراسری ══════════
        if text in ["لغو", "🔙 برگشت"]:
            if admin_states.get(chat_id):
                admin_states.pop(chat_id, None)
                await send_message(chat_id, "❌ عملیات لغو شد.", reply_markup=ADMIN_KEYBOARD)
                return
            if user:
                user.onboarding_step = "completed"
                await session.commit()
                await send_message(chat_id, "🔙 بازگشت به منوی اصلی.", reply_markup=MAIN_KEYBOARD)
            return

        # ══════════ کاربر جدید ══════════
        if user is None:
            user = User(
                bale_id=chat_id,
                username=message.get("from", {}).get("username"),
                onboarding_step="new",
            )
            session.add(user)
            await session.commit()

            if _is_admin:
                user.onboarding_step = "completed"
                await session.commit()
                await send_message(
                    chat_id,
                    "🔑 خوش آمدید ادمین عزیز!\nپنل مدیریت فعال شد.",
                    reply_markup=ADMIN_KEYBOARD,
                )
                return

            await send_local_photo(
                chat_id,
                WELCOME_PREVIEW_PATH,
                caption=WELCOME_PREVIEW,
            )
            return

        # ══════════ دستور /start ══════════
        if text == "/start":
            if _is_admin:
                user.onboarding_step = "completed"
                await session.commit()
                await send_message(
                    chat_id,
                    "🔑 پنل مدیریت لیرانا فعال شد.",
                    reply_markup=ADMIN_KEYBOARD,
                )
                return

            valid_completed_states = ["completed", "chatting", "editing_profile", "editing_concern", "awaiting_receipt", "installment_menu", "installment_detail"]
            if user.onboarding_step in valid_completed_states or user.phone_number:
                user.onboarding_step = "completed"
                await session.commit()
                first_name = extract_first_name(user.full_name)
                await send_message(
                    chat_id,
                    f"سلام دوباره {first_name} عزیز! 🌸\nشما قبلاً ثبت‌نام کرده‌اید. از منوی پایین استفاده کن 👇",
                    reply_markup=MAIN_KEYBOARD,
                )
                return

            user.onboarding_step = "ask_name"
            await session.commit()
            await send_local_photo(
                chat_id,
                ONBOARDING_START_PATH,
                caption=ONBOARDING_START,
            )
            return

        # ══════════ مراحل آنبردینگ ══════════

        if user.onboarding_step == "new":
            await send_message(chat_id, "👋 برای شروع، لطفاً دکمه /start رو بزن.")
            return

        if user.onboarding_step == "ask_name":
            if len(text) < 3 or len(text) > 60:
                await send_message(chat_id, "⚠️ لطفاً نام و نام خانوادگی معتبر وارد کن (بین ۳ تا ۶۰ کاراکتر):")
                return

            user.full_name = text.strip()
            user.onboarding_step = "ask_phone"
            await session.commit()

            first_name = extract_first_name(user.full_name)
            await send_message(chat_id, f"خوش‌وقتم {first_name} عزیز! 🌸\n📱 لطفاً شماره موبایل خودت رو وارد کن :")
            return

        # کل بلاک فعلی if user.onboarding_step == "ask_phone": را با این نسخه جایگزین کن

# کل بلاک فعلی if user.onboarding_step == "ask_phone": را با این نسخه جایگزین کن

# کل بلاک فعلی if user.onboarding_step == "ask_phone": را با این نسخه جایگزین کن

        if user.onboarding_step == "ask_phone":
            contact = message.get("contact")

            if not contact:
                await send_message(
                    chat_id,
                    "⚠️ لطفاً شماره را تایپ نکنید و فقط از دکمه «📱 ارسال شماره موبایل» استفاده کنید:",
                    reply_markup=ASK_PHONE_KEYBOARD,
                )
                return

            # اگر بله user_id کانتکت را ارسال کند، مطمئن می‌شویم شماره متعلق به خود کاربر است
            contact_user_id = contact.get("user_id")
            if contact_user_id is not None:
                try:
                    if int(contact_user_id) != int(chat_id):
                        await send_message(
                            chat_id,
                            "⚠️ لطفاً فقط شماره موبایل خودتان را با دکمه زیر ارسال کنید:",
                            reply_markup=ASK_PHONE_KEYBOARD,
                        )
                        return
                except (TypeError, ValueError):
                    await send_message(
                        chat_id,
                        "⚠️ خطا در اعتبارسنجی شماره. لطفاً دوباره از دکمه زیر استفاده کنید:",
                        reply_markup=ASK_PHONE_KEYBOARD,
                    )
                    return

            phone_number = normalize_contact_phone_to_local(contact.get("phone_number", ""))

            if not re.match(r"^09\d{9}$", phone_number):
                await send_message(
                    chat_id,
                    "⚠️ شماره موبایل دریافت‌شده معتبر نیست. لطفاً با همان شماره‌ای که وارد بله شده‌اید دوباره دکمه زیر را بزنید:",
                    reply_markup=ASK_PHONE_KEYBOARD,
                )
                return

            existing_phone = await session.execute(
                select(User).where(
                    User.phone_number == phone_number,
                    User.bale_id != chat_id,
                )
            )

            if existing_phone.scalar_one_or_none():
                await send_message(
                    chat_id,
                    "⚠️ این شماره موبایل قبلاً توسط شخص دیگری ثبت شده است. امکان تقلب وجود ندارد ⛔️\n"
                    "لطفاً شماره واقعی خود را با دکمه زیر ارسال کنید:",
                    reply_markup=ASK_PHONE_KEYBOARD,
                )
                return

            user.phone_number = phone_number
            user.onboarding_step = "ask_birth_month"
            await session.commit()

            await send_message(
                chat_id,
                "✅ شماره شما ثبت شد.\n"
                "برای تکمیل مشخصات کامل (سن) لطفاً اول ماه تولدت رو انتخاب کن:",
                reply_markup=MONTH_KEYBOARD,
            )
            return




        if user.onboarding_step == "ask_birth_month":
            if text not in VALID_MONTHS:
                await send_message(chat_id, "⚠️ لطفاً ماه تولدت رو از دکمه‌های پایین انتخاب کن 👇", reply_markup=MONTH_KEYBOARD)
                return

            user.birth_date = MONTH_MAP[text]
            user.onboarding_step = "ask_birth_day"
            await session.commit()

            await send_message(chat_id, "📅 حالا روز تولدت رو انتخاب کن:", reply_markup=DAY_KEYBOARD)
            return

        if user.onboarding_step == "ask_birth_day":
            if not text.isdigit() or int(text) < 1 or int(text) > 31:
                await send_message(chat_id, "⚠️ لطفاً روز تولدت رو از دکمه‌های پایین انتخاب کن 👇", reply_markup=DAY_KEYBOARD)
                return

            day = str(int(text)).zfill(2)
            user.birth_date = f"{user.birth_date}/{day}"
            user.onboarding_step = "ask_birth_year"
            await session.commit()

            await send_message(chat_id, "📅 و سال تولدت رو انتخاب کن:", reply_markup=YEAR_KEYBOARD)
            return

        if user.onboarding_step == "ask_birth_year":
            if not text.isdigit() or int(text) < 1330 or int(text) > 1400:
                await send_message(chat_id, "⚠️ لطفاً سال تولدت رو از دکمه‌های پایین انتخاب کن 👇", reply_markup=YEAR_KEYBOARD)
                return

            user.birth_date = f"{text}/{user.birth_date}"
            user.onboarding_step = "ask_skin_type"
            await session.commit()

            await send_message(chat_id, "🧴 نوع پوستت رو انتخاب کن:", reply_markup=SKIN_TYPE_KEYBOARD)
            return

        if user.onboarding_step == "ask_skin_type":
            if text not in VALID_SKINS:
                await send_message(chat_id, "⚠️ لطفاً نوع پوستت رو از دکمه‌های پایین انتخاب کن 👇", reply_markup=SKIN_TYPE_KEYBOARD)
                return

            user.skin_type = text
            user.onboarding_step = "ask_concern"
            await session.commit()

            remove_kb = {"remove_keyboard": True}
            await send_message(chat_id, "✅ نوع پوستت ثبت شد!", reply_markup=remove_kb)
            await asyncio.sleep(0.5)
            await send_message(chat_id, "🤔 حالا دغدغه اصلی پوستت رو بنویس:\n(مثلاً: جوش، لک، چروک، خشکی، منافذ باز و ...)")
            return

        if user.onboarding_step == "ask_concern":
            user.skin_concern = text
            user.onboarding_step = "completed"
            await session.commit()
            await send_local_photo(
                chat_id,
                PROFILE_COMPLETE_PATH,
                caption=f"📝 پرونده دیجیتال شما تکمیل شد!\n\n{FINAL_WELCOME_TEXT}",
                reply_markup=MAIN_KEYBOARD,
            )
            return


        # ══════════ وضعیت‌های خاص ══════════

                # --- حالت چت با AI ---
                # --- حالت چت با AI ---
        if user.onboarding_step == "chatting":
            if not user.is_vip:
                remaining = max(0, FREE_QUESTION_LIMIT - (user.ai_question_count or 0))
                if remaining <= 0:
                    user.onboarding_step = "completed"
                    await session.commit()
                    await send_message(
                        chat_id,
                        "⚠️ سوالات رایگان شما تمام شد!\n💎 برای ادامه، اشتراک VIP تهیه کنید.",
                        reply_markup=MAIN_KEYBOARD,
                    )
                    return

            await send_message(chat_id, "⏳ در حال بررسی و نوشتن نسخه شما... ✍️🌸")

            try:
                ai_result = await asyncio.wait_for(
                    get_ai_response(
                        text,
                        str(user.bale_id),
                        user.skin_type,
                        user.skin_concern,
                        str(user.birth_date),
                    ),
                    timeout=30.0,
                )
            except asyncio.TimeoutError:
                await send_message(
                    chat_id,
                    "⚠️ ارتباط با سرور هوش مصنوعی به دلیل کندی شبکه قطع شد. لطفاً چند دقیقه دیگر دوباره امتحان کنید.",
                    reply_markup=CANCEL_KEYBOARD,
                )
                return
            except Exception as e:
                print(f"❌ خطا در AI: {e}")
                await send_message(
                    chat_id,
                    "⚠️ متأسفانه مشکلی در پردازش سوال شما پیش آمد. لطفاً دوباره تلاش کنید.",
                    reply_markup=CANCEL_KEYBOARD,
                )
                return

            # ai_handler جدید خروجی dict می‌دهد:
            # {"answer": "...", "product_ids": [...]}
            answer_text, product_ids = normalize_ai_result(ai_result)

            if not answer_text:
                await send_message(
                    chat_id,
                    "⚠️ پاسخ معتبری از هوش مصنوعی دریافت نشد. لطفاً دوباره سوال خود را ارسال کنید.",
                    reply_markup=CANCEL_KEYBOARD,
                )
                return

            is_sent_successfully = True

            # 1) اول متن نسخه/مشاوره ارسال شود
            text_sent = await send_ai_answer_text(chat_id, answer_text)
            if not text_sent:
                is_sent_successfully = False

            # 2) بعد محصولات دقیقاً بر اساس product_ids ارسال شوند
            # یعنی دیگر وابسته به پیدا کردن اسم محصول داخل متن نیستیم
            if is_sent_successfully and product_ids:
                header_result = await send_message(
                    chat_id,
                    "🛍️ محصولات پیشنهادی بر اساس مشاوره شما:",
                    reply_markup=CANCEL_KEYBOARD,
                )

                if not (isinstance(header_result, dict) and header_result.get("ok")):
                    is_sent_successfully = False
                else:
                    products_sent = await send_ai_products(chat_id, product_ids)
                    if not products_sent:
                        is_sent_successfully = False

            if is_sent_successfully:
                user.ai_question_count = (user.ai_question_count or 0) + 1
                await session.commit()

                if not user.is_vip:
                    remaining = max(0, FREE_QUESTION_LIMIT - (user.ai_question_count or 0))
                    if remaining > 0:
                        await send_message(
                            chat_id,
                            f"💡 {remaining} سوال رایگان باقی‌مانده.",
                            reply_markup=CANCEL_KEYBOARD,
                        )
                    else:
                        user.onboarding_step = "completed"
                        await session.commit()
                        await send_message(
                            chat_id,
                            "⚠️ سوالات رایگان شما تمام شد!\n💎 برای ادامه، اشتراک VIP تهیه کنید.",
                            reply_markup=MAIN_KEYBOARD,
                        )

                        if user.ai_question_count == FREE_QUESTION_LIMIT:
                            asyncio.create_task(
                                send_vip_promo_after_delay(chat_id, delay_seconds=900)
                            )
            else:
                print("❌ پیام AI یا محصولات به‌صورت کامل برای کاربر ارسال نشد.")
                print(f"AI raw result: {ai_result}")
                print(f"answer_text: {answer_text}")
                print(f"product_ids: {product_ids}")

                await send_message(
                    chat_id,
                    "⚠️ متاسفانه در ارسال پاسخ مشکلی پیش آمد. نگران نباشید، سهمیه شما کسر نشد. لطفاً دوباره سوال خود را مطرح کنید.",
                    reply_markup=CANCEL_KEYBOARD,
                )

            return



        # --- ویرایش پروفایل ---
        if user.onboarding_step == "editing_profile":
            if text in VALID_SKINS:
                user.skin_type = text
                user.onboarding_step = "editing_concern"
                await session.commit()

                await send_message(chat_id, "✅ نوع پوست جدیدت ثبت شد!")
                await asyncio.sleep(0.5)
                await send_message(
                    chat_id,
                    "حالا دغدغه جدیدت رو برام بنویس:\n🤔 مشکل اصلی پوستت الان چیه؟\n(برای انصراف «🔙 برگشت» را بزنید)",
                    reply_markup=CANCEL_KEYBOARD # اضافه شدن دکمه برگشت برای تایپ دغدغه
                )
            else:
                await send_message(
                    chat_id,
                    "⚠️ لطفاً نوع پوستت رو از دکمه‌های پایین انتخاب کن 👇",
                    reply_markup=SKIN_TYPE_EDIT_KEYBOARD,
                )
            return

        if user.onboarding_step == "editing_concern":
            user.skin_concern = text
            user.onboarding_step = "completed"
            await session.commit()
            await send_message(
                chat_id,
                "✅ پروفایل پوستی شما با موفقیت به‌روزرسانی شد! 🌸",
                reply_markup=MAIN_KEYBOARD,
            )
            return

        # --- ارسال فیش پرداخت (نسخه جدید دیتابیس محور) ---
        if user.onboarding_step == "awaiting_receipt":
            if "photo" in message:
                photo_list = message["photo"]
                best_photo = photo_list[-1]
                file_id = best_photo["file_id"]

                user.pending_receipt_file_id = file_id # ثبت در دیتابیس
                user.onboarding_step = "completed"
                await session.commit()

                await send_message(
                    chat_id,
                    "✅ فیش شما دریافت شد و با موفقیت در سیستم ثبت گردید.\nدر حال حاضر در صف بررسی توسط مدیریت است. لطفاً منتظر بمانید...",
                    reply_markup=MAIN_KEYBOARD,
                )

                first_name = extract_first_name(user.full_name)

                for admin_id in ADMIN_IDS:
                    await send_message(
                        admin_id,
                        f"🔔 یک فیش جدید از {first_name} (شماره: {user.phone_number or 'ندارد'}) دریافت شد.\nبرای بررسی از دکمه «🧾 بررسی فیش‌های در انتظار» در پنل مدیریت استفاده کنید."
                    )
                return
            else:
                await send_message(
                    chat_id,
                    "⚠️ لطفاً عکس فیش واریزی رو بفرست یا «🔙 برگشت» رو بزن.",
                    reply_markup=CANCEL_KEYBOARD,
                )
                return
                
        # --- منوی اقساط ---
        # در بخش منوی اقساط، بلاک if user.onboarding_step == "installment_menu": را با این نسخه جایگزین کن

        if user.onboarding_step == "installment_menu":
            if text == "اسنپ‌پی":
                user.onboarding_step = "installment_detail"
                await session.commit()

                await send_local_photo(
                    chat_id,
                    SNAPPAY_CLOSED_PATH,
                    reply_markup=BACK_ONLY_KEYBOARD,
                )

            elif text == "دیجی‌پی":
                user.onboarding_step = "installment_detail"
                await session.commit()

                await send_local_photo(
                    chat_id,
                    DIGIPAY_CLOSED_PATH,
                    reply_markup=BACK_ONLY_KEYBOARD,
                )

            elif text == "ترب‌پی":
                user.onboarding_step = "installment_detail"
                await session.commit()

                await send_local_photo(
                    chat_id,
                    TOROBPAY_PATH,
                    caption="🔵 خرید اقساطی با ترب‌پی:\nسریع‌ترین روش خرید اقساطی با تایید فوری.",
                    reply_markup=INSTALLMENT_DETAIL_KEYBOARD,
                )

            else:
                await send_message(
                    chat_id,
                    "لطفاً یکی از درگاه‌های اقساطی زیر را انتخاب کن:",
                    reply_markup=INSTALLMENT_KEYBOARD,
                )

            return

            
        # بلاک فعلی if user.onboarding_step == "installment_detail": را با این نسخه جایگزین کن

        if user.onboarding_step == "installment_detail":
            if text == "📚 آموزش و نحوه خرید":
                await send_message(
                    chat_id,
                    "برای خرید قسطی کافیه محصولات رو به سبد خرید سایت لیرانا اضافه کنی و در مرحله پرداخت، درگاه قسطی مورد نظرت رو انتخاب کنی 🛍️\n\n"
                    "برای اطلاعات بیشتر می‌تونید با پشتیبانی تماس بگیرید: 09178639822",
                    reply_markup=INSTALLMENT_DETAIL_KEYBOARD,
                )
            else:
                await send_message(
                    chat_id,
                    "برای بازگشت از دکمه زیر استفاده کنید:",
                    reply_markup=BACK_ONLY_KEYBOARD,
                )

            return


        valid_post_onboarding_states = ["completed", "chatting", "editing_profile", "editing_concern", "awaiting_receipt", "installment_menu", "installment_detail"]
        if user.onboarding_step not in valid_post_onboarding_states:
            await send_message(chat_id, "👋 برای شروع، لطفاً دکمه /start رو بزن.")
            return


        # ══════════ منوی ادمین ══════════

        if _is_admin:
            
    

                # در بخش ادمین، کل قسمت ارسال پیام تبلیغاتی را با این نسخه جایگزین کن
            # یعنی از:
            # if text == "📢 ارسال پیام تبلیغاتی":
            # تا انتهای:
            # if admin_states.get(chat_id) == "confirm_broadcast":
            # را حذف و این را قرار بده

            if text == "📢 ارسال پیام تبلیغاتی":
                admin_states[chat_id] = {
                    "state": "confirm_broadcast",
                    "text": BROADCAST_TEXT,
                }

                await send_local_photo(
                    chat_id,
                    BROADCAST_LIRANA_PATH,
                    caption=(
                        f"پیش‌نمایش پیام:\n\n{BROADCAST_TEXT}\n\n"
                        "⚠️ آیا مطمئن هستید که می‌خواهید این پیام برای تمام کاربران غیر VIP ارسال شود؟"
                    ),
                    reply_markup=CONFIRM_BROADCAST_KEYBOARD,
                )
                return


            admin_state = admin_states.get(chat_id)

            if isinstance(admin_state, dict) and admin_state.get("state") == "confirm_broadcast":
                broadcast_text = admin_state.get("text") or BROADCAST_TEXT

                if text == "✅ تایید و ارسال همگانی":
                    await send_message(
                        chat_id,
                        "⏳ در حال ارسال پیام به کاربران... لطفاً تا دریافت پیام پایان کار صبور باشید.",
                        reply_markup=ADMIN_KEYBOARD,
                    )

                    admin_states.pop(chat_id, None)

                    target_users = await session.execute(
                        select(User.bale_id).where(User.is_vip.is_not(True))
                    )
                    users_to_send = target_users.scalars().all()

                    if not users_to_send:
                        await send_message(
                            chat_id,
                            "❌ کاربری برای ارسال یافت نشد.",
                            reply_markup=ADMIN_KEYBOARD,
                        )
                        return

                    success_count = 0
                    failed_count = 0

                    for u_id in users_to_send:
                        res = await send_local_photo(
                            u_id,
                            BROADCAST_LIRANA_PATH,
                            caption=broadcast_text,
                        )

                        if isinstance(res, dict) and res.get("ok"):
                            success_count += 1
                        else:
                            failed_count += 1

                        await asyncio.sleep(0.05)

                    await send_message(
                        chat_id,
                        "✅ ارسال پیام تبلیغاتی به پایان رسید!\n\n"
                        f"📊 ارسال موفق: {success_count}\n"
                        f"⚠️ ارسال ناموفق: {failed_count}\n"
                        f"👥 کل کاربران هدف: {len(users_to_send)}",
                        reply_markup=ADMIN_KEYBOARD,
                    )
                    return

                if text == "✏️ ویرایش متن پیام":
                    admin_states[chat_id] = {
                        "state": "awaiting_broadcast_edit",
                        "text": broadcast_text,
                    }

                    await send_message(
                        chat_id,
                        "✏️ متن جدید پیام تبلیغاتی را ارسال کنید:\n\n"
                        "برای انصراف «لغو» را بزنید.",
                        reply_markup=CANCEL_KEYBOARD,
                    )
                    return

                admin_states.pop(chat_id, None)
                await send_message(
                    chat_id,
                    "❌ ارسال پیام لغو شد.",
                    reply_markup=ADMIN_KEYBOARD,
                )
                return


            # نسخه صحیح کامل این بلاک باید این باشد:

            if isinstance(admin_state, dict) and admin_state.get("state") == "awaiting_broadcast_edit":
                if text in ("لغو", "🔙 برگشت"):
                    admin_states.pop(chat_id, None)
                    await send_message(
                        chat_id,
                        "❌ ویرایش پیام تبلیغاتی لغو شد.",
                        reply_markup=ADMIN_KEYBOARD,
                    )
                    return

                new_broadcast_text = text.strip()

                if len(new_broadcast_text) < 3:
                    await send_message(
                        chat_id,
                        "⚠️ متن پیام خیلی کوتاه است. لطفاً متن کامل‌تری ارسال کنید:",
                        reply_markup=CANCEL_KEYBOARD,
                    )
                    return

                admin_states[chat_id] = {
                    "state": "confirm_broadcast",
                    "text": new_broadcast_text,
                }

                await send_local_photo(
                    chat_id,
                    BROADCAST_LIRANA_PATH,
                    caption=(
                        f"پیش‌نمایش پیام ویرایش‌شده:\n\n{new_broadcast_text}\n\n"
                        "⚠️ آیا این نسخه ارسال شود؟"
                    ),
                    reply_markup=CONFIRM_BROADCAST_KEYBOARD,
                )
                return




            # === بخش بررسی فیش‌ها ===
            if text == "🧾 بررسی فیش‌های در انتظار":
                pending_users_result = await session.execute(
                    select(User).where(User.pending_receipt_file_id.is_not(None))
                )
                pending_users = pending_users_result.scalars().all()

                if not pending_users:
                    await send_message(chat_id, "✅ در حال حاضر هیچ فیش بررسی‌نشده‌ای در سیستم وجود ندارد.", reply_markup=ADMIN_KEYBOARD)
                    return
                
                await send_message(chat_id, f"تعداد {len(pending_users)} فیش در انتظار بررسی در دیتابیس موجود است:")
                
                for pu in pending_users:
                    approve_kb = {
                        "inline_keyboard": [
                            [
                                {"text": "✅ تایید", "callback_data": f"approve_{pu.bale_id}"},
                                {"text": "❌ رد", "callback_data": f"reject_{pu.bale_id}"},
                            ]
                        ]
                    }
                    caption = f"🧾 فیش در انتظار تایید\n👤 {extract_first_name(pu.full_name)} (ID: {pu.bale_id})\n📱 {pu.phone_number or 'ثبت نشده'}"
                    await send_photo(chat_id, pu.pending_receipt_file_id, caption=caption, reply_markup=approve_kb)
                return

            if text == "🔍 فیلتر اکسل شماره‌ها":
                admin_states[chat_id] = "waiting_for_excel"
                await send_message(
                    chat_id,
                    "📁 لطفاً فایل اکسل خروجی از سیستم خود را اینجا بفرستید.\n\n⚠️ دقت کنید که ستون شماره‌ها باید با نام `شماره تلفن` در فایل وجود داشته باشد.\n\n(برای لغو، کلمه «لغو» را بفرستید)",
                    reply_markup=CANCEL_KEYBOARD,
                )
                return

            if admin_states.get(chat_id) == "waiting_for_excel":
                if "document" in message:
                    doc = message["document"]
                    file_id = doc["file_id"]
                    file_name = doc.get("file_name", "uploaded.xlsx").lower()
                    
                    if not (file_name.endswith(".xlsx") or file_name.endswith(".xls")):
                        await send_message(chat_id, "⚠️ لطفاً فقط فایل اکسل (.xlsx یا .xls) ارسال کنید.")
                        return
                    
                    await send_message(chat_id, "⏳ در حال دانلود و تطبیق شماره‌ها با دیتابیس... لطفاً صبور باشید.")
                    
                    temp_input_path = f"temp_input_{chat_id}.xlsx"
                    success = await download_file(file_id, temp_input_path)
                    
                    if success:
                        try:
                            df = pd.read_excel(temp_input_path)
                            
                            if "شماره تلفن" not in df.columns:
                                await send_message(chat_id, "❌ خطای فرمت: ستونی با نام `شماره تلفن` در فایل پیدا نشد! لطفاً اسم ستون را اصلاح کنید.", reply_markup=ADMIN_KEYBOARD)
                                admin_states.pop(chat_id, None)
                                return
                                
                            total_input = len(df)
                            df["شماره_نرمال"] = df["شماره تلفن"].apply(normalize_phone_number)
                            
                            db_users = await session.execute(select(User.phone_number).where(User.phone_number.is_not(None)))
                            db_phones = set(db_users.scalars().all())
                            
                            df_filtered = df[~df["شماره_نرمال"].isin(db_phones)].copy()
                            df_filtered.drop(columns=["شماره_نرمال"], inplace=True)
                            
                            total_output = len(df_filtered)
                            duplicates = total_input - total_output
                            
                            temp_output_path = f"Filtered_Targets_{jdatetime.datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
                            df_filtered.to_excel(temp_output_path, index=False, engine='openpyxl')
                            
                            caption = (
                                f"✅ فیلتر فایل با موفقیت انجام شد!\n\n"
                                f"📊 تعداد کل شماره‌های فایل اصلی: {total_input}\n"
                                f"👥 اعضای ثبت‌نام شده (حذف شدند): {duplicates}\n"
                                f"🎯 شماره‌های جدید جهت ارسال دعوت: {total_output}\n\n"
                                f"📁 فایل خالص و بدون تکراری شما پیوست شد."
                            )
                            
                            await send_local_document(chat_id, temp_output_path, caption=caption, reply_markup=ADMIN_KEYBOARD)
                            admin_states.pop(chat_id, None)
                            
                            if os.path.exists(temp_output_path):
                                os.remove(temp_output_path)
                                
                        except Exception as e:
                            print(f"❌ خطای پردازش اکسل آپلودی: {e}")
                            await send_message(chat_id, "❌ متاسفانه فایل شما دارای فرمت پیچیده یا خرابی است که خوانده نشد.", reply_markup=ADMIN_KEYBOARD)
                            admin_states.pop(chat_id, None)
                        finally:
                            if os.path.exists(temp_input_path):
                                os.remove(temp_input_path)
                    else:
                        await send_message(chat_id, "❌ دانلود فایل از سرور بله با مشکل مواجه شد. مجدداً تلاش کنید.", reply_markup=ADMIN_KEYBOARD)
                        admin_states.pop(chat_id, None)
                    return
                else:
                    await send_message(chat_id, "⚠️ شما باید یک فایل (Document) اکسل بفرستید. در صورت انصراف «لغو» را بزنید.")
                    return

            if text == "📊 گزارش‌گیری و خروجی اکسل":
                await send_message(chat_id, "⏳ در حال استخراج اطلاعات از دیتابیس و ساخت فایل اکسل...")

                try:
                    total = await session.execute(select(func.count(User.id)))
                    total_count = total.scalar()
                    
                    vip_count_result = await session.execute(
                        select(func.count(User.id)).where(User.is_vip == True)
                    )
                    vip_count = vip_count_result.scalar()

                    pending_receipts_result = await session.execute(
                        select(func.count(User.id)).where(User.pending_receipt_file_id.is_not(None))
                    )
                    pending_count = pending_receipts_result.scalar()

                    caption_text = (
                        f"📊 خلاصه آمار ربات لیرانا:\n\n"
                        f"👥 تعداد کل کاربران: {total_count}\n"
                        f"💎 کاربران VIP فعال: {vip_count}\n"
                        f"⏳ منتظر تایید فیش: {pending_count}\n\n"
                        f"📁 فایل اکسل دیتابیس کامل به پیوست ارسال شد."
                    )

                    all_users_result = await session.execute(select(User))
                    all_users = all_users_result.scalars().all()

                    users_data = []
                    for u in all_users:
                        vip_expiry_str = "ندارد"
                        if u.vip_expiry:
                            tehran_tz = timezone(timedelta(hours=3, minutes=30))
                            expiry_tehran = u.vip_expiry.astimezone(tehran_tz)
                            j_date = jdatetime.datetime.fromgregorian(datetime=expiry_tehran)
                            vip_expiry_str = j_date.strftime("%Y/%m/%d %H:%M")

                        users_data.append({
                            "شناسه بله": u.bale_id,
                            "نام کاربری": u.username or "ندارد",
                            "نام و نام خانوادگی": u.full_name or "ثبت نشده",
                            "شماره موبایل": u.phone_number or "ثبت نشده",
                            "تاریخ تولد": u.birth_date or "ثبت نشده",
                            "نوع پوست": u.skin_type or "ثبت نشده",
                            "دغدغه اصلی": u.skin_concern or "ثبت نشده",
                            "تعداد سوالات پرسیده شده": u.ai_question_count or 0,
                            "کاربر VIP؟": "بله" if u.is_vip else "خیر",
                            "تاریخ انقضای VIP": vip_expiry_str,
                            "وضعیت فعلی (مرحله)": u.onboarding_step,
                            "دارای فیش بررسی نشده": "بله" if u.pending_receipt_file_id else "خیر",
                            "تاریخ ثبت نام": u.created_at_jalali or "نامشخص",
                        })

                    df = pd.DataFrame(users_data)
                    file_name = f"Lirana_Users_Report_{jdatetime.datetime.now().strftime('%Y-%m-%d_%H-%M')}.xlsx"
                    df.to_excel(file_name, index=False, engine='openpyxl')

                    await send_local_document(chat_id, file_name, caption=caption_text, reply_markup=ADMIN_KEYBOARD)

                    if os.path.exists(file_name):
                        os.remove(file_name)

                except Exception as e:
                    print(f"❌ خطا در ساخت اکسل: {e}")
                    await send_message(chat_id, "⚠️ متأسفانه خطایی در تولید فایل اکسل رخ داد.", reply_markup=ADMIN_KEYBOARD)
                
                return

            if text == "👁️ ورود به منوی کاربری (تست ربات)":
                first_name = extract_first_name(user.full_name)
                await send_message(
                    chat_id,
                    f"👁️ حالت تست فعال شد، {first_name}!\nمنوی کاربری رو می‌بینی 👇",
                    reply_markup=MAIN_KEYBOARD,
                )
                return

        # ══════════ منوی اصلی کاربر ══════════

        # --- شروع مشاوره ---
        if text.startswith("💡 شروع مشاوره"):
            if not user.is_vip:
                remaining = max(0, FREE_QUESTION_LIMIT - (user.ai_question_count or 0))
                if remaining <= 0:
                    user.onboarding_step = "awaiting_receipt"
                    await session.commit()
                    await send_message(
                        chat_id,
                        "⚠️ سوالات رایگان شما تمام شده!\n\n💎 برای ادامه مشاوره، اشتراک VIP تهیه کنید:",
                        reply_markup=CANCEL_KEYBOARD,
                    )
                    await send_message(chat_id, CHARGE_TEXT)
                    return

            user.onboarding_step = "chatting"
            await session.commit()

            first_name = extract_first_name(user.full_name)
            if user.is_vip:
                header = f"💎 {first_name} عزیز، مشاوره VIP فعاله!\n"
            else:
                remaining = max(0, FREE_QUESTION_LIMIT - (user.ai_question_count or 0))
                header = f"💡 {first_name} عزیز، {remaining} سوال رایگان داری.\n"

            await send_message(
                chat_id,
                f"{header}\n🤖 سوالت رو درباره پوست یا مو بپرس:\n(برای بازگشت «🔙 برگشت» رو بزن)",
                reply_markup=CANCEL_KEYBOARD,
            )
            return

        # --- کیف پول ---
        if text == "💰 کیف پول و شارژ هوش مصنوعی":
            wallet_text = build_wallet_text(user)
            if not user.is_vip:
                user.onboarding_step = "awaiting_receipt"
                await session.commit()
                await send_local_photo(chat_id, WALLET_VIP_PATH, caption=wallet_text, reply_markup=CANCEL_KEYBOARD)
            else:
                await send_local_photo(chat_id, WALLET_VIP_PATH, caption=wallet_text, reply_markup=MAIN_KEYBOARD)
            return

        # --- ویرایش پروفایل ---
        if text == "⚙️ ویرایش پروفایل پوستی":
            user.onboarding_step = "editing_profile"
            await session.commit()
            await send_message(
                chat_id,
                "🧴 نوع پوست جدیدت رو انتخاب کن:\n(برای انصراف «🔙 برگشت» رو بزن)",
                reply_markup=SKIN_TYPE_EDIT_KEYBOARD, # استفاده از کیبورد جدید که دکمه برگشت دارد
            )
            return

        # --- سایت و محصولات ---
        if text == "🛍️ ورود به سایت و محصولات":
            await send_message(
                chat_id,
                "🛍️ برای مشاهده محصولات به سایت لیرانا مراجعه کنید:\n\n🌐 liranabeauty.com",
                reply_markup=MAIN_KEYBOARD,
            )
            return

        # --- خرید اقساطی ---
        if text == "💳 خرید اقساطی محصولات":
            user.onboarding_step = "installment_menu"
            await session.commit()
            await send_local_photo(
                chat_id,
                INSTALLMENT_MENU_PATH,
                caption="لطفاً یکی از درگاه‌های اقساطی زیر را انتخاب کن:",
                reply_markup=INSTALLMENT_KEYBOARD,
            )
            return

        # --- درباره لیرانا ---
        if text == "ℹ️ درباره لیرانا و پشتیبانی":
            await send_message(chat_id, ABOUT_TEXT, reply_markup=MAIN_KEYBOARD)
            return

        # --- پیام نامشخص ---
        await send_message(
            chat_id,
            "🤔 متوجه نشدم! لطفاً از منوی پایین استفاده کن 👇",
            reply_markup=MAIN_KEYBOARD,
        )


# ═══════════════════════════════════════════
#  Polling
# ═══════════════════════════════════════════

def log_task_exception(task: asyncio.Task):
    try:
        exc = task.exception()
        if exc:
            print(f"❌ خطا در task پردازش آپدیت: {exc}")
    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"❌ خطا در log_task_exception: {e}")


async def process_update_with_user_lock(update: dict) -> None:
    """
    Process each user's updates sequentially.

    Different users can still be processed concurrently,
    but updates from the same chat_id will wait for each other.
    """

    chat_id = extract_chat_id_from_update(update)

    if chat_id is None:
        await process_update(update)
        return

    user_lock = USER_LOCKS.get(chat_id)

    if user_lock is None:
        user_lock = asyncio.Lock()
        USER_LOCKS[chat_id] = user_lock

    async with user_lock:
        await process_update(update)

async def main():
    # load_products()  # ❌ حذف شود؛ دیگر در main.py استفاده نمی‌کنیم

    print("🚀 ربات لیرانا شروع به کار کرد...")

    offset = 0
    timeout = httpx.Timeout(connect=15.0, read=40.0, write=15.0, pool=15.0)

    async with httpx.AsyncClient(timeout=timeout) as client:
        while True:
            try:
                resp = await client.get(
                    f"{BASE_URL}/getUpdates",
                    params={"offset": offset, "timeout": 30},
                )
                resp.raise_for_status()
                data = resp.json()

                if not data.get("ok", False):
                    print(f"❌ getUpdates rejected: {data}")
                    await asyncio.sleep(2)
                    continue

                for update in data.get("result", []):
                    offset = update["update_id"] + 1
                    task = asyncio.create_task(process_update_with_user_lock(update))
                    task.add_done_callback(log_task_exception)

            except httpx.ReadTimeout:
                continue
            except httpx.HTTPError as e:
                print(f"❌ HTTP error در polling: {e}")
                await asyncio.sleep(3)
            except Exception as e:
                print(f"❌ خطا در polling: {e}")
                await asyncio.sleep(3)


if __name__ == "__main__":
    asyncio.run(main())
