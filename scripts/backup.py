import os
import subprocess
import zipfile
import datetime
import requests
import logging
import sys

# اضافه کردن مسیر روت پروژه به sys.path برای اینکه بتوانیم app.core.config را ایمپورت کنیم
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from app.core.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BACKUP_DIR = os.path.join(os.path.dirname(__file__), "backups")


def create_postgres_backup():
    if not os.path.exists(BACKUP_DIR):
        os.makedirs(BACKUP_DIR)

    date_str = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    sql_filename = os.path.join(BACKUP_DIR, f"lirana_db_{date_str}.sql")
    zip_filename = os.path.join(BACKUP_DIR, f"lirana_backup_{date_str}.zip")

    # تنظیم رمز عبور دیتابیس به عنوان متغیر محیطی تا pg_dump رمز نخواهد
    env = os.environ.copy()
    env["PGPASSWORD"] = settings.POSTGRES_PASSWORD

    # دستور بک‌آپ‌گیری از PostgreSQL
    dump_command = [
        "pg_dump",
        "-h",
        settings.POSTGRES_SERVER,
        "-p",
        settings.POSTGRES_PORT,
        "-U",
        settings.POSTGRES_USER,
        "-F",
        "p",  # فرمت متن ساده (Plain text sql)
        "-f",
        sql_filename,
        settings.POSTGRES_DB,
    ]

    try:
        logger.info(
            f"⏳ Starting PostgreSQL backup for database: {settings.POSTGRES_DB}..."
        )

        # اجرای دستور در خط فرمان سیستم عامل
        process = subprocess.run(
            dump_command, env=env, check=True, capture_output=True, text=True
        )

        # فشرده‌سازی فایل SQL تولید شده به ZIP
        logger.info("⏳ Zipping the backup file...")
        with zipfile.ZipFile(zip_filename, "w", zipfile.ZIP_DEFLATED) as zipf:
            zipf.write(sql_filename, os.path.basename(sql_filename))

        # پاک کردن فایل SQL اصلی برای خلوت ماندن هارد (فقط زیپ را نگه می‌داریم)
        os.remove(sql_filename)

        logger.info(f"✅ Backup created successfully: {zip_filename}")
        return zip_filename

    except subprocess.CalledProcessError as e:
        logger.error(f"❌ Error during pg_dump execution: {e.stderr}")
        return None
    except Exception as e:
        logger.error(f"❌ Error creating backup: {e}")
        return None


def send_backup_to_bale(zip_filepath):
    # چک می‌کنیم آیا ادمینی در لیست تعریف شده یا نه
    if not settings.ADMIN_IDS:
        logger.warning(
            "⚠️ No ADMIN_IDS defined in config. Backup saved locally but not sent."
        )
        return

    url = f"{settings.BALE_API_URL}{settings.BALE_BOT_TOKEN}/sendDocument"
    caption = f"📦 بک‌آپ خودکار PostgreSQL لیرانا\n📅 تاریخ: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}"

    try:
        # ارسال برای اولین ادمین در لیست
        target_admin_id = settings.ADMIN_IDS[0]

        with open(zip_filepath, "rb") as file:
            files = {"document": file}
            data = {"chat_id": target_admin_id, "caption": caption}

            logger.info("⏳ Sending backup to Bale...")
            response = requests.post(url, data=data, files=files)

            if response.status_code == 200:
                logger.info("✅ Backup successfully sent to Admin via Bale.")
                # اختیاری: پاک کردن فایل زیپ بعد از ارسال موفق
                # os.remove(zip_filepath)
            else:
                logger.error(
                    f"❌ Failed to send backup. Status: {response.status_code}, Response: {response.text}"
                )
    except Exception as e:
        logger.error(f"❌ Error sending backup to Bale: {e}")


if __name__ == "__main__":
    backup_file = create_postgres_backup()

    if backup_file:
        send_backup_to_bale(backup_file)
