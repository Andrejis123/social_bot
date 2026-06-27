"""Tests for synthesis artifact save/load and CategorySynthesis serialization.

Covers:
- save_synthesis_artifact: inserts row via Supabase (mocked client)
- load_latest_synthesis_artifact: returns blob or None, ordered by created_at desc
- CategorySynthesis.to_dict() / from_dict() round-trip and edge cases
- PROMPT_VERSIONS required keys
- _build_report with reuse_synthesis=True/False (synthesize/save call behaviour)

All Supabase access and LLM calls are mocked. No live APIs are touched.
"""
from __future__ import annotations

from collections import OrderedDict
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

import social_bot.reports.renderer as renderer_mod
from social_bot.reports.data import AccountData, Period, PostRow, ReportData
from social_bot.reports.synthesis import PROMPT_VERSIONS, CategorySynthesis, ClusterItem
from social_bot.storage.synthesis import (
    load_latest_synthesis_artifact,
    save_synthesis_artifact,
)

# ─────────────────────────────────────────────────────────────────────
# Shared helpers
# ─────────────────────────────────────────────────────────────────────


def _make_cluster_item(**kw) -> ClusterItem:
    defaults = dict(
        title="Test Campaign",
        narrative="Brand promoted the test campaign.",
        best_post_id="post-1",
        post_ids=["post-1", "post-2"],
    )
    return ClusterItem(**{**defaults, **kw})


def _make_category_synthesis(**kw) -> CategorySynthesis:
    defaults = dict(
        category="Events",
        category_narrative="Brand ran several events this month.",
        items=[_make_cluster_item()],
    )
    return CategorySynthesis(**{**defaults, **kw})


def _make_period() -> Period:
    return Period(
        start=datetime(2026, 4, 1, tzinfo=UTC),
        end=datetime(2026, 5, 1, tzinfo=UTC),
        label="April 2026",
    )


def _make_post(**kw) -> PostRow:
    defaults = dict(
        id="post-1",
        platform_post_id="p1",
        posted_at=datetime(2026, 4, 1, tzinfo=UTC),
        post_type="image",
        caption="Test caption",
        ai_category="Events",
        ai_description="A product photo.",
        like_count=10,
        comment_count=1,
        hero_image_path=None,
    )
    return PostRow(**{**defaults, **kw})


def _make_report_data(handle: str = "testhandle") -> ReportData:
    post = _make_post()
    account = AccountData(
        handle=handle,
        platform="instagram",
        account_id="acc-1",
        posts_by_category=OrderedDict({"Events": [post]}),
        stories_by_category=OrderedDict(),
        intro_previews=[],
        total_posts=1,
        total_reels=0,
        total_stories=0,
        total_likes=10,
        total_comments=1,
    )
    return ReportData(
        client_slug="test-client",
        client_name="Test Client",
        period=_make_period(),
        accounts=[account],
    )


# ─────────────────────────────────────────────────────────────────────
# 1. PROMPT_VERSIONS required keys
# ─────────────────────────────────────────────────────────────────────


def test_prompt_versions_has_required_keys():
    assert {"pass0", "pass1", "pass2", "page"} <= set(PROMPT_VERSIONS.keys())


def test_prompt_versions_values_are_strings():
    for key, val in PROMPT_VERSIONS.items():
        assert isinstance(val, str), f"PROMPT_VERSIONS[{key!r}] is not a string"
        assert val, f"PROMPT_VERSIONS[{key!r}] is empty"


# ─────────────────────────────────────────────────────────────────────
# 2. CategorySynthesis.to_dict() / from_dict() round-trip
# ─────────────────────────────────────────────────────────────────────


def test_category_synthesis_round_trip():
    original = _make_category_synthesis()
    restored = CategorySynthesis.from_dict(original.to_dict())

    assert restored.category == original.category
    assert restored.category_narrative == original.category_narrative
    assert len(restored.items) == len(original.items)
    r_item, o_item = restored.items[0], original.items[0]
    assert r_item.title == o_item.title
    assert r_item.narrative == o_item.narrative
    assert r_item.best_post_id == o_item.best_post_id
    assert r_item.post_ids == o_item.post_ids


def test_category_synthesis_to_dict_shape():
    d = _make_category_synthesis().to_dict()
    assert set(d) >= {"category", "category_narrative", "items"}
    item = d["items"][0]
    assert set(item) >= {"title", "narrative", "best_post_id", "post_ids"}


