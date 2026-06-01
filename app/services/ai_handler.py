# =========================
# app/services/ai_handler.py
# =========================

import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

import jdatetime
from dotenv import load_dotenv
from openai import (
    APIConnectionError,
    APIError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    BadRequestError,
    OpenAIError,
    RateLimitError,
)

from app.services.redis_cache import redis_db


# =========================
# Logging
# =========================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("ai_errors.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)

logger = logging.getLogger(__name__)


# =========================
# Environment / AI Client
# =========================

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
AI_MODEL = os.getenv("AI_MODEL", "gpt-5.2")

client: AsyncOpenAI | None = None

if not OPENAI_API_KEY:
    logger.critical("OPENAI_API_KEY در env تنظیم نشده است.")
else:
    try:
        client = AsyncOpenAI(
            base_url="https://api.gapgpt.app/v1",
            api_key=OPENAI_API_KEY,
            timeout=25.0,
            max_retries=2,
        )
    except Exception as e:
        logger.critical(
            "خطای حیاتی در راه‌اندازی کلاینت هوش مصنوعی: %s",
            e,
            exc_info=True,
        )
        client = None


# =========================
# Paths / Constants
# =========================

# ai_handler.py داخل app/services قرار دارد.
# پس parents[1] برابر app است.
# مسیر نهایی محصولات:
# app/data/products.json

APP_DIR = Path(__file__).resolve().parents[1]
PRODUCTS_FILE_PATH = APP_DIR / "data" / "products.json"

MAX_HISTORY_LENGTH = 14
MAX_PRODUCT_DESCRIPTION_LENGTH = 220
MAX_PRODUCTS_CONTEXT_CHARS = 25000
MAX_AI_ANSWER_CHARS_IN_HISTORY = 1800
MAX_USER_MESSAGE_CHARS = 2500


# =========================
# Products Cache
# =========================

_PRODUCTS_CACHE: list[dict[str, Any]] | None = None
_PRODUCTS_CACHE_MTIME: float | None = None


def load_products(force_reload: bool = False) -> list[dict[str, Any]]:
    """
    خواندن امن products.json با cache.
    """

    global _PRODUCTS_CACHE
    global _PRODUCTS_CACHE_MTIME

    if not PRODUCTS_FILE_PATH.is_file():
        logger.error("فایل محصولات پیدا نشد: %s", PRODUCTS_FILE_PATH)
        return _PRODUCTS_CACHE or []

    try:
        current_mtime = PRODUCTS_FILE_PATH.stat().st_mtime
    except OSError as e:
        logger.error("خطا در خواندن mtime فایل محصولات: %s", e, exc_info=True)
        return _PRODUCTS_CACHE or []

    if (
        not force_reload
        and _PRODUCTS_CACHE is not None
        and _PRODUCTS_CACHE_MTIME == current_mtime
    ):
        return _PRODUCTS_CACHE

    try:
        with PRODUCTS_FILE_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, list):
            logger.error("فرمت products.json اشتباه است. ریشه فایل باید list باشد.")
            return _PRODUCTS_CACHE or []

        safe_products: list[dict[str, Any]] = []

        for index, item in enumerate(data):
            if not isinstance(item, dict):
                logger.warning(
                    "آیتم نامعتبر در products.json نادیده گرفته شد. index=%s",
                    index,
                )
                continue

            product_id = item.get("id")

            if product_id is None or str(product_id).strip() == "":
                logger.warning(
                    "محصول بدون id در products.json نادیده گرفته شد. index=%s",
                    index,
                )
                continue

            safe_products.append(item)

        _PRODUCTS_CACHE = safe_products
        _PRODUCTS_CACHE_MTIME = current_mtime

        logger.info(
            "PRODUCTS_LOADED | count=%s | file=%s",
            len(safe_products),
            PRODUCTS_FILE_PATH,
        )

        return safe_products

    except json.JSONDecodeError as e:
        logger.error("خطا در parse کردن products.json: %s", e, exc_info=True)
        return _PRODUCTS_CACHE or []

    except Exception as e:
        logger.error("خطای ناشناخته در خواندن products.json: %s", e, exc_info=True)
        return _PRODUCTS_CACHE or []


