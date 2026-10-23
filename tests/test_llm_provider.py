import unittest

from sentiment.llm_provider import (
    OPENROUTER_MODEL,
    OPENROUTER_URL,
    TOKENHARBOR_MODEL,
    TOKENHARBOR_URL,
    Provider,
    ProviderError,
    resolve_provider,
)
from sentiment.outlook import SCHEMA, request_body

KEYS = {"OPENROUTER_API_KEY": "or-key", "TOKENHARBOR_API_KEY": "thk_live_key"}
PRODUCTION = KEYS | {"GITHUB_ACTIONS": "true"}


class ProviderChoiceTests(unittest.TestCase):
    """Production pays OpenRouter; a developer's machine uses Token Harbor free."""

    def test_production_uses_openrouter(self):
        provider = resolve_provider(environ=PRODUCTION)
        self.assertEqual((provider.name, provider.url, provider.api_key), ("openrouter", OPENROUTER_URL, "or-key"))
        self.assertEqual(provider.model, OPENROUTER_MODEL)

    def test_production_refuses_token_harbor_however_it_is_asked_for(self):
        with self.assertRaises(ProviderError):
            resolve_provider("tokenharbor", environ=PRODUCTION)
        with self.assertRaises(ProviderError):
            resolve_provider(environ=PRODUCTION | {"OUTLOOK_PROVIDER": "tokenharbor"})

    def test_development_uses_token_harbor(self):
        provider = resolve_provider(environ=KEYS)
        self.assertEqual((provider.name, provider.url, provider.api_key), ("tokenharbor", TOKENHARBOR_URL, "thk_live_key"))
        self.assertEqual(provider.model, TOKENHARBOR_MODEL)
        self.assertEqual(resolve_provider(environ=KEYS | {"TOKENHARBOR_MODEL": "other"}).model, "other")

    def test_development_without_a_free_key_does_not_fall_back_to_the_paid_one(self):
        with self.assertRaises(ProviderError) as raised:
            resolve_provider(environ={"OPENROUTER_API_KEY": "or-key"})
        self.assertIn("TOKENHARBOR_API_KEY", str(raised.exception))

    def test_development_can_ask_for_openrouter_by_name(self):
        self.assertEqual(resolve_provider("openrouter", environ=KEYS).name, "openrouter")
        self.assertEqual(resolve_provider(environ=KEYS | {"OUTLOOK_PROVIDER": "openrouter"}).name, "openrouter")

    def test_an_unknown_provider_is_refused(self):
        with self.assertRaises(ProviderError):
            resolve_provider("someone", environ=KEYS)

    def test_a_development_reading_is_stored_under_its_own_name(self):
        self.assertEqual(resolve_provider(environ=PRODUCTION).stored_model_name, OPENROUTER_MODEL)
        self.assertEqual(
            resolve_provider(environ=KEYS).stored_model_name, f"tokenharbor/{TOKENHARBOR_MODEL}"
        )


class RequestBodyTests(unittest.TestCase):
    MESSAGES = [{"role": "user", "content": "call"}]

    def test_openrouter_is_held_to_the_cheapest_provider_with_minimal_reasoning(self):
        body = request_body(Provider("openrouter", OPENROUTER_URL, "k", OPENROUTER_MODEL), self.MESSAGES)
        self.assertEqual(body["provider"]["sort"], "price")
        self.assertEqual(body["reasoning"], {"effort": "minimal"})
        self.assertIs(body["response_format"]["json_schema"]["schema"], SCHEMA)

    def test_token_harbor_is_sent_the_standard_fields_with_thinking_off(self):
        body = request_body(Provider("tokenharbor", TOKENHARBOR_URL, "k", TOKENHARBOR_MODEL), self.MESSAGES)
        self.assertEqual(
            set(body), {"model", "messages", "temperature", "max_tokens", "response_format", "thinking"}
        )
        # Token Harbor ignores OpenRouter's `reasoning` switch and thinks by default.
        self.assertEqual(body["thinking"], {"type": "disabled"})
        self.assertEqual(body["model"], TOKENHARBOR_MODEL)



class RateLimitTests(unittest.TestCase):
    class Response:
        def __init__(self, status, headers=None, error=None):
            self.status_code, self.headers, self.error = status, headers or {}, error

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f"HTTP {self.status_code}")

        def json(self):
            if self.error:
                return {"error": self.error}
            return {"choices": [{"message": {"content": '{"view": "neutral"}'}}], "usage": {}}

    def session(self, statuses):
        responses = iter(statuses)

        class Session:
            calls = 0

            def post(inner, *args, **kwargs):
                Session.calls += 1
                return next(responses)

        return Session()

    def test_a_rate_limited_request_waits_and_is_tried_again(self):
        from sentiment.outlook import _post

        session = self.session([self.Response(429, {"Retry-After": "7"}), self.Response(200)])
        waits = []
        parsed, _ = _post(session, Provider("tokenharbor", "u", "k", "m"), {}, 10, sleep=waits.append)
        self.assertEqual(parsed, {"view": "neutral"})
        self.assertEqual(waits, [7.0])

    def test_a_request_still_limited_after_the_retries_fails(self):
        from sentiment.outlook import RATE_LIMIT_RETRIES, _post

        session = self.session([self.Response(429)] * (RATE_LIMIT_RETRIES + 1))
        with self.assertRaises(RuntimeError):
            _post(session, Provider("tokenharbor", "u", "k", "m"), {}, 10, sleep=lambda wait: None)
        self.assertEqual(session.calls, RATE_LIMIT_RETRIES + 1)


    def test_a_spent_free_allowance_is_not_waited_out(self):
        from sentiment.outlook import _post

        spent = self.Response(429, {"Retry-After": "3600"}, {"code": "free_tier_limit_reached", "message": "weekly"})
        session = self.session([spent])
        waits = []
        from sentiment.outlook import QuotaSpentError

        with self.assertRaises(QuotaSpentError):
            _post(session, Provider("tokenharbor", "u", "k", "m"), {}, 10, sleep=waits.append)
        self.assertEqual((session.calls, waits), (1, []))


if __name__ == "__main__":
    unittest.main()