def test_category_synthesis_round_trip_empty_items():
    synth = CategorySynthesis(category="Events", category_narrative="", items=[])
    restored = CategorySynthesis.from_dict(synth.to_dict())
    assert restored.category == "Events"
    assert restored.category_narrative == ""
    assert restored.items == []


def test_category_synthesis_round_trip_multiple_items():
    synth = CategorySynthesis(
        category="Collaborations",
        category_narrative="Brand partnered with two firms.",
        items=[
            _make_cluster_item(title="Collab A", post_ids=["post-1"]),
            _make_cluster_item(title="Collab B", post_ids=["post-2", "post-3"]),
        ],
    )
    restored = CategorySynthesis.from_dict(synth.to_dict())
    assert len(restored.items) == 2
    assert restored.items[0].title == "Collab A"
    assert restored.items[1].title == "Collab B"
    assert restored.items[1].post_ids == ["post-2", "post-3"]


# ─────────────────────────────────────────────────────────────────────
# Regression edge cases: from_dict robustness
# ─────────────────────────────────────────────────────────────────────


def test_from_dict_missing_top_key_raises():
    """Missing required top-level key must raise KeyError, not silently corrupt."""
    d = _make_category_synthesis().to_dict()
    del d["category"]
    with pytest.raises(KeyError):
        CategorySynthesis.from_dict(d)


def test_from_dict_missing_narrative_raises():
    d = _make_category_synthesis().to_dict()
    del d["category_narrative"]
    with pytest.raises(KeyError):
        CategorySynthesis.from_dict(d)


def test_from_dict_missing_items_raises():
    d = _make_category_synthesis().to_dict()
    del d["items"]
    with pytest.raises(KeyError):
        CategorySynthesis.from_dict(d)


def test_from_dict_missing_item_field_raises():
    """Missing required field inside an item must raise KeyError."""
    d = _make_category_synthesis().to_dict()
    del d["items"][0]["title"]
    with pytest.raises(KeyError):
        CategorySynthesis.from_dict(d)


def test_from_dict_extra_top_keys_ignored():
    """Extra unexpected top-level keys must be silently ignored, not cause errors."""
    d = _make_category_synthesis().to_dict()
    d["future_field"] = "some value"
    restored = CategorySynthesis.from_dict(d)
    assert restored.category == "Events"


def test_from_dict_extra_item_keys_ignored():
    """Extra unexpected keys inside an item dict must be silently ignored."""
    d = _make_category_synthesis().to_dict()
    d["items"][0]["extra_key"] = 42
    restored = CategorySynthesis.from_dict(d)
    assert restored.items[0].title == "Test Campaign"


# ─────────────────────────────────────────────────────────────────────
# 3. save_synthesis_artifact
# ─────────────────────────────────────────────────────────────────────


def test_save_synthesis_artifact_inserts_row(monkeypatch):
    mock_sb = MagicMock()
    monkeypatch.setattr("social_bot.storage.synthesis.get_supabase", lambda: mock_sb)

    save_synthesis_artifact(
        client_slug="testclient",
        period_label="April 2026",
        platform="instagram",
        model="gemini-2.5-flash",
        prompt_versions={"pass0": "v3"},
        artifact={"handle1": {"Events": {}}},
    )

    mock_sb.table.assert_called_once_with("synthesis_artifacts")
    table = mock_sb.table.return_value
    table.insert.assert_called_once()
    inserted = table.insert.call_args[0][0]
    assert inserted["client_slug"] == "testclient"
    assert inserted["period_label"] == "April 2026"
    assert inserted["platform"] == "instagram"
    assert inserted["model"] == "gemini-2.5-flash"
    assert inserted["prompt_versions"] == {"pass0": "v3"}
    assert inserted["artifact"] == {"handle1": {"Events": {}}}
    table.insert.return_value.execute.assert_called_once()


def test_save_synthesis_artifact_calls_execute(monkeypatch):
    """The insert must be executed (not just built)."""
    mock_sb = MagicMock()
    monkeypatch.setattr("social_bot.storage.synthesis.get_supabase", lambda: mock_sb)

    save_synthesis_artifact(
        client_slug="c",
        period_label="P",
        platform="instagram",
        model="m",
        prompt_versions={},
        artifact={},
    )

    mock_sb.table.return_value.insert.return_value.execute.assert_called_once()


# ─────────────────────────────────────────────────────────────────────
# 4. load_latest_synthesis_artifact
# ─────────────────────────────────────────────────────────────────────