def get_product_by_id(product_id: int | str) -> dict[str, Any] | None:
    """
    پیدا کردن محصول فقط با id.
    هیچ match متنی روی نام، توضیحات یا جواب AI انجام نمی‌شود.
    """

    product_id_str = str(product_id).strip()

    if not product_id_str:
        return None

    for product in load_products():
        if str(product.get("id", "")).strip() == product_id_str:
            return product

    return None


def get_valid_product_ids() -> set[str]:
    """
    دریافت id تمام محصولات معتبر.
    """

    valid_ids: set[str] = set()

    for product in load_products():
        product_id = product.get("id")

        if product_id is None:
            continue

        product_id_str = str(product_id).strip()

        if product_id_str:
            valid_ids.add(product_id_str)

    return valid_ids


# =========================
# System Prompt
# =========================

SYSTEM_PROMPT = """
تو «لیرانا» هستی؛ دستیار هوشمند، مشاور زیبایی و مشاور پوست و موی گالری لیرانا.

لحن تو:
- فارسی، صمیمی، مهربان، دلگرم‌کننده و دخترانه.
- مثل یک دوست متخصص راهنمایی کن.
- پاسخ‌ها کاربردی، واضح و نه خیلی طولانی باشند.

قوانین حیاتی:

1. فقط درباره پوست، مو، زیبایی، روتین مراقبتی، آرایش، محصولات مراقبتی و محصولات زیبایی پاسخ بده.
اگر سوال نامرتبط بود، محترمانه بگو فقط می‌تونی درباره پوست، مو و زیبایی کمک کنی.

2. برای معرفی محصول از فروشگاه لیرانا:
فقط و فقط از لیست محصولات داده‌شده در بخش «موجودی محصولات لیرانا» استفاده کن.
هیچ محصولی را اختراع نکن.
هیچ قیمت، لینک، عکس، آدرس، موجودی یا مشخصات ساختگی نساز.

3. خروجی تو همیشه باید JSON معتبر باشد.
هیچ متن اضافه‌ای قبل یا بعد از JSON ننویس.
از markdown، کدبلاک و
```json استفاده نکن.

فرمت خروجی اجباری:

{
  "answer": "متن پاسخ مشاوره‌ای برای کاربر",
  "product_ids": []
}

4. مقدار product_ids:
- فقط id محصولاتی را قرار بده که واقعاً در لیست محصولات داده‌شده وجود دارند.
- اگر محصول فروشگاه را پیشنهاد می‌کنی، فقط id آن را داخل product_ids بگذار.
- product_ids باید array باشد.
- اگر هیچ محصول مناسبی در لیست نبود، product_ids را خالی بگذار.

5. در answer:
- لینک خرید ننویس.
- نام فایل عکس ننویس.
- آدرس عکس ننویس.
- id محصول را به کاربر نشان نده.
- قیمت قطعی ننویس مگر قیمت محصول در اطلاعات داده‌شده وجود داشته باشد.
- تمرکز answer روی مشاوره و دلیل انتخاب محصول باشد.
- ارسال عکس، لینک، دکمه خرید و جزئیات نهایی محصول توسط کد اصلی ربات انجام می‌شود، نه توسط تو.

6. اگر در لیست محصولات لیرانا محصول مناسبی نبود:
بگو: «عزیزم، الان محصولی که دقیقاً برای این نیازت مناسب باشه رو تو گالری موجود نداریم...»
بعد می‌توانی چند پیشنهاد عمومی یا داروخانه‌ای معتبر بدهی، اما بدون قیمت و بدون لینک خرید.
در این حالت product_ids باید [] باشد.

7. اگر کاربر نام محصولی که خودش دارد را فرستاد:
آن را از نظر کاربرد، ترکیبات احتمالی، مزایا، محدودیت‌ها و مناسب بودن برای نوع پوست تحلیل کن.
اگر لازم بود، از او عکس محصول یا ترکیبات را بخواه.

8. برای مشکلات پوستی مبهم مثل لک، جوش شدید، التهاب غیرعادی، قرمزی شدید یا بافت مشکوک:
از کاربر بخواه عکس واضح در نور طبیعی بفرستد تا بهتر راهنمایی شود.

9. برای موارد پزشکی جدی مثل زخم باز، عفونت، سوختگی شدید، ریزش موی سکه‌ای، درد شدید، ترشح، خونریزی یا واکنش آلرژیک شدید:
تشخیص یا درمان قطعی نده و کاربر را به پزشک متخصص ارجاع بده.

10. در پایان answer، اگر مناسب بود، با لحنی صمیمی بپرس:
«سوال دیگه‌ای داری یا می‌خوای محصول دیگه‌ای هم معرفی کنم؟ 🌸»
"""


