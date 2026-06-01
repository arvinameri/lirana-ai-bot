from sqlalchemy import Column, Integer, String, Boolean, DateTime, BigInteger
from sqlalchemy.sql import func
from app.db.database import Base
import jdatetime


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    bale_id = Column(BigInteger, unique=True, index=True, nullable=False)

    username = Column(String, nullable=True)
    full_name = Column(String, nullable=True)
    phone_number = Column(String, unique=True, index=True, nullable=True)

    # فیلدهای تخصصی لیرانا (باید به صورت شمسی ذخیره شوند)
    birth_date = Column(String, nullable=True)  # مثال: 1375/06/15
    skin_type = Column(String, nullable=True)
    skin_concern = Column(String, nullable=True)

    # مدیریت مراحل ثبت نام
    onboarding_step = Column(String, default="none")
    is_waiting_for_receipt = Column(Boolean, default=False)

    ai_question_count = Column(Integer, default=0)

    is_vip = Column(Boolean, default=False)
    vip_expiry = Column(DateTime(timezone=True), nullable=True)

    # ستون جدید: ذخیره موقت فیش ارسالی کاربر در دیتابیس
    pending_receipt_file_id = Column(String, nullable=True)

    # ذخیره زمان ثبت نام به شمسی در دیتابیس به صورت رشته
    created_at_jalali = Column(
        String, default=lambda: jdatetime.datetime.now().strftime("%Y/%m/%d %H:%M")
    )

    def __repr__(self):
        return f"<User(bale_id={self.bale_id}, full_name='{self.full_name}', step='{self.onboarding_step}')>"


# ======= جدول جدید برای تاریخچه فیش ها =======
class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, index=True)
    bale_id = Column(BigInteger, index=True, nullable=False)
    file_id = Column(String, nullable=False)
    status = Column(String, nullable=False)
    created_at_jalali = Column(
        String, default=lambda: jdatetime.datetime.now().strftime("%Y/%m/%d %H:%M")
    )

    def __repr__(self):
        return f"<Payment(bale_id={self.bale_id}, status='{self.status}')>"
