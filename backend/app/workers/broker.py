import dramatiq

from app import observability
from dramatiq.brokers.redis import RedisBroker

from app.config import settings

dramatiq.set_broker(RedisBroker(url=settings.redis_url))

observability.setup_logging()