# =========================
# Text / History Helpers
# =========================

def sanitize_text(value: Any, max_chars: int | None = None) -> str:
    """
    تبدیل امن مقدار به متن تمیز.
    """

    text = str(value or "").strip()
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)

    if max_chars is not None and len(text) > max_chars:
        text = text[:max_chars].strip()

    return text


def sanitize_ai_history(history: Any) -> list[dict[str, str]]:
    """
    پاکسازی history برای ارسال امن به AI.
    """

    if not isinstance(history, list):
        return []

    safe_history: list[dict[str, str]] = []

    for item in history:
        if not isinstance(item, dict):
            continue

        role = item.get("role")
        content = item.get("content")

        if role not in {"user", "assistant"}:
            continue

        max_chars = (
            MAX_USER_MESSAGE_CHARS
            if role == "user"
            else MAX_AI_ANSWER_CHARS_IN_HISTORY
        )

        content_text = sanitize_text(content, max_chars=max_chars)

        if not content_text:
            continue

        safe_history.append(
            {
                "role": role,
                "content": content_text,
            }
        )

    return safe_history[-MAX_HISTORY_LENGTH:]


async def get_safe_ai_history(user_id_str: str) -> list[dict[str, str]]:
    """
    خواندن امن history از Redis.
    اگر Redis خطا بدهد، پاسخ AI نباید fail شود.
    """

    try:
        history = await redis_db.get_ai_history(user_id_str)
        return sanitize_ai_history(history)

    except Exception as e:
        logger.warning(
            "Redis history load failed | user_id=%s | error=%s",
            user_id_str,
            e,
            exc_info=True,
        )
        return []


async def save_safe_ai_history(
    user_id_str: str,
    history: list[dict[str, str]],
) -> None:
    """
    ذخیره امن history در Redis.
    اگر Redis خطا بدهد، پاسخ کاربر نباید از بین برود.
    """

    try:
        safe_history = sanitize_ai_history(history)
        await redis_db.save_ai_history(user_id_str, safe_history[-MAX_HISTORY_LENGTH:])

    except Exception as e:
        logger.warning(
            "Redis history save failed | user_id=%s | error=%s",
            user_id_str,
            e,
            exc_info=True,
        )


# =========================
# Products Context
# =========================

def build_minimal_products_context(products_list: list[dict[str, Any]]) -> str:
    """
    ساخت context محصولات برای AI.

    مهم:
    - product_url را به AI نمی‌دهیم.
    - image_filename را به AI نمی‌دهیم.
    - AI فقط id محصول را انتخاب می‌کند.
    - لینک و عکس باید در main.py از products.json خوانده و ارسال شوند.
    """

    minimal_products: list[dict[str, Any]] = []

    for product in products_list:
        if not isinstance(product, dict):
            continue

        product_id = product.get("id")

        if product_id is None or str(product_id).strip() == "":
            continue

        if product.get("in_stock") is False:
            continue

        minimal_products.append(
            {
                "id": product_id,
                "name_fa": product.get("name_fa", ""),
                "name_en": product.get("name_en", ""),
                "brand": product.get("brand", ""),
                "category": product.get("category", ""),
                "skin_type": product.get("skin_type", ""),
                "price_original": product.get("price_original", ""),
                "price_discounted": product.get("price_discounted", ""),
                "description": sanitize_text(
                    product.get("description", ""),
                    max_chars=MAX_PRODUCT_DESCRIPTION_LENGTH,
                ),
            }
        )

    context = json.dumps(minimal_products, ensure_ascii=False)

    if len(context) > MAX_PRODUCTS_CONTEXT_CHARS:
        logger.warning(
            "Products context truncated | original_chars=%s | max_chars=%s",
            len(context),
            MAX_PRODUCTS_CONTEXT_CHARS,
        )
        context = context[:MAX_PRODUCTS_CONTEXT_CHARS]

    return context


