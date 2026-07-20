"""Tests for the internet-reachability probe.

This deployment runs on a closed LAN, so the critical property is that the
probe **fails closed**: anything short of a positive response must report
offline, so internet-only features stay disabled.
"""

import pytest

from open_notebook.utils import connectivity


@pytest.fixture(autouse=True)
def _clear_cache(monkeypatch):
    connectivity.reset_cache()
    monkeypatch.delenv("FORCE_OFFLINE", raising=False)
    monkeypatch.delenv("INTERNET_PROBE_URLS", raising=False)
    yield
    connectivity.reset_cache()


class TestForceOffline:
    @pytest.mark.parametrize("value", ["1", "true", "yes", "on", "TRUE"])
    def test_recognised_truthy_values(self, monkeypatch, value):
        monkeypatch.setenv("FORCE_OFFLINE", value)
        assert connectivity.force_offline() is True

    @pytest.mark.parametrize("value", ["0", "false", "no", "off", ""])
    def test_falsy_values(self, monkeypatch, value):
        monkeypatch.setenv("FORCE_OFFLINE", value)
        assert connectivity.force_offline() is False

    @pytest.mark.asyncio
    async def test_short_circuits_without_probing(self, monkeypatch):
        """FORCE_OFFLINE must not even attempt a network call."""
        called = False

        async def _boom():
            nonlocal called
            called = True
            return True

        monkeypatch.setattr(connectivity, "_probe_once", _boom)
        monkeypatch.setenv("FORCE_OFFLINE", "1")

        assert await connectivity.internet_available() is False
        assert called is False

    def test_cached_status_reports_offline_when_forced(self, monkeypatch):
        monkeypatch.setenv("FORCE_OFFLINE", "1")
        assert connectivity.cached_status() is False


class TestCaching:
    @pytest.mark.asyncio
    async def test_probe_runs_once_within_ttl(self, monkeypatch):
        calls = 0

        async def _probe():
            nonlocal calls
            calls += 1
            return True

        monkeypatch.setattr(connectivity, "_probe_once", _probe)
        monkeypatch.setenv("INTERNET_CHECK_TTL", "300")

        assert await connectivity.internet_available() is True
        assert await connectivity.internet_available() is True
        assert calls == 1

    @pytest.mark.asyncio
    async def test_force_bypasses_cache(self, monkeypatch):
        calls = 0

        async def _probe():
            nonlocal calls
            calls += 1
            return True

        monkeypatch.setattr(connectivity, "_probe_once", _probe)

        await connectivity.internet_available()
        await connectivity.internet_available(force=True)
        assert calls == 2

    @pytest.mark.asyncio
    async def test_offline_result_is_cached_too(self, monkeypatch):
        """A failed probe must not be retried on every request."""
        calls = 0

        async def _probe():
            nonlocal calls
            calls += 1
            return False

        monkeypatch.setattr(connectivity, "_probe_once", _probe)

        assert await connectivity.internet_available() is False
        assert await connectivity.internet_available() is False
        assert calls == 1


class TestProbeConfiguration:
    def test_probe_urls_default(self, monkeypatch):
        monkeypatch.delenv("INTERNET_PROBE_URLS", raising=False)
        assert connectivity._probe_urls() == list(connectivity._DEFAULT_PROBE_URLS)

    def test_probe_urls_override(self, monkeypatch):
        monkeypatch.setenv("INTERNET_PROBE_URLS", "http://a.local , http://b.local")
        assert connectivity._probe_urls() == ["http://a.local", "http://b.local"]

    @pytest.mark.parametrize(
        "raw,expected", [("5", 5.0), ("nonsense", 3.0), ("", 3.0)]
    )
    def test_timeout_falls_back_on_bad_value(self, monkeypatch, raw, expected):
        monkeypatch.setenv("INTERNET_PROBE_TIMEOUT", raw)
        assert connectivity._timeout() == expected

    @pytest.mark.asyncio
    async def test_unreachable_target_reports_offline(self, monkeypatch):
        """A real air-gap: nothing answers, so we must report offline."""
        # RFC5737-style unroutable address, tiny timeout.
        monkeypatch.setenv("INTERNET_PROBE_URLS", "http://192.0.2.1:9")
        monkeypatch.setenv("INTERNET_PROBE_TIMEOUT", "0.25")
        assert await connectivity.internet_available() is False
