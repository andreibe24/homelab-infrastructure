import json

from django.test import SimpleTestCase


class HealthEndpointTests(SimpleTestCase):
    def test_health_returns_ok(self) -> None:
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        self.assertEqual(payload["status"], "ok")
        self.assertIn("protocol", payload)

    def test_healthz_alias(self) -> None:
        self.assertEqual(self.client.get("/healthz").status_code, 200)

    def test_info_reports_app_name(self) -> None:
        payload = json.loads(self.client.get("/api/info").content)
        self.assertEqual(payload["app"], "webapp-backend")

    def test_metrics_endpoint_exposed(self) -> None:
        response = self.client.get("/metrics")
        self.assertEqual(response.status_code, 200)