# =========================
# User Info Helpers
# =========================

def get_user_age_display(user_age: str, user_id: str) -> str:
    """
    اگر user_age تاریخ تولد جلالی مثل 1378/05/20 باشد،
    سن تقریبی محاسبه می‌شود.
    """

    user_age_display = sanitize_text(user_age)

    if not user_age_display or user_age_display == "نامشخص":
        return "نامشخص"

    if "/" not in user_age_display:
        return user_age_display

    try:
        birth_year = int(user_age_display.split("/")[0])
        calculated_age = jdatetime.datetime.now().year - birth_year

        if 5 < calculated_age < 100:
            return f"{user_age_display} (حدوداً {calculated_age} ساله)"

    except Exception as e:
        logger.warning(
            "خطا در محاسبه سن | user_id=%s | user_age=%s | error=%s",
            user_id,
            user_age_display,
            e,
        )

    return user_age_display


# =========================
# AI Response Parsing
# =========================

def extract_assistant_message(response: Any) -> str:
    """
    استخراج امن متن پاسخ از response سازگار با OpenAI.
    """

    if response is None:
        raise ValueError("AI response is None.")

    choices = getattr(response, "choices", None)

    if not choices:
        raise ValueError("AI response has no choices.")

    first_choice = choices[0]

    if first_choice is None:
        raise ValueError("AI first choice is None.")

    message = getattr(first_choice, "message", None)

    if message is None:
        raise ValueError("AI choice has no message.")

    content = getattr(message, "content", None)

    if content is None:
        raise ValueError("AI message content is None.")

    content_text = sanitize_text(content)

    if not content_text:
        raise ValueError("AI message content is empty.")

    return content_text


def strip_json_code_fence(text: str) -> str:
    """
    حذف code fence اگر مدل اشتباهی خروجی را داخل بلاک json برگرداند.
    """

    clean = sanitize_text(text)

    clean = re.sub(r"^\s*```(?:json)?\s*", "", clean, flags=re.IGNORECASE)
    clean = re.sub(r"\s*```\s*$", "", clean)
 
    return clean.strip()


def extract_json_object(text: str) -> dict[str, Any]:
    """
    تبدیل خروجی AI به dict معتبر.
    """

    clean_text = strip_json_code_fence(text)

    try:
        data = json.loads(clean_text)

    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", clean_text, flags=re.DOTALL)

        if not match:
            raise ValueError("AI output is not valid JSON.")

        try:
            data = json.loads(match.group(0))

        except json.JSONDecodeError as e:
            raise ValueError(f"AI output JSON parse failed: {e}") from e

    if not isinstance(data, dict):
        raise ValueError("AI JSON root must be an object.")

    return data


def normalize_ai_payload(data: dict[str, Any]) -> dict[str, Any]:
    """
    نرمال‌سازی خروجی AI به ساختار ثابت:
    {
        "answer": "...",
        "product_ids": [...]
    }
    """

    answer = sanitize_text(data.get("answer"))

    if not answer:
        answer = (
            "عزیزم، الان نتونستم پاسخ دقیقی بسازم. "
            "لطفاً سوالت رو یک‌بار واضح‌تر بپرس 🌸"
        )

    raw_product_ids = data.get("product_ids", [])

    if not isinstance(raw_product_ids, list):
        raw_product_ids = []

    valid_ids = get_valid_product_ids()
    clean_product_ids: list[int | str] = []
    seen: set[str] = set()

    for raw_id in raw_product_ids:
        raw_id_str = str(raw_id).strip()

        if not raw_id_str:
            continue

        if raw_id_str not in valid_ids:
            logger.warning(
                "AI returned invalid product_id and it was removed: %s",
                raw_id_str,
            )
            continue

        if raw_id_str in seen:
            continue

        seen.add(raw_id_str)

        if raw_id_str.isdigit():
            clean_product_ids.append(int(raw_id_str))
        else:
            clean_product_ids.append(raw_id_str)

    return {
        "answer": answer,
        "product_ids": clean_product_ids,
    }


