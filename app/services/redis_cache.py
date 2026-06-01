import json
import logging
from app.core.config import settings
from redis.asyncio import Redis, ConnectionError

logger = logging.getLogger(__name__)


class RedisService:
    def __init__(self):
        self.redis_client = Redis.from_url(
            f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}",
            decode_responses=True,
        )

    async def ping(self):
        try:
            await self.redis_client.ping()
            logger.info("✅ Successfully connected to Redis.")
        except ConnectionError as e:
            logger.error(f"❌ Failed to connect to Redis: {e}")

    async def get_ai_history(self, user_id: str) -> list:
        key = f"ai_chat_history:{user_id}"
        try:
            data = await self.redis_client.get(key)
            if data:
                return json.loads(data)
        except Exception as e:
            logger.error(f"Error reading from Redis for user {user_id}: {e}")
        return []

    async def save_ai_history(
        self, user_id: str, history: list, expire_time: int = 86400
    ):
        key = f"ai_chat_history:{user_id}"
        recent_history = history[-15:]
        try:
            await self.redis_client.setex(
                name=key,
                time=expire_time,
                value=json.dumps(recent_history, ensure_ascii=False),
            )
        except Exception as e:
            logger.error(f"Error saving to Redis for user {user_id}: {e}")

    async def clear_ai_history(self, user_id: str):
        key = f"ai_chat_history:{user_id}"
        await self.redis_client.delete(key)


redis_db = RedisService()
