"""Small command-line exercises for Redis and RabbitMQ."""

import argparse
import os
import ssl
import sys
import uuid
from urllib.parse import parse_qs, urlsplit

import pika
import redis

QUEUE = "lab.jobs"
EXCHANGE = "lab.events"
ROUTING_KEY = "job"


def required(name):
    value = os.environ.get(name)
    if not value:
        raise ValueError(f"{name} must be set")
    return value


def connection_url(name, secure_scheme, insecure_scheme):
    value = required(name)
    parsed = urlsplit(value)
    if parsed.scheme != secure_scheme and (
        parsed.scheme != insecure_scheme or os.environ.get("LAB_ALLOW_INSECURE") != "1"
    ):
        raise ValueError(f"{name} must use {secure_scheme}")
    if name == "REDIS_URL" and any(key.startswith("ssl_") for key in parse_qs(parsed.query)):
        raise ValueError("REDIS_URL must not override TLS options")
    return value


def secret_file(name):
    with open(required(name), encoding="utf-8") as secret:
        value = secret.read().strip()
    if not value:
        raise ValueError(f"{name} refers to an empty secret")
    return value


def port(name, default):
    value = int(os.environ.get(name, default))
    if not 1 <= value <= 65535:
        raise ValueError(f"{name} must be a valid TCP port")
    return value


def redis_client():
    if os.environ.get("REDIS_PASSWORD_FILE"):
        return redis.Redis(
            host=required("REDIS_HOST"),
            port=port("REDIS_PORT", 6379),
            password=secret_file("REDIS_PASSWORD_FILE"),
            ssl=True,
            ssl_ca_certs=required("REDIS_CA_FILE"),
            ssl_check_hostname=True,
            socket_connect_timeout=5,
            socket_timeout=5,
            decode_responses=True,
        )
    url = connection_url("REDIS_URL", "rediss", "redis")
    options = {}
    if urlsplit(url).scheme == "rediss":
        options["ssl_ca_certs"] = os.environ.get("REDIS_CA_FILE")
    return redis.Redis.from_url(
        url,
        socket_connect_timeout=5,
        socket_timeout=5,
        decode_responses=True,
        **options,
    )


def rabbit_connection():
    if os.environ.get("RABBITMQ_PASSWORD_FILE"):
        host = required("RABBITMQ_HOST")
        context = ssl.create_default_context(cafile=required("AMQP_CA_FILE"))
        params = pika.ConnectionParameters(
            host=host,
            port=port("RABBITMQ_PORT", 5671),
            virtual_host=required("RABBITMQ_VHOST"),
            credentials=pika.PlainCredentials(
                secret_file("RABBITMQ_USERNAME_FILE"),
                secret_file("RABBITMQ_PASSWORD_FILE"),
            ),
            ssl_options=pika.SSLOptions(context, host),
        )
    else:
        params = pika.URLParameters(connection_url("AMQP_URL", "amqps", "amqp"))
    params.socket_timeout = 5
    params.stack_timeout = 10
    params.blocked_connection_timeout = 10
    if params.ssl_options:
        context = ssl.create_default_context(cafile=os.environ.get("AMQP_CA_FILE"))
        params.ssl_options = pika.SSLOptions(context, params.host)
    return pika.BlockingConnection(params)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    put = commands.add_parser("cache-put", help="cache a value with a TTL")
    put.add_argument("key")
    put.add_argument("value")
    put.add_argument("--ttl", type=int, default=60)
    get = commands.add_parser("cache-get", help="read a cached value")
    get.add_argument("key")
    commands.add_parser("count", help="increment an atomic counter")
    commands.add_parser("check", help="check both connections")
    publish = commands.add_parser("publish", help="publish a persistent job")
    publish.add_argument("message")
    commands.add_parser("consume", help="process one job with manual acknowledgement")
    args = parser.parse_args(argv)

    if args.command == "cache-put":
        if args.ttl < 1:
            parser.error("--ttl must be positive")
        redis_client().set("lab:cache:" + args.key, args.value, ex=args.ttl)
        print("stored")
    elif args.command == "cache-get":
        value = redis_client().get("lab:cache:" + args.key)
        print(value if value is not None else "(cache miss)")
    elif args.command == "count":
        print(redis_client().incr("lab:counter"))
    elif args.command == "check":
        redis_client().ping()
        with rabbit_connection():
            pass
        print("connections ready")
    elif args.command == "publish":
        if len(args.message.encode("utf-8")) > 4096:
            parser.error("message must be at most 4096 bytes")
        message_id = str(uuid.uuid4())
        with rabbit_connection() as connection:
            channel = connection.channel()
            channel.confirm_delivery()
            channel.basic_publish(
                exchange=EXCHANGE,
                routing_key=ROUTING_KEY,
                body=args.message.encode("utf-8"),
                properties=pika.BasicProperties(delivery_mode=2, message_id=message_id),
                mandatory=True,
            )
        print(f"published {message_id}")
    else:
        with rabbit_connection() as connection:
            channel = connection.channel()
            method, properties, body = channel.basic_get(QUEUE, auto_ack=False)
            if method is None:
                print("(queue empty)")
                return
            try:
                if not properties.message_id:
                    raise ValueError("job has no message ID")
                message = body.decode("utf-8")
            except ValueError:
                channel.basic_nack(method.delivery_tag, requeue=False)
                raise
            try:
                print(f"job {properties.message_id!r}: {message!r}", flush=True)
                channel.basic_ack(method.delivery_tag)
            except Exception:
                channel.basic_nack(method.delivery_tag, requeue=True)
                raise


if __name__ == "__main__":
    try:
        main()
    except (ValueError, redis.RedisError, pika.exceptions.AMQPError, OSError) as exc:
        print(f"messaging lab failed: {type(exc).__name__}", file=sys.stderr)
        sys.exit(1)