def build_fallback_payload(message: str) -> dict[str, Any]:
    """
    خروجی استاندارد برای خطاها.
    """

    return {
        "answer": message,
        "product_ids": [],
    }


# =========================
# Error Messages
# =========================

def build_ai_error_message(error_type: str) -> str:
    """
    پیام‌های خطای قابل نمایش به کاربر.
    """

    if error_type == "timeout":
        return (
            "عزیزم، پاسخ‌دهی مشاور هوشمند کمی طول کشید. "
            "لطفاً چند لحظه دیگه دوباره سوالت رو بفرست 🌸"
        )

    if error_type == "auth":
        return (
            "عزیزم، سرویس مشاوره الان مشکل تنظیمات دارد. "
            "تیم پشتیبانی باید بررسی‌اش کند 🙏"
        )

    if error_type == "rate_limit":
        return (
            "عزیزم، الان تعداد درخواست‌ها خیلی زیاد شده. "
            "لطفاً یکی دو دقیقه دیگه دوباره امتحان کن 🌸"
        )

    if error_type == "provider":
        return (
            "عزیزم، سرویس هوش مصنوعی الان موقتاً درست پاسخ نمی‌دهد. "
            "لطفاً چند دقیقه دیگه دوباره امتحان کن 🙏"
        )

    if error_type == "malformed":
        return (
            "عزیزم، الان پاسخ مناسبی از مشاور هوشمند دریافت نکردم. "
            "لطفاً سوالت رو یک‌بار دیگه بپرس 🌸"
        )

    if error_type == "bad_request":
        return (
            "عزیزم، درخواستت برای مشاور هوشمند قابل پردازش نبود. "
            "لطفاً سوالت رو کوتاه‌تر و واضح‌تر بفرست 🌸"
        )

    return (
        "عزیزم، متأسفم! الان یه مشکل فنی کوچیک برای مشاور هوشمندم پیش اومده 🙏 "
        "لطفاً چند دقیقه دیگه دوباره امتحان کن 🌸"
    )


# =========================
# Main AI Function
# =========================

