"""
Redis Asynchronous Client, Pub/Sub Event Publisher, and Background Consumer.

Why Redis Pub/Sub for Disruption Events?
- Decoupling: The status poller (or manual scenario simulation) does not need to know
  anything about the Agent Orchestrator or the Detection Service. It simply emits:
  "Flight 6E-204 status changed to CANCELLED" onto a channel.
- Asynchronous Non-blocking: Subscribing listeners react instantaneously without HTTP polling overhead.
- Resilience: If Redis is temporarily unreachable during local development, we provide
  a graceful fallback logger so local development can continue seamlessly without crashing.
"""

import asyncio
import json
import logging
from typing import Any, AsyncGenerator, Callable, Dict, Optional
import redis.asyncio as aioredis
from redis.exceptions import ConnectionError as RedisConnectionError
from app.core.config import get_settings

logger = logging.getLogger("reroute.redis")
settings = get_settings()

# Global Redis client instance
redis_client: Optional[aioredis.Redis] = None


async def get_redis_client() -> Optional[aioredis.Redis]:
    """
    Initializes and returns the singleton Async Redis client.
    """
    global redis_client
    if redis_client is None:
        try:
            redis_client = aioredis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
            )
            # Test ping to ensure connection is live
            await redis_client.ping()
            logger.info("Successfully connected to Redis at %s", settings.REDIS_URL)
        except (RedisConnectionError, Exception) as e:
            logger.warning(
                "Could not connect to Redis at %s: %s. "
                "Running in local fallback mode (in-memory mock event dispatcher).",
                settings.REDIS_URL,
                str(e),
            )
            redis_client = None
    return redis_client


async def close_redis() -> None:
    """
    Cleanly closes the Redis connection on server shutdown.
    """
    global redis_client
    if redis_client is not None:
        await redis_client.close()
        redis_client = None
        logger.info("Redis connection closed cleanly.")


async def publish_event(channel: str, event_data: Dict[str, Any]) -> bool:
    """
    Publishes an event dictionary (serialized to JSON string) onto a Redis channel.
    
    Returns:
        bool: True if published successfully, False if in fallback mode.
    """
    client = await get_redis_client()
    payload = json.dumps(event_data)
    
    if client is not None:
        try:
            await client.publish(channel, payload)
            logger.info("[REDIS PUB] Emitted event to '%s': %s", channel, payload)
            return True
        except Exception as e:
            logger.error("[REDIS PUB ERROR] Failed to publish event: %s", str(e))
            return False
    else:
        # Fallback for local development if Redis daemon is not running
        logger.info("[LOCAL FALLBACK EVENT] Simulated pub to '%s': %s", channel, payload)
        # Directly invoke the registered listener hook if in fallback mode
        await handle_incoming_event(event_data)
        return True


async def handle_incoming_event(event: Dict[str, Any]) -> None:
    """
    Core event handler for incoming disruption messages.
    Invokes the Consumer to hydrate DB state, run the pipeline, and persist decisions.
    """
    event_type = event.get("event_type", "UNKNOWN")
    flight_id = event.get("flight_id", "N/A")
    flight_number = event.get("flight_number", "N/A")
    logger.info(
        "[REDIS EVENT CONSUMER] Ingesting disruption event: type=%s, flight_id=%s, flight_number=%s",
        event_type,
        flight_id,
        flight_number,
    )
    from app.services.consumer import process_disruption_event
    await process_disruption_event(event)



async def start_redis_listener(stop_event: asyncio.Event) -> None:
    """
    Background worker task that runs continuously in the FastAPI lifespan.
    It subscribes to `REDIS_CHANNEL` and listens for published messages.
    
    Why `asyncio.Event` (stop_event)?
    - When the FastAPI server shuts down, we set `stop_event.set()`.
    - This allows the infinite loop below to exit gracefully without leaving orphaned tasks.
    """
    client = await get_redis_client()
    if client is None:
        logger.info("[REDIS LISTENER] Redis not available; background listener waiting for fallback triggers.")
        # Keep task alive until shutdown
        await stop_event.wait()
        return

    pubsub = client.pubsub()
    await pubsub.subscribe(settings.REDIS_CHANNEL)
    logger.info("[REDIS LISTENER] Subscribed to channel: '%s'", settings.REDIS_CHANNEL)

    try:
        while not stop_event.is_set():
            try:
                # get_message with a short timeout allows us to check `stop_event` periodically
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message is not None and message.get("type") == "message":
                    raw_data = message.get("data")
                    try:
                        data = json.loads(raw_data)
                        await handle_incoming_event(data)
                    except json.JSONDecodeError:
                        logger.warning("[REDIS LISTENER] Received non-JSON message: %s", raw_data)
            except Exception as loop_err:
                if not stop_event.is_set():
                    logger.error("[REDIS LISTENER ERROR] Error processing message: %s", str(loop_err))
                    await asyncio.sleep(1.0)
    finally:
        await pubsub.unsubscribe(settings.REDIS_CHANNEL)
        await pubsub.close()
        logger.info("[REDIS LISTENER] Unsubscribed and closed pubsub listener.")
