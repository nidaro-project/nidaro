from taskiq_redis import RedisScheduleSource

from nidaro.config import get_settings

scheduler = RedisScheduleSource(get_settings().redis_url)
