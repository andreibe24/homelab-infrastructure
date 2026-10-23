import io
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import server


class MCPServerTests(unittest.TestCase):
    def test_authorization_requires_a_bearer_token(self):
        context = SimpleNamespace(headers={"authorization": "Basic credentials"})

        with self.assertRaises(ValueError):
            server._authorization(context)

    @patch("server.urlopen")
    def test_api_requests_forward_the_callers_token(self, urlopen):
        urlopen.return_value.__enter__.return_value = io.BytesIO(b'{"messages": []}')
        authorization = "".join(("Bear", "er test-token"))

        result = server._request_api("?limit=5", authorization)

        self.assertEqual(result, {"messages": []})
        request = urlopen.call_args.args[0]
        self.assertTrue(request.full_url.endswith("/?limit=5"))
        self.assertEqual(request.get_header("Authorization"), authorization)

    def test_holiday_tools_are_registered(self):
        tool_names = {tool.name for tool in server.server._tool_manager.list_tools()}

        self.assertEqual(
            tool_names,
            {"send-holidayExperience", "view-holidayExperiences"},
        )


if __name__ == "__main__":
    unittest.main()
