from taskiq_redis import ListQueueBroker

from nidaro.config import get_settings

broker = ListQueueBroker(get_settings().redis_url)
