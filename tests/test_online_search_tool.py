from nanobot.agent.tools.web import (
    OnlineSearchTool,
    _compose_online_search_query,
    _extract_duckduckgo_results,
    _map_recency_to_ddg_df,
    _normalize_site_filter,
)


def test_extract_duckduckgo_results_modern_markup() -> None:
    html = """
    <div class="results">
      <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2F">Example Domain</a>
      <a class="result__snippet">A sample snippet.</a>
    </div>
    """

    results = _extract_duckduckgo_results(html, limit=5)
    assert len(results) == 1
    assert results[0]["title"] == "Example Domain"
    assert results[0]["url"] == "https://example.com/"
    assert results[0]["snippet"] == "A sample snippet."


def test_extract_duckduckgo_results_lite_markup() -> None:
    html = """
    <table>
      <tr><td><a class="result-link" href="https://example.org/page">Example Org</a></td></tr>
    </table>
    """

    results = _extract_duckduckgo_results(html, limit=5)
    assert len(results) == 1
    assert results[0]["title"] == "Example Org"
    assert results[0]["url"] == "https://example.org/page"


def test_normalize_site_filter_accepts_domain_and_url() -> None:
    assert _normalize_site_filter("docs.python.org") == "docs.python.org"
    assert _normalize_site_filter("https://OpenAI.com/docs") == "openai.com"


def test_normalize_site_filter_rejects_invalid_host() -> None:
    assert _normalize_site_filter("bad host.com") is None
    assert _normalize_site_filter("-bad.com") is None


def test_compose_online_search_query_with_site() -> None:
    assert _compose_online_search_query("asyncio timeout", "docs.python.org") == "site:docs.python.org asyncio timeout"
    assert _compose_online_search_query("asyncio timeout", None) == "asyncio timeout"


def test_map_recency_to_ddg_df() -> None:
    assert _map_recency_to_ddg_df("day") == "d"
    assert _map_recency_to_ddg_df("week") == "w"
    assert _map_recency_to_ddg_df("month") == "m"
    assert _map_recency_to_ddg_df("year") == "y"
    assert _map_recency_to_ddg_df(None) is None


def test_online_search_tool_recency_enum_validation() -> None:
    tool = OnlineSearchTool()
    errors = tool.validate_params({"query": "python", "recency": "decade"})
    assert any("recency must be one of" in e for e in errors)
