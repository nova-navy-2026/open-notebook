"""Tests for the dangerous-content risk classifier.

Covers the pure logic — verdict parsing and the enable/severity gates. The
network call itself and the DB writes are exercised manually against the live
Gemma endpoint; here we only pin the behaviour that must never regress:
a malformed or unrecognised model reply must NOT produce a flag.
"""

import pytest

from open_notebook.safety.risk_classifier import (
    _parse_verdict,
    classifier_enabled,
)


class TestParseVerdict:
    def test_plain_negative(self):
        v = _parse_verdict('{"dangerous": false}')
        assert v is not None
        assert v.dangerous is False

    def test_full_positive(self):
        v = _parse_verdict(
            '{"dangerous": true, "categories": ["classified_leak"], '
            '"severity": "high", "reason": "motivo", "excerpt": "trecho"}'
        )
        assert v.dangerous is True
        assert v.categories == ["classified_leak"]
        assert v.severity == "high"
        assert v.reason == "motivo"
        assert v.excerpt == "trecho"

    def test_strips_markdown_fence(self):
        v = _parse_verdict(
            '```json\n{"dangerous": true, "categories": ["threat_violence"], '
            '"severity": "medium"}\n```'
        )
        assert v.dangerous is True
        assert v.categories == ["threat_violence"]

    def test_ignores_surrounding_prose(self):
        v = _parse_verdict(
            'Here is my analysis: {"dangerous": true, '
            '"categories": ["illegal_misconduct"], "severity": "low"} Hope that helps!'
        )
        assert v.dangerous is True
        assert v.severity == "low"

    def test_unknown_categories_are_dropped_and_downgraded(self):
        # A "dangerous" verdict with no recognisable category is untrustworthy —
        # it must not create an uncategorised flag.
        v = _parse_verdict('{"dangerous": true, "categories": ["something_else"]}')
        assert v.dangerous is False

    def test_unknown_severity_falls_back_to_medium(self):
        v = _parse_verdict(
            '{"dangerous": true, "categories": ["classified_leak"], '
            '"severity": "catastrophic"}'
        )
        assert v.severity == "medium"

    @pytest.mark.parametrize(
        "raw",
        ["", "not json at all", "{broken json", "[]", "null"],
    )
    def test_unparseable_returns_none(self, raw):
        # None means "no verdict" — the caller must not flag on this.
        assert _parse_verdict(raw) is None

    def test_mixed_categories_keeps_only_known(self):
        v = _parse_verdict(
            '{"dangerous": true, "categories": ["exfiltration_opsec", "bogus"], '
            '"severity": "high"}'
        )
        assert v.categories == ["exfiltration_opsec"]


class TestClassifierEnabled:
    def test_disabled_by_flag(self, monkeypatch):
        monkeypatch.setenv("GEMMA_BASE_URL", "http://example.invalid/v1")
        for value in ("0", "false", "no", "off"):
            monkeypatch.setenv("RISK_CLASSIFIER_ENABLED", value)
            assert classifier_enabled() is False

    def test_disabled_without_endpoint(self, monkeypatch):
        monkeypatch.setenv("RISK_CLASSIFIER_ENABLED", "1")
        monkeypatch.setenv("GEMMA_BASE_URL", "")
        assert classifier_enabled() is False

    def test_enabled_by_default_with_endpoint(self, monkeypatch):
        monkeypatch.delenv("RISK_CLASSIFIER_ENABLED", raising=False)
        monkeypatch.setenv("GEMMA_BASE_URL", "http://example.invalid/v1")
        assert classifier_enabled() is True
