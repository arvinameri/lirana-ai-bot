import asyncio
from app.db.database import engine, Base

# ایمپورت کردن مدل‌ها ضروری است تا SQLAlchemy آن‌ها را بشناسد
from app.db.models.user import User


async def init_models():
    # باز کردن یک ارتباط با دیتابیس
    async with engine.begin() as conn:
        print("⏳ در حال ساخت جداول دیتابیس لیرانا...")

        # این دستور تمام کلاس‌هایی که از Base ارث‌بری کردن (مثل User) رو پیدا میکنه
        # و جداولشون رو تو دیتابیس میسازه
        await conn.run_sync(Base.metadata.create_all)

        print("✅ جداول با موفقیت ساخته شدند!")


if __name__ == "__main__":
    # اجرای تابع غیرهمزمان
    asyncio.run(init_models())
