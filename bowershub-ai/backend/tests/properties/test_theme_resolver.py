"""
Property tests for the theme resolver.

Feature: bowershub-ai-enhancements

Properties exercised:

  P1 — Theme resolution priority is total and stable.
       Generate combinations of (user_override_id, platform_default_id,
       deleted_id_set, themes_owned_by_other_user). For every combination,
       the resolver returns the highest-priority theme that exists in the
       view AND is visible to the user, falling through to the built-in
       Dark Navy fallback when no priority entry qualifies. The resolver
       never raises.

  P13 — settings_json.theme_id is always resolvable or absent.
        For *any* value of `settings_json.theme_id` — including values
        that point at deleted, missing, or another-user-owned themes —
        the resolver still returns a valid theme shape rather than
        raising. The override is honored when (and only when) it points
        at a row that is present in the view and visible.

Validates: Requirements R1.3, R1.9, R3.5, R3.7, R3.8, R4.6
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from backend.services.theme_resolver import resolve


# ---------------------------------------------------------------------------
# Constants matching the resolver's contracts
# ---------------------------------------------------------------------------

EXPECTED_KEYS: frozenset[str] = frozenset(
    {"id", "name", "slug", "tokens_json", "is_default"}
)

# Synthetic fallback shape — matches `_FALLBACK_DARK_NAVY` in theme_resolver.
FALLBACK_SLUG = "dark-navy"
FALLBACK_NAME = "Dark Navy"


# ---------------------------------------------------------------------------
# Theme-row strategy
# ---------------------------------------------------------------------------
#
# Each generated theme has a unique id within a single example. We treat
# ids 1..MAX_THEMES as the universe of possible theme ids; whether each
# one shows up in the actual DB view is decided per-example.

MAX_THEMES = 6
THE_USER_ID = 100
OTHER_USER_IDS = (200, 300, 400)


def _theme_with_id(theme_id: int) -> st.SearchStrategy[dict[str, Any]]:
    """
    Build a strategy for a single theme row with the given id.

    A theme can be:
      - a built-in preset (is_preset=True, owner_id=None)
      - admin-published (is_preset=False, owner_id=None)
      - personally owned by THE_USER_ID
      - personally owned by some other user
    """
    flavor = st.sampled_from(
        ["preset", "admin", "owned_by_me", "owned_by_other"]
    )

    @st.composite
    def _strat(draw: st.DrawFn) -> dict[str, Any]:
        kind = draw(flavor)
        if kind == "preset":
            is_preset = True
            owner_id: Optional[int] = None
        elif kind == "admin":
            is_preset = False
            owner_id = None
        elif kind == "owned_by_me":
            is_preset = False
            owner_id = THE_USER_ID
        else:  # owned_by_other
            is_preset = False
            owner_id = draw(st.sampled_from(OTHER_USER_IDS))

        # Make slug uniqueness per (slug, owner_id) trivially unique by
        # mixing the id in. Real rows have arbitrary slugs.
        slug = f"theme-{theme_id}"
        # Special case: id=1 is the canonical Dark Navy preset so the
        # resolver's third-level fallback can find it. The strategy may
        # still demote it to a non-preset; that's fine — when it does,
        # the resolver should fall through to the synthetic fallback.
        if theme_id == 1 and kind == "preset":
            slug = FALLBACK_SLUG

        return {
            "id": theme_id,
            "name": f"Theme {theme_id}",
            "slug": slug,
            "is_preset": is_preset,
            "owner_id": owner_id,
            "tokens_json": {
                "background": "#101010",
                "surface": "#202020",
                "primary": "#303030",
                "accent": "#404040",
                "text": "#f0f0f0",
                "text_muted": "#a0a0a0",
                "border": "#505050",
                "danger": "#ff0000",
                "success": "#00ff00",
            },
        }

    return _strat()


@st.composite
def theme_population(draw: st.DrawFn) -> list[dict[str, Any]]:
    """A pool of distinct themes covering ids 1..N for some N in [0, MAX]."""
    n = draw(st.integers(min_value=0, max_value=MAX_THEMES))
    return [draw(_theme_with_id(i)) for i in range(1, n + 1)]


# ---------------------------------------------------------------------------
# Reference implementation — the spec, written directly.
# This is the oracle the resolver must match.
# ---------------------------------------------------------------------------


def _is_visible(theme: Mapping[str, Any], user_id: Optional[int]) -> bool:
    if theme.get("is_preset"):
        return True
    owner_id = theme.get("owner_id")
    if owner_id is None:
        return True
    return owner_id == user_id


def _find_by_id(
    themes: list[Mapping[str, Any]], theme_id: Any
) -> Optional[Mapping[str, Any]]:
    if theme_id is None:
        return None
    for t in themes:
        if t.get("id") == theme_id:
            return t
    return None


def _find_dark_navy_preset(
    themes: list[Mapping[str, Any]],
) -> Optional[Mapping[str, Any]]:
    for t in themes:
        if (
            t.get("slug") == FALLBACK_SLUG
            and t.get("is_preset")
            and t.get("owner_id") is None
        ):
            return t
    return None


def reference_resolve(
    user: Optional[Mapping[str, Any]],
    themes: list[Mapping[str, Any]],
    platform_default_id: Optional[int],
) -> dict[str, Any]:
    """
    Reproduce the documented priority order in plain Python.

    Matches `theme_resolver.resolve` exactly so the property test asserts
    semantic equivalence (and surfaces any drift between spec & impl).
    """
    user_id: Optional[int] = None
    override_id: Any = None
    if isinstance(user, Mapping):
        user_id = user.get("id")
        sj = user.get("settings_json")
        if isinstance(sj, Mapping):
            override_id = sj.get("theme_id")

    def _shape(theme: Mapping[str, Any]) -> dict[str, Any]:
        tid = theme.get("id")
        return {
            "id": tid,
            "name": theme.get("name"),
            "slug": theme.get("slug"),
            "tokens_json": theme.get("tokens_json"),
            "is_default": (
                platform_default_id is not None and tid == platform_default_id
            ),
        }

    # 1. user override
    override = _find_by_id(themes, override_id)
    if override is not None and _is_visible(override, user_id):
        return _shape(override)

    # 2. platform default
    default = _find_by_id(themes, platform_default_id)
    if default is not None and _is_visible(default, user_id):
        return _shape(default)

    # 3. dark-navy preset row in the view
    preset = _find_dark_navy_preset(themes)
    if preset is not None and _is_visible(preset, user_id):
        return _shape(preset)

    # 4. synthetic fallback
    return {
        "id": None,
        "name": FALLBACK_NAME,
        "slug": FALLBACK_SLUG,
        "tokens_json": {
            "background": "#0f0f1a",
            "surface": "#1a1a2e",
            "primary": "#6366f1",
            "accent": "#818cf8",
            "text": "#e5e7eb",
            "text_muted": "#94a3b8",
            "border": "#374151",
            "danger": "#ef4444",
            "success": "#22c55e",
        },
        "is_default": False,
    }


# ---------------------------------------------------------------------------
# Composite scenario strategy — picks (user, themes_table_view, default)
# ---------------------------------------------------------------------------


@st.composite
def scenario(draw: st.DrawFn):
    """
    Build a scenario:
      - a population of themes (ids 1..N)
      - a "deleted" subset (ids removed from the view passed to the resolver)
      - an override id (None | valid | deleted | unknown / garbage)
      - a platform default id (None | valid | deleted | unknown / garbage)

    The reference resolver and the implementation are run on the same
    `themes_table_view` (i.e., the population MINUS the deleted set), so
    both see the same world.
    """
    pool = draw(theme_population())
    pool_ids = [t["id"] for t in pool]

    # Pick a subset to "delete" — they're filtered out of the view.
    deleted_ids: set[int] = set(
        draw(
            st.lists(
                st.sampled_from(pool_ids) if pool_ids else st.nothing(),
                max_size=MAX_THEMES,
                unique=True,
            )
            if pool_ids
            else st.just([])
        )
    )

    visible_pool = [t for t in pool if t["id"] not in deleted_ids]

    # Choose ids for override / default.
    # Mix valid, deleted, missing-from-pool, and garbage non-int values.
    id_choices: list[st.SearchStrategy[Any]] = [st.none()]
    if pool_ids:
        id_choices.append(st.sampled_from(pool_ids))
    # Ids beyond the pool — guaranteed not to exist.
    id_choices.append(st.integers(min_value=MAX_THEMES + 1, max_value=10_000))
    # Garbage values — exercise total-ness.
    id_choices.append(
        st.one_of(
            st.text(max_size=8),
            st.floats(allow_nan=False, allow_infinity=False),
            st.lists(st.integers(), max_size=2),
            st.dictionaries(st.text(max_size=4), st.integers(), max_size=2),
        )
    )

    override_id = draw(st.one_of(*id_choices))
    default_id = draw(st.one_of(*id_choices))

    # The user dict — sometimes None, sometimes missing settings_json.
    user_shape = draw(
        st.sampled_from(["full", "no_settings", "empty_settings", "no_user"])
    )
    if user_shape == "no_user":
        user: Optional[dict[str, Any]] = None
    elif user_shape == "no_settings":
        user = {"id": THE_USER_ID}
    elif user_shape == "empty_settings":
        user = {"id": THE_USER_ID, "settings_json": {}}
    else:
        user = {
            "id": THE_USER_ID,
            "settings_json": {"theme_id": override_id},
        }

    return user, visible_pool, default_id


# ---------------------------------------------------------------------------
# P1 — priority order matches the reference implementation
# ---------------------------------------------------------------------------


@given(scenario())
@settings(
    max_examples=400,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
)
def test_p1_resolution_matches_reference(s) -> None:
    """For every scenario, resolve() agrees with the reference resolver."""
    user, visible_pool, default_id = s
    actual = resolve(user, visible_pool, default_id)
    expected = reference_resolve(user, visible_pool, default_id)
    assert actual == expected


# ---------------------------------------------------------------------------
# P1 — return shape is always the expected 5 keys
# ---------------------------------------------------------------------------


@given(scenario())
@settings(
    max_examples=200,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
)
def test_p1_return_shape_is_complete(s) -> None:
    """Every resolve() result has exactly the documented keys."""
    user, visible_pool, default_id = s
    result = resolve(user, visible_pool, default_id)

    assert isinstance(result, dict)
    assert set(result.keys()) == EXPECTED_KEYS
    assert isinstance(result["tokens_json"], dict)
    assert isinstance(result["is_default"], bool)


# ---------------------------------------------------------------------------
# P1 — is_default agrees with (returned id == platform_default_id)
# ---------------------------------------------------------------------------


@given(scenario())
@settings(
    max_examples=200,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
)
def test_p1_is_default_flag_matches_id(s) -> None:
    """is_default == (resolved id is non-None AND equals platform_default_id)."""
    user, visible_pool, default_id = s
    result = resolve(user, visible_pool, default_id)

    expected_flag = (
        default_id is not None
        and result["id"] is not None
        and result["id"] == default_id
    )
    assert result["is_default"] == expected_flag


# ---------------------------------------------------------------------------
# P1 — resolver never raises, even on garbage
# ---------------------------------------------------------------------------


@given(
    user=st.one_of(
        st.none(),
        st.dictionaries(st.text(max_size=4), st.integers(), max_size=3),
        st.fixed_dictionaries(
            {
                "id": st.one_of(st.none(), st.integers(), st.text(max_size=4)),
                "settings_json": st.one_of(
                    st.none(),
                    st.text(max_size=8),
                    st.dictionaries(
                        st.text(max_size=4), st.integers(), max_size=3
                    ),
                ),
            }
        ),
    ),
    themes_table_view=st.one_of(
        st.just([]),
        st.lists(
            st.dictionaries(st.text(max_size=4), st.integers(), max_size=4),
            max_size=4,
        ),
        # A list with a non-mapping junk entry mixed in.
        st.lists(
            st.one_of(
                st.dictionaries(
                    st.text(max_size=4), st.integers(), max_size=4
                ),
                st.text(max_size=4),
                st.none(),
                st.integers(),
            ),
            max_size=4,
        ),
    ),
    platform_default_id=st.one_of(
        st.none(),
        st.integers(),
        st.text(max_size=4),
        st.lists(st.integers(), max_size=2),
    ),
)
@settings(
    max_examples=300,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
)
def test_p1_never_raises_on_garbage(
    user: Any, themes_table_view: Any, platform_default_id: Any
) -> None:
    """resolve() is total: any garbage input still returns a valid shape."""
    result = resolve(user, themes_table_view, platform_default_id)
    assert isinstance(result, dict)
    assert set(result.keys()) == EXPECTED_KEYS


# ---------------------------------------------------------------------------
# P13 — `settings_json.theme_id` is always resolvable or absent
# ---------------------------------------------------------------------------
#
# Concretely: whatever value `settings_json.theme_id` holds, resolve()
# returns a complete, valid theme shape rather than raising. The override
# is honored *only* when its target row is present in the view and visible.


@given(
    pool=theme_population(),
    weird_theme_id=st.one_of(
        st.none(),
        st.integers(min_value=-1000, max_value=10_000),
        st.text(max_size=8),
        st.floats(allow_nan=True, allow_infinity=True),
        st.booleans(),
        st.lists(st.integers(), max_size=2),
        st.dictionaries(st.text(max_size=4), st.integers(), max_size=2),
    ),
    default_id=st.one_of(
        st.none(),
        st.integers(min_value=1, max_value=MAX_THEMES + 5),
    ),
)
@settings(
    max_examples=400,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
)
def test_p13_settings_theme_id_is_total(
    pool: list[dict[str, Any]],
    weird_theme_id: Any,
    default_id: Optional[int],
) -> None:
    """
    Property 13: any settings_json.theme_id (including absurd values, ids
    that point at non-existent or another-user-owned themes) leaves the
    resolver still able to return a valid theme shape — it must fall
    through, not raise.
    """
    user = {
        "id": THE_USER_ID,
        "settings_json": {"theme_id": weird_theme_id},
    }

    result = resolve(user, pool, default_id)

    # Total-ness: a complete shape comes back.
    assert isinstance(result, dict)
    assert set(result.keys()) == EXPECTED_KEYS

    # If the override resolved (i.e., id matches), it must have been a
    # row that's both present in the pool and visible to THE_USER_ID.
    if (
        result["id"] is not None
        and weird_theme_id == result["id"]
    ):
        match = next((t for t in pool if t.get("id") == result["id"]), None)
        assert match is not None
        assert _is_visible(match, THE_USER_ID)


# ---------------------------------------------------------------------------
# Targeted sanity examples (kept tiny; complement the properties)
# ---------------------------------------------------------------------------


_PRESET_DARK_NAVY = {
    "id": 1,
    "name": "Dark Navy",
    "slug": "dark-navy",
    "is_preset": True,
    "owner_id": None,
    "tokens_json": {"k": "v"},
}

_ADMIN_THEME = {
    "id": 2,
    "name": "Admin Forest",
    "slug": "forest",
    "is_preset": False,
    "owner_id": None,
    "tokens_json": {"k": "v"},
}

_MINE = {
    "id": 3,
    "name": "Mine",
    "slug": "mine",
    "is_preset": False,
    "owner_id": THE_USER_ID,
    "tokens_json": {"k": "v"},
}

_THEIRS = {
    "id": 4,
    "name": "Theirs",
    "slug": "theirs",
    "is_preset": False,
    "owner_id": OTHER_USER_IDS[0],
    "tokens_json": {"k": "v"},
}


def test_override_wins_when_present_and_visible() -> None:
    user = {"id": THE_USER_ID, "settings_json": {"theme_id": 3}}
    pool = [_PRESET_DARK_NAVY, _ADMIN_THEME, _MINE]
    result = resolve(user, pool, platform_default_id=2)
    assert result["id"] == 3
    assert result["is_default"] is False  # 3 != 2


def test_override_falls_through_when_owned_by_other() -> None:
    user = {"id": THE_USER_ID, "settings_json": {"theme_id": 4}}
    pool = [_PRESET_DARK_NAVY, _ADMIN_THEME, _THEIRS]
    result = resolve(user, pool, platform_default_id=2)
    # Override 4 is invisible → falls through to platform default 2.
    assert result["id"] == 2
    assert result["is_default"] is True


def test_override_falls_through_when_deleted() -> None:
    """The "deleted" condition is modeled by absence from the view."""
    user = {"id": THE_USER_ID, "settings_json": {"theme_id": 99}}
    pool = [_PRESET_DARK_NAVY, _ADMIN_THEME]
    result = resolve(user, pool, platform_default_id=2)
    assert result["id"] == 2


def test_falls_through_to_dark_navy_preset_row() -> None:
    pool = [_PRESET_DARK_NAVY]
    result = resolve(
        {"id": THE_USER_ID, "settings_json": {"theme_id": 99}},
        pool,
        platform_default_id=99,
    )
    assert result["id"] == 1
    assert result["slug"] == "dark-navy"
    assert result["is_default"] is False  # default id 99 ≠ 1


def test_falls_through_to_synthetic_fallback_when_view_empty() -> None:
    result = resolve(
        {"id": THE_USER_ID, "settings_json": {"theme_id": 1}},
        [],
        platform_default_id=1,
    )
    assert result["id"] is None
    assert result["slug"] == FALLBACK_SLUG
    assert result["name"] == FALLBACK_NAME
    assert result["is_default"] is False


@pytest.mark.parametrize(
    "user",
    [
        None,
        {},
        {"id": THE_USER_ID},
        {"id": THE_USER_ID, "settings_json": None},
        {"id": THE_USER_ID, "settings_json": {}},
        {"id": THE_USER_ID, "settings_json": "not-a-dict"},
    ],
)
def test_no_override_falls_through_to_default(user: Any) -> None:
    pool = [_PRESET_DARK_NAVY, _ADMIN_THEME]
    result = resolve(user, pool, platform_default_id=2)
    assert result["id"] == 2
    assert result["is_default"] is True
