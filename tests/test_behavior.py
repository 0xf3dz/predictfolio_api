import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import requests
from fastapi import HTTPException

from app import main as api_main
from app.services import polymarket, subgraph


class AddressValidationTests(unittest.TestCase):
    def test_normalize_user_address_accepts_hex_and_lowercases_it(self):
        address = "0x" + "AB" * 20

        self.assertEqual(api_main.normalize_user_address(address), address.lower())

    def test_fetch_rejects_non_hex_address_before_database_access(self):
        database = MagicMock()

        with self.assertRaises(HTTPException) as context:
            api_main.fetch_pnl_data("0x" + "g" * 40, False, database)

        self.assertEqual(context.exception.status_code, 400)
        database.query.assert_not_called()


class RateLimitTests(unittest.TestCase):
    def test_user_rate_limit_does_not_swallow_limit_response(self):
        redis_client = MagicMock()
        redis_client.get.return_value = str(api_main.RATE_LIMIT_PER_MINUTE)

        with patch.object(api_main.cache, "redis_client", redis_client):
            with self.assertRaises(HTTPException) as context:
                api_main.get_user_rate_limit(
                    SimpleNamespace(),
                    "0x" + "0" * 40,
                )

        self.assertEqual(context.exception.status_code, 429)
        redis_client.incr.assert_not_called()


class ExternalServiceFailureTests(unittest.TestCase):
    def test_subgraph_graphql_error_fails_instead_of_returning_partial_data(self):
        response = MagicMock()
        response.json.return_value = {"errors": [{"message": "unavailable"}]}
        session = MagicMock()
        session.post.return_value = response

        with patch.object(subgraph, "create_retry_session", return_value=session):
            with self.assertRaisesRegex(RuntimeError, "GraphQL errors"):
                subgraph.get_realized_pnl("0x" + "0" * 40)

    def test_polymarket_request_error_reaches_the_circuit_breaker_caller(self):
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("unavailable")

        with (
            patch.object(polymarket, "create_retry_session", return_value=session),
            patch("app.cache.cache.get", return_value=None),
        ):
            with self.assertRaisesRegex(RuntimeError, "request failed"):
                polymarket.get_unrealized_pnl("0x" + "0" * 40)


if __name__ == "__main__":
    unittest.main()