def _sb_returning(rows: list[dict]) -> MagicMock:
    """Build a fake Supabase client whose chained query returns `rows`."""
    mock_sb = MagicMock()
    # The query chain: .table().select().eq().eq().eq().order().limit().execute()
    chain = MagicMock()
    mock_sb.table.return_value.select.return_value = chain
    chain.eq.return_value = chain
    chain.order.return_value = chain
    chain.limit.return_value = chain
    chain.execute.return_value.data = rows
    return mock_sb, chain


def test_load_latest_synthesis_artifact_returns_blob(monkeypatch):
    artifact = {"handle": {"Events": {"category": "Events"}}}
    mock_sb, _ = _sb_returning([{"artifact": artifact}])
    monkeypatch.setattr("social_bot.storage.synthesis.get_supabase", lambda: mock_sb)

    result = load_latest_synthesis_artifact(
        client_slug="testclient",
        period_label="April 2026",
        platform="instagram",
    )

    assert result == artifact


def test_load_latest_synthesis_artifact_returns_none_when_empty(monkeypatch):
    mock_sb, _ = _sb_returning([])
    monkeypatch.setattr("social_bot.storage.synthesis.get_supabase", lambda: mock_sb)

    result = load_latest_synthesis_artifact(
        client_slug="testclient",
        period_label="April 2026",
        platform="instagram",
    )

    assert result is None


def test_load_latest_synthesis_artifact_orders_desc(monkeypatch):
    """Query must use order('created_at', desc=True) to fetch the most recent row."""
    mock_sb, chain = _sb_returning([{"artifact": {}}])
    monkeypatch.setattr("social_bot.storage.synthesis.get_supabase", lambda: mock_sb)

    load_latest_synthesis_artifact(
        client_slug="testclient",
        period_label="April 2026",
        platform="instagram",
    )

    chain.order.assert_called_once_with("created_at", desc=True)


def test_load_latest_synthesis_artifact_limits_to_one(monkeypatch):
    """Query must limit to 1 row so only the most recent is fetched."""
    mock_sb, chain = _sb_returning([{"artifact": {}}])
    monkeypatch.setattr("social_bot.storage.synthesis.get_supabase", lambda: mock_sb)

    load_latest_synthesis_artifact(
        client_slug="testclient",
        period_label="April 2026",
        platform="instagram",
    )

    chain.limit.assert_called_once_with(1)


def test_load_latest_synthesis_artifact_returns_first_row_only(monkeypatch):
    """With multiple rows, only the artifact from data[0] (the most recent) is returned."""
    newest = {"handle": {"new": "data"}}
    older = {"handle": {"old": "data"}}
    mock_sb, _ = _sb_returning([{"artifact": newest}, {"artifact": older}])
    monkeypatch.setattr("social_bot.storage.synthesis.get_supabase", lambda: mock_sb)

    result = load_latest_synthesis_artifact(
        client_slug="testclient",
        period_label="April 2026",
        platform="instagram",
    )

    assert result == newest


# ─────────────────────────────────────────────────────────────────────
# 5. _build_report: reuse_synthesis=True / False behaviour
# ─────────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_renderer(monkeypatch, tmp_path):
    """Patch all heavy renderer dependencies so _build_report tests are fast.

    Returns tmp_path as the out_dir for the caller to pass to _build_report.
    """
    report_data = _make_report_data()
    mock_brand = MagicMock()
    mock_brand.hero_path = None
    mock_synth = _make_category_synthesis()
    mock_settings = MagicMock()
    mock_settings.gemini_model = "gemini-2.5-flash"
    mock_prs = MagicMock()

    monkeypatch.setattr(renderer_mod, "load_report_data", lambda *a, **k: report_data)
    monkeypatch.setattr(renderer_mod, "Brand", MagicMock(load=MagicMock(return_value=mock_brand)))
    monkeypatch.setattr(renderer_mod, "get_settings", lambda: mock_settings)
    monkeypatch.setattr(renderer_mod, "Presentation", MagicMock(return_value=mock_prs))
    monkeypatch.setattr(renderer_mod, "draw_cover", MagicMock())
    monkeypatch.setattr(renderer_mod, "draw_intro", MagicMock())
    monkeypatch.setattr(renderer_mod, "draw_account_overview", MagicMock())
    monkeypatch.setattr(renderer_mod, "draw_category_page", MagicMock())
    monkeypatch.setattr(renderer_mod, "draw_account_summary", MagicMock())
    monkeypatch.setattr(renderer_mod, "draw_additional_data", MagicMock())
    monkeypatch.setattr(renderer_mod, "synthesize_category", MagicMock(return_value=mock_synth))
    monkeypatch.setattr(renderer_mod, "synthesize_page_narrative", MagicMock(return_value=""))
    monkeypatch.setattr(renderer_mod, "save_synthesis_artifact", MagicMock())
    monkeypatch.setattr(renderer_mod, "load_latest_synthesis_artifact", MagicMock(return_value=None))

    return tmp_path


