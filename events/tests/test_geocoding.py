"""Tests for the Nominatim geocoding helper."""

import time
from unittest.mock import Mock, patch

import pytest
import requests

from events import geocoding


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Reset the module-level rate-limit clock before each test."""
    geocoding._last_call_at = 0.0
    yield
    geocoding._last_call_at = 0.0


def _mock_response(status_code=200, json_data=None, raise_http=False):
    resp = Mock()
    resp.status_code = status_code
    if raise_http:
        resp.raise_for_status.side_effect = requests.HTTPError("boom")
    else:
        resp.raise_for_status.return_value = None
    resp.json.return_value = json_data if json_data is not None else []
    return resp


class TestGeocodeSuccess:
    def test_returns_float_tuple_from_first_result(self):
        with patch("events.geocoding.requests.get") as m_get:
            m_get.return_value = _mock_response(
                json_data=[
                    {"lat": "55.6761", "lon": "12.5683"},
                    {"lat": "0", "lon": "0"},
                ]
            )
            result = geocoding.geocode("Copenhagen")
        assert result == (55.6761, 12.5683)

    def test_sends_user_agent_and_query(self, settings):
        settings.GEOCODING_USER_AGENT = "pleskal-test/1.0"
        with patch("events.geocoding.requests.get") as m_get:
            m_get.return_value = _mock_response(
                json_data=[{"lat": "1.0", "lon": "2.0"}]
            )
            geocoding.geocode("Dansehallerne, Copenhagen, Denmark")

        args, kwargs = m_get.call_args
        assert args[0] == geocoding.NOMINATIM_URL
        assert kwargs["headers"]["User-Agent"] == "pleskal-test/1.0"
        assert kwargs["params"]["q"] == "Dansehallerne, Copenhagen, Denmark"
        assert kwargs["params"]["format"] == "json"
        assert kwargs["params"]["limit"] == 1
        assert kwargs["timeout"] == geocoding.REQUEST_TIMEOUT_SECONDS


class TestGeocodeFailureModes:
    def test_empty_query_returns_none_without_request(self):
        with patch("events.geocoding.requests.get") as m_get:
            assert geocoding.geocode("") is None
        m_get.assert_not_called()

    def test_empty_results_returns_none(self):
        with patch("events.geocoding.requests.get") as m_get:
            m_get.return_value = _mock_response(json_data=[])
            assert geocoding.geocode("nowhere") is None

    def test_http_error_returns_none(self):
        with patch("events.geocoding.requests.get") as m_get:
            m_get.return_value = _mock_response(status_code=500, raise_http=True)
            assert geocoding.geocode("Copenhagen") is None

    def test_timeout_returns_none(self):
        with patch("events.geocoding.requests.get") as m_get:
            m_get.side_effect = requests.Timeout("slow")
            assert geocoding.geocode("Copenhagen") is None

    def test_connection_error_returns_none(self):
        with patch("events.geocoding.requests.get") as m_get:
            m_get.side_effect = requests.ConnectionError("offline")
            assert geocoding.geocode("Copenhagen") is None

    def test_invalid_json_returns_none(self):
        with patch("events.geocoding.requests.get") as m_get:
            resp = Mock()
            resp.raise_for_status.return_value = None
            resp.json.side_effect = ValueError("not json")
            m_get.return_value = resp
            assert geocoding.geocode("Copenhagen") is None

    def test_malformed_result_returns_none(self):
        with patch("events.geocoding.requests.get") as m_get:
            m_get.return_value = _mock_response(
                json_data=[{"not_lat": "x", "not_lon": "y"}]
            )
            assert geocoding.geocode("Copenhagen") is None


class TestRateLimit:
    def test_enforces_minimum_spacing_between_calls(self, monkeypatch):
        sleep_calls: list[float] = []

        def fake_sleep(seconds):
            sleep_calls.append(seconds)

        # Freeze monotonic so the first call sees a "recent" prior call.
        times = iter([100.0, 100.0, 100.0, 100.0])
        monkeypatch.setattr(geocoding.time, "monotonic", lambda: next(times))
        monkeypatch.setattr(geocoding.time, "sleep", fake_sleep)

        # Simulate a prior call that happened "just now".
        geocoding._last_call_at = 100.0

        with patch("events.geocoding.requests.get") as m_get:
            m_get.return_value = _mock_response(json_data=[])
            geocoding.geocode("Copenhagen")

        assert len(sleep_calls) == 1
        assert sleep_calls[0] == pytest.approx(geocoding.MIN_INTERVAL_SECONDS, abs=1e-6)

    def test_no_sleep_when_interval_already_elapsed(self, monkeypatch):
        sleep_calls: list[float] = []
        monkeypatch.setattr(geocoding.time, "sleep", lambda s: sleep_calls.append(s))
        # Far in the future: interval has passed.
        monkeypatch.setattr(geocoding.time, "monotonic", lambda: 10_000.0)
        geocoding._last_call_at = 0.0

        with patch("events.geocoding.requests.get") as m_get:
            m_get.return_value = _mock_response(json_data=[])
            geocoding.geocode("Copenhagen")

        assert sleep_calls == []

    def test_last_call_timestamp_updates(self, monkeypatch):
        monkeypatch.setattr(geocoding.time, "sleep", lambda s: None)
        monkeypatch.setattr(geocoding.time, "monotonic", lambda: 500.0)
        geocoding._last_call_at = 0.0

        with patch("events.geocoding.requests.get") as m_get:
            m_get.return_value = _mock_response(json_data=[])
            geocoding.geocode("Copenhagen")

        assert geocoding._last_call_at == 500.0


def test_rate_limit_does_not_exceed_policy_under_threads():
    """Sanity check: the rate limiter serialises requests."""
    call_times: list[float] = []

    def fake_get(*args, **kwargs):
        call_times.append(time.monotonic())
        return _mock_response(json_data=[{"lat": "1", "lon": "2"}])

    # Reduce the interval so the test stays fast but still proves the lock works.
    # The observed spacing between the mocked requests.get calls is slightly less
    # than MIN_INTERVAL_SECONDS because the first call's per-call overhead (cold
    # path) can exceed the second's. Use a generous interval with a small
    # tolerance to keep the test fast but non-flaky.
    interval = 0.1
    tolerance = 0.02
    with (
        patch("events.geocoding.MIN_INTERVAL_SECONDS", interval),
        patch("events.geocoding.requests.get", side_effect=fake_get),
    ):
        geocoding.geocode("a")
        geocoding.geocode("b")

    assert len(call_times) == 2
    assert call_times[1] - call_times[0] >= interval - tolerance