async def get_ai_response(
    user_message: str,
    user_id: str,
    user_skin_type: str = "نامشخص",
    user_concern: str = "نامشخص",
    user_age: str = "نامشخص",
) -> dict[str, Any]:
    """
    گرفتن پاسخ از AI.

    خروجی همیشه dict است:

    {
        "answer": "متن پاسخ",
        "product_ids": [1, 2]
    }

    نکته:
    AI نباید لینک یا عکس بسازد.
    main.py باید با product_ids محصول را از products.json پیدا کند
    و لینک/عکس را همان‌جا ارسال کند.
    """

    user_id_str = sanitize_text(user_id) or "unknown"

    if client is None:
        logger.error("AI client مقداردهی نشده است.")
        return build_fallback_payload(build_ai_error_message("provider"))

    clean_user_message = sanitize_text(
        user_message,
        max_chars=MAX_USER_MESSAGE_CHARS,
    )

    if not clean_user_message:
        return build_fallback_payload(
            "عزیزم، لطفاً سوالت رو یک‌بار واضح‌تر برام بفرست تا بهتر راهنمایی‌ات کنم 🌸"
        )

    try:
        chat_history = await get_safe_ai_history(user_id_str)

        chat_history.append(
            {
                "role": "user",
                "content": clean_user_message,
            }
        )

        chat_history = sanitize_ai_history(chat_history)

        products_list = load_products()
        products_context = build_minimal_products_context(products_list)

        today_jalali = jdatetime.datetime.now().strftime("%Y/%m/%d")
        user_age_display = get_user_age_display(str(user_age), user_id_str)

        user_skin_type_safe = sanitize_text(user_skin_type) or "نامشخص"
        user_concern_safe = sanitize_text(user_concern) or "نامشخص"

        dynamic_system_prompt = (
            f"{SYSTEM_PROMPT}\n\n"
            f"--- پرونده دیجیتال کاربر ---\n"
            f"تاریخ جلالی: {today_jalali}\n"
            f"سن/تاریخ تولد: {user_age_display}\n"
            f"نوع پوست: {user_skin_type_safe}\n"
            f"دغدغه اصلی: {user_concern_safe}\n\n"
            f"--- موجودی محصولات لیرانا ---\n"
            f"{products_context}\n\n"
            f"یادآوری بسیار مهم:\n"
            f"- فقط JSON معتبر برگردان.\n"
            f"- لینک خرید ننویس.\n"
            f"- عکس یا نام فایل عکس ننویس.\n"
            f"- اگر محصولی از موجودی مناسب بود، فقط id آن را در product_ids بگذار.\n"
        )

        messages: list[dict[str, str]] = [
            {
                "role": "system",
                "content": dynamic_system_prompt,
            }
        ]

        messages.extend(chat_history)

        logger.info(
            "AI_REQUEST | user_id=%s | history_count=%s | products_count=%s",
            user_id_str,
            len(chat_history),
            len(products_list),
        )

        response = await client.chat.completions.create(
            model=AI_MODEL,
            messages=messages,
            temperature=0.35,
            max_tokens=700,
            top_p=0.85,
            frequency_penalty=0.3,
            presence_penalty=0.2,
        )

        try:
            assistant_raw_message = extract_assistant_message(response)
            assistant_json = extract_json_object(assistant_raw_message)
            payload = normalize_ai_payload(assistant_json)

        except ValueError as e:
            logger.error(
                "Malformed AI response | user_id=%s | error=%s",
                user_id_str,
                e,
                exc_info=True,
            )
            return build_fallback_payload(build_ai_error_message("malformed"))

        chat_history.append(
            {
                "role": "assistant",
                "content": payload["answer"],
            }
        )

        chat_history = sanitize_ai_history(chat_history)

        await save_safe_ai_history(user_id_str, chat_history)

        logger.info(
            "AI_RESPONSE_OK | user_id=%s | product_ids=%s",
            user_id_str,
            payload.get("product_ids", []),
        )

        return payload

    except APITimeoutError as e:
        logger.warning(
            "AI timeout | user_id=%s | error=%s",
            user_id_str,
            e,
            exc_info=True,
        )
        return build_fallback_payload(build_ai_error_message("timeout"))

    except asyncio.TimeoutError as e:
        logger.warning(
            "Async timeout | user_id=%s | error=%s",
            user_id_str,
            e,
            exc_info=True,
        )
        return build_fallback_payload(build_ai_error_message("timeout"))

    except AuthenticationError as e:
        logger.critical(
            "AI authentication error | user_id=%s | error=%s",
            user_id_str,
            e,
            exc_info=True,
        )
        return build_fallback_payload(build_ai_error_message("auth"))

    except RateLimitError as e:
        logger.warning(
            "AI rate limit | user_id=%s | error=%s",
            user_id_str,
            e,
            exc_info=True,
        )
        return build_fallback_payload(build_ai_error_message("rate_limit"))

    except BadRequestError as e:
        logger.error(
            "AI bad request | user_id=%s | error=%s",
            user_id_str,
            e,
            exc_info=True,
        )
        return build_fallback_payload(build_ai_error_message("bad_request"))

    except APIConnectionError as e:
        logger.warning(
            "AI connection error | user_id=%s | error=%s",
            user_id_str,
            e,
            exc_info=True,
        )
        return build_fallback_payload(build_ai_error_message("provider"))

    except APIStatusError as e:
        logger.error(
            "AI provider status error | user_id=%s | status_code=%s | error=%s",
            user_id_str,
            getattr(e, "status_code", None),
            e,
            exc_info=True,
        )
        return build_fallback_payload(build_ai_error_message("provider"))

    except APIError as e:
        logger.error(
            "AI API error | user_id=%s | error=%s",
            user_id_str,
            e,
            exc_info=True,
        )
        return build_fallback_payload(build_ai_error_message("provider"))

    except OpenAIError as e:
        logger.error(
            "Generic OpenAI error | user_id=%s | error=%s",
            user_id_str,
            e,
            exc_info=True,
        )
        return build_fallback_payload(build_ai_error_message("provider"))

    except Exception as e:
        logger.error(
            "Critical error in get_ai_response | user_id=%s | error=%s",
            user_id_str,
            e,
            exc_info=True,
        )
        return build_fallback_payload(build_ai_error_message("unknown"))