def test_build_report_reuse_synthesis_raises_when_no_artifact(mock_renderer):
    """reuse_synthesis=True with no stored artifact must raise RuntimeError."""
    with pytest.raises(RuntimeError, match="No synthesis artifact found"):
        renderer_mod._build_report(
            "test-client",
            _make_period(),
            out_dir=mock_renderer,
            reuse_synthesis=True,
        )


def test_build_report_reuse_synthesis_calls_load(mock_renderer, monkeypatch):
    """reuse_synthesis=True must call load_latest_synthesis_artifact."""
    mock_load = MagicMock(return_value=None)
    monkeypatch.setattr(renderer_mod, "load_latest_synthesis_artifact", mock_load)

    with pytest.raises(RuntimeError):
        renderer_mod._build_report(
            "test-client",
            _make_period(),
            out_dir=mock_renderer,
            reuse_synthesis=True,
        )

    mock_load.assert_called_once_with(
        client_slug="test-client",
        period_label="April 2026",
        platform="instagram",
    )


def test_build_report_reuse_synthesis_does_not_call_synthesize(mock_renderer, monkeypatch):
    """reuse_synthesis=True with a valid artifact must NOT call synthesize_category."""
    artifact = {
        "testhandle": {
            "Events": {
                "category": "Events",
                "category_narrative": "Test narrative.",
                "items": [],
            }
        }
    }
    monkeypatch.setattr(
        renderer_mod, "load_latest_synthesis_artifact", MagicMock(return_value=artifact)
    )
    mock_synthesize = MagicMock()
    monkeypatch.setattr(renderer_mod, "synthesize_category", mock_synthesize)

    renderer_mod._build_report(
        "test-client",
        _make_period(),
        out_dir=mock_renderer,
        reuse_synthesis=True,
    )

    mock_synthesize.assert_not_called()


def test_build_report_reuse_synthesis_does_not_call_save(mock_renderer, monkeypatch):
    """reuse_synthesis=True must NOT call save_synthesis_artifact."""
    artifact = {
        "testhandle": {
            "Events": {
                "category": "Events",
                "category_narrative": "Test narrative.",
                "items": [],
            }
        }
    }
    monkeypatch.setattr(
        renderer_mod, "load_latest_synthesis_artifact", MagicMock(return_value=artifact)
    )
    mock_save = MagicMock()
    monkeypatch.setattr(renderer_mod, "save_synthesis_artifact", mock_save)

    renderer_mod._build_report(
        "test-client",
        _make_period(),
        out_dir=mock_renderer,
        reuse_synthesis=True,
    )

    mock_save.assert_not_called()


def test_build_report_default_calls_synthesize_category(mock_renderer):
    """reuse_synthesis=False (default): synthesize_category must be called per category."""
    renderer_mod._build_report(
        "test-client",
        _make_period(),
        out_dir=mock_renderer,
        reuse_synthesis=False,
    )

    renderer_mod.synthesize_category.assert_called_once()


def test_build_report_default_calls_save_synthesis_artifact(mock_renderer):
    """reuse_synthesis=False: save_synthesis_artifact must be called after rendering."""
    renderer_mod._build_report(
        "test-client",
        _make_period(),
        out_dir=mock_renderer,
        reuse_synthesis=False,
    )

    renderer_mod.save_synthesis_artifact.assert_called_once()
    kw = renderer_mod.save_synthesis_artifact.call_args.kwargs
    assert kw["client_slug"] == "test-client"
    assert kw["period_label"] == "April 2026"
    assert kw["platform"] == "instagram"


def test_build_report_default_does_not_call_load_artifact(mock_renderer):
    """reuse_synthesis=False: load_latest_synthesis_artifact must NOT be called."""
    renderer_mod._build_report(
        "test-client",
        _make_period(),
        out_dir=mock_renderer,
        reuse_synthesis=False,
    )

    renderer_mod.load_latest_synthesis_artifact.assert_not_called()
