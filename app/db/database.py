import os
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base

# خواندن اطلاعات از فایل .env
load_dotenv()

# گرفتن آدرس دیتابیس
DATABASE_URL = os.getenv("DATABASE_URL")

# ساخت موتور اتصال به دیتابیس به صورت نامتقارن (Async)
engine = create_async_engine(DATABASE_URL, echo=False)

# این دقیقاً همان متغیری است که main.py دنبال آن می‌گردد!
async_session_maker = async_sessionmaker(
    bind=engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
)

Base = declarative_base()
