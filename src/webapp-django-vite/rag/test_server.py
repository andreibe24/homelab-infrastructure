import unittest
from datetime import UTC, datetime
from unittest import mock
from unittest.mock import patch

from pgvector import Vector
from server import RagInputError, ask_campfire, retrieve_sources, validate_question


class QuestionTests(unittest.TestCase):
    def test_strips_valid_question_and_rejects_invalid_values(self):
        self.assertEqual(validate_question("  How did we deploy it?  "), "How did we deploy it?")
        for question in ("", " ", "x" * 1001, 42, None):
            with self.subTest(question=question), self.assertRaises(RagInputError):
                validate_question(question)


class RetrievalTests(unittest.TestCase):
    def test_uses_cosine_distance_to_rank_semantic_matches(self):
        now = datetime.now(UTC)
        source_row = (17, "camper", "We deployed Django with Helm.", now, 0.82)

        class FakeConnection:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def execute(self, query, parameters):
                self.query = query
                self.parameters = parameters
                return self

            def fetchall(self):
                return [source_row]

        connection = FakeConnection()
        model = mock.Mock()
        query_vector = mock.Mock()
        query_vector.tolist.return_value = [0.1, 0.2, 0.3]
        model.query_embed.return_value = iter([query_vector])
        with (
            patch("server.database_connection", return_value=connection),
            patch("server.register_vector"),
        ):
            sources = retrieve_sources("How was deployment done?", model)

        self.assertIn("embedding <=> %s", connection.query)
        self.assertIn("ORDER BY embedding <=> %s", connection.query)
        self.assertIsInstance(connection.parameters[0], Vector)
        self.assertEqual(sources[0]["id"], 17)
        self.assertEqual(sources[0]["createdAt"], now.isoformat())

    @patch("server.sync_index")
    @patch("server.retrieve_sources", return_value=[])
    @patch("server.generate_answer")
    def test_skips_generation_when_no_relevant_sources(self, generate, retrieve, sync):
        result = ask_campfire("What did we decide?", object())
        self.assertEqual(result["sources"], [])
        self.assertIn("No sufficiently relevant", result["text"])
        sync.assert_called_once()
        retrieve.assert_called_once()
        generate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
