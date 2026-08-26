from taskiq_redis import ListQueueBroker

from nidaro.config import get_settings

# The queue is polled with an unbounded BRPOP, so reads must be allowed to
# wait indefinitely: redis-py's blocking pool defaults socket_timeout to 5
# seconds, and an idle worker then dies with an unhandled TimeoutError that
# taskiq-redis does not catch. TCP keepalive still detects a dead peer, and
# connects keep a short timeout.
broker = ListQueueBroker(
    get_settings().redis_url,
    socket_timeout=None,
    socket_connect_timeout=5,
    socket_keepalive=True,
)
