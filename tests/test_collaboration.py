"""Unit tests for collaborative-notebook access rules.

These cover the pure logic in ``open_notebook.collaboration`` (no database):
effective access computation, eligibility validation, profile resolution and
the effective navy-corpus filter. Member directory is mocked via
``access_control.load_users``.
"""

from types import SimpleNamespace

import pytest

from open_notebook import collaboration as col
from open_notebook.exceptions import InvalidInputError


DIRECTORY = {
    "m24409": {"email": "a@marinha.pt", "departments": ["SI-DAGI"], "clearance_level": 2},
    "m24810": {"email": "b@marinha.pt", "departments": ["SI-DAGI"], "clearance_level": 3},
    "m25109": {"email": "c@marinha.pt", "departments": ["SI-DITIC"], "clearance_level": 2},
    "m2000": {
        "email": "multi@marinha.pt",
        "departments": ["SI-DAGI", "SI-DITIC"],
        "clearance_level": 4,
    },
}


@pytest.fixture(autouse=True)
def _mock_directory(monkeypatch):
    monkeypatch.setattr(
        "open_notebook.access_control.load_users", lambda *a, **k: DIRECTORY
    )


# --- resolve_profile --------------------------------------------------------
def test_resolve_profile_known_user():
    depts, clearance = col.resolve_profile("a@marinha.pt")
    assert depts == {"SI-DAGI"}
    assert clearance == 2


def test_resolve_profile_unknown_user_fails_closed():
    depts, clearance = col.resolve_profile("nobody@marinha.pt")
    assert depts == set()
    assert clearance == 0


# --- compute_effective_access ----------------------------------------------
def test_effective_access_min_clearance_and_intersection():
    profiles = [({"SI-DAGI", "X"}, 2), ({"SI-DAGI"}, 3)]
    clearance, depts = col.compute_effective_access(profiles)
    assert clearance == 2  # MIN
    assert depts == ["SI-DAGI"]  # INTERSECTION


def test_effective_access_empty_intersection():
    clearance, depts = col.compute_effective_access([({"A"}, 2), ({"B"}, 3)])
    assert clearance == 2
    assert depts == []


def test_effective_access_no_members():
    assert col.compute_effective_access([]) == (None, [])


# --- validate_can_add -------------------------------------------------------
def test_validate_can_add_same_department_ok():
    profile = col.validate_can_add(["a@marinha.pt"], "b@marinha.pt")
    assert profile[0] == {"SI-DAGI"}


def test_validate_can_add_disjoint_department_rejected():
    with pytest.raises(InvalidInputError):
        col.validate_can_add(["a@marinha.pt"], "c@marinha.pt")


def test_validate_can_add_user_without_department_rejected():
    with pytest.raises(InvalidInputError):
        col.validate_can_add(["a@marinha.pt"], "nobody@marinha.pt")


def test_validate_can_add_multi_department_user_keeps_intersection():
    # multi@ is in both SI-DAGI and SI-DITIC, so it can join an SI-DAGI group.
    profile = col.validate_can_add(["a@marinha.pt"], "multi@marinha.pt")
    assert "SI-DAGI" in profile[0]


# --- effective_navy_filter --------------------------------------------------
def test_effective_navy_filter_non_collaborative_returns_none():
    nb = SimpleNamespace(collaborative=False)
    assert col.effective_navy_filter(nb) is None


def test_effective_navy_filter_uses_effective_profile():
    nb = SimpleNamespace(
        collaborative=True, effective_clearance=2, effective_departments=["SI-DAGI"]
    )
    flt = col.effective_navy_filter(nb)
    must = flt["bool"]["must"]
    assert {"range": {"classification_level": {"lte": 2}}} in must
    # Departments appear in the should-clause; no individual user entity leaks in.
    should = next(m["bool"]["should"] for m in must if "bool" in m)
    entities = next(s["terms"]["allowed_entities"] for s in should if "terms" in s)
    assert "SI-DAGI" in entities
    assert "general" in entities


def test_effective_navy_filter_collaborative_uncomputed_fails_closed():
    nb = SimpleNamespace(
        collaborative=True, effective_clearance=None, effective_departments=None
    )
    flt = col.effective_navy_filter(nb)
    assert flt == {"bool": {"must_not": {"match_all": {}}}}
