import unittest
from unittest.mock import MagicMock, mock_open, patch

import lab


class LabTests(unittest.TestCase):
    @patch.dict("os.environ", {"REDIS_URL": "redis://localhost:6379"}, clear=True)
    def test_insecure_connection_requires_explicit_opt_in(self):
        with self.assertRaises(ValueError):
            lab.redis_client()

    @patch.dict("os.environ", {"REDIS_URL": "rediss://localhost?ssl_cert_reqs=none"}, clear=True)
    def test_certificate_verification_cannot_be_disabled(self):
        with self.assertRaises(ValueError):
            lab.redis_client()

    @patch.dict("os.environ", {"AMQP_URL": "amqp://localhost"}, clear=True)
    def test_insecure_amqp_requires_explicit_opt_in(self):
        with self.assertRaises(ValueError):
            lab.rabbit_connection()

    @patch.dict("os.environ", {
        "REDIS_HOST": "redis.example",
        "REDIS_PASSWORD_FILE": "/credentials/password",
        "REDIS_CA_FILE": "/ca/ca.crt",
    }, clear=True)
    @patch("lab.redis.Redis")
    @patch("builtins.open", new_callable=mock_open, read_data="password")
    def test_cluster_redis_uses_verified_tls_and_secret_file(self, _open, client):
        lab.redis_client()
        self.assertEqual(client.call_args.kwargs["password"], "password")
        self.assertTrue(client.call_args.kwargs["ssl"])
        self.assertTrue(client.call_args.kwargs["ssl_check_hostname"])
        self.assertEqual(client.call_args.kwargs["ssl_ca_certs"], "/ca/ca.crt")

    @patch.dict("os.environ", {"RABBITMQ_PORT": "70000"}, clear=True)
    def test_invalid_port_rejected(self):
        with self.assertRaises(ValueError):
            lab.port("RABBITMQ_PORT", 5671)

    @patch("lab.redis_client")
    def test_cache_has_expiry(self, client):
        lab.main(["cache-put", "key", "value", "--ttl", "15"])
        client.return_value.set.assert_called_once_with("lab:cache:key", "value", ex=15)

    @patch("lab.redis_client")
    def test_counter_is_atomic(self, client):
        lab.main(["count"])
        client.return_value.incr.assert_called_once_with("lab:counter")

    @patch("lab.rabbit_connection")
    def test_publish_is_confirmed_persistent_and_mandatory(self, connect):
        channel = connect.return_value.__enter__.return_value.channel.return_value
        lab.main(["publish", "hello"])
        channel.confirm_delivery.assert_called_once()
        kwargs = channel.basic_publish.call_args.kwargs
        self.assertTrue(kwargs["mandatory"])
        self.assertEqual(kwargs["properties"].delivery_mode, 2)
        self.assertTrue(kwargs["properties"].message_id)

    @patch("lab.rabbit_connection")
    def test_oversized_publish_is_rejected_without_connecting(self, connect):
        with self.assertRaises(SystemExit):
            lab.main(["publish", "x" * 4097])
        connect.assert_not_called()

    @patch("lab.rabbit_connection")
    def test_consume_acknowledges_after_processing(self, connect):
        channel = connect.return_value.__enter__.return_value.channel.return_value
        method = MagicMock(delivery_tag=42)
        props = MagicMock(message_id="job-1")
        channel.basic_get.return_value = (method, props, b"hello")
        lab.main(["consume"])
        channel.basic_ack.assert_called_once_with(42)
        channel.basic_nack.assert_not_called()

    @patch("lab.rabbit_connection")
    def test_bad_message_is_dead_lettered(self, connect):
        channel = connect.return_value.__enter__.return_value.channel.return_value
        channel.basic_get.return_value = (MagicMock(delivery_tag=42), MagicMock(message_id=""), b"hello")
        with self.assertRaises(ValueError):
            lab.main(["consume"])
        channel.basic_nack.assert_called_once_with(42, requeue=False)
        channel.basic_ack.assert_not_called()

    @patch("lab.rabbit_connection")
    @patch("builtins.print", side_effect=OSError("output unavailable"))
    def test_failed_processing_is_requeued(self, _print, connect):
        channel = connect.return_value.__enter__.return_value.channel.return_value
        channel.basic_get.return_value = (MagicMock(delivery_tag=42), MagicMock(message_id="job-1"), b"hello")
        with self.assertRaises(OSError):
            lab.main(["consume"])
        channel.basic_nack.assert_called_once_with(42, requeue=True)


if __name__ == "__main__":
    unittest.main()
