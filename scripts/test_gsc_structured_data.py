"""Tests for gsc_structured_data."""


import gsc_structured_data
import pytest

# ---------- extract_jsonld ----------

def test_extract_jsonld_single_object():
    html = """<html><head>
<script type="application/ld+json">{"@type":"Product","name":"Foo"}</script>
</head></html>"""
    blocks = gsc_structured_data.extract_jsonld(html)
    assert blocks == [{"@type": "Product", "name": "Foo"}]


def test_extract_jsonld_array_of_objects():
    html = """<head>
<script type="application/ld+json">[{"@type":"Article","headline":"x"},{"@type":"Person","name":"y"}]</script>
</head>"""
    blocks = gsc_structured_data.extract_jsonld(html)
    assert {b["@type"] for b in blocks} == {"Article", "Person"}


def test_extract_jsonld_at_graph_unwrapping():
    html = """<head>
<script type="application/ld+json">{"@context":"https://schema.org",
"@graph":[{"@type":"Product","name":"a"},{"@type":"BreadcrumbList","itemListElement":[]}]}</script>
</head>"""
    blocks = gsc_structured_data.extract_jsonld(html)
    assert len(blocks) == 2
    assert blocks[0]["@type"] == "Product"
    assert blocks[1]["@type"] == "BreadcrumbList"


def test_extract_jsonld_handles_invalid_json():
    html = """<head>
<script type="application/ld+json">not json at all { broken</script>
</head>"""
    blocks = gsc_structured_data.extract_jsonld(html)
    assert len(blocks) == 1
    assert blocks[0]["_error"] == "invalid_json"


# ---------- validate_block ----------

def test_validate_block_product_pass():
    block = {"@type": "Product", "name": "Foo", "image": "https://x/img"}
    out = gsc_structured_data.validate_block(block)
    assert out["verdict"] == "unchecked"  # Product needs a snippet/merchant context.
    assert "Product.brand" in out["missing_recommended"]


def test_validate_block_product_full_pass():
    block = {
        "@type": "Product", "name": "Foo", "image": "https://x/img",
        "description": "d", "brand": "b", "offers": {"@type": "Offer"},
        "aggregateRating": {"@type": "AggregateRating"}, "review": [],
    }
    # `review` empty list still counts as present? Let's check our _has_field
    # - empty list returns False, so review is missing. That's fine, recommended.
    out = gsc_structured_data.validate_block(block)
    # Required all present; recommended `review` missing because empty list.
    assert out["verdict"] == "unchecked"


def test_validate_block_product_fail_missing_required():
    block = {"@type": "Product"}
    out = gsc_structured_data.validate_block(block)
    assert out["verdict"] == "fail"
    assert "Product.name" in out["missing_required"]
    assert "Product.image" not in out["missing_required"]


def test_validate_block_article_pass():
    block = {
        "@type": "Article", "headline": "h", "image": "x",
        "datePublished": "2026-01-01",
        "author": {"name": "n"}, "publisher": {"name": "p"},
        "dateModified": "2026-02-01",
    }
    out = gsc_structured_data.validate_block(block)
    assert out["verdict"] == "pass"


def test_validate_block_unknown_type_is_unchecked():
    block = {"@type": "WidgetWidget"}
    out = gsc_structured_data.validate_block(block)
    assert out["verdict"] == "unchecked"


def test_validate_block_no_type_is_untyped():
    block = {"name": "x"}
    out = gsc_structured_data.validate_block(block)
    assert out["verdict"] == "untyped"


def test_validate_block_invalid_passes_through():
    block = {"_error": "invalid_json"}
    out = gsc_structured_data.validate_block(block)
    assert out["verdict"] == "invalid"


# ---------- has_field nested ----------

def test_has_field_nested_dict():
    block = {"@type": "Article", "author": {"name": "x"}}
    assert gsc_structured_data._has_field(block, "author.name") is True


def test_has_field_nested_list_first_element():
    block = {"@type": "Article", "author": [{"name": "y"}]}
    assert gsc_structured_data._has_field(block, "author.name") is True


def test_has_field_empty_string_is_missing():
    assert gsc_structured_data._has_field({"name": ""}, "name") is False


# ---------- analyze_url (HTTP mocked) ----------

PRODUCT_HTML = """<html><head>
<script type="application/ld+json">{"@type":"Product","name":"Foo","image":"https://x/i.jpg"}</script>
</head></html>"""


def test_analyze_url_returns_summary(monkeypatch):
    monkeypatch.setattr(gsc_structured_data, "_fetch_html", lambda url: PRODUCT_HTML)
    out = gsc_structured_data.analyze_url("https://example.com/p/foo")
    assert out["block_count"] == 1
    assert out["types_found"] == ["Product"]


def test_analyze_url_fetch_failure(monkeypatch):
    monkeypatch.setattr(gsc_structured_data, "_fetch_html", lambda url: None)
    out = gsc_structured_data.analyze_url("https://example.com/p/foo")
    assert out["error"] == "fetch_failed"


# ---------- analyze_sitemap_sample ----------

def test_analyze_sitemap_sample_no_urls(monkeypatch):
    monkeypatch.setattr(gsc_structured_data, "_fetch_sitemap_urls", lambda site, limit, **kw: [])
    out = gsc_structured_data.analyze_sitemap_sample("example.com", sample_size=10)
    assert out["error"] == "no_sitemap_urls"


def test_analyze_sitemap_sample_rolls_up(monkeypatch):
    urls = [f"https://example.com/p/{i}" for i in range(5)]
    monkeypatch.setattr(gsc_structured_data, "_fetch_sitemap_urls",
                        lambda site, limit, **kw: urls)
    monkeypatch.setattr(gsc_structured_data, "_fetch_html", lambda url: PRODUCT_HTML)
    out = gsc_structured_data.analyze_sitemap_sample("example.com", sample_size=5)
    assert out["sample_size"] == 5
    rollup = out["rollup"]
    assert rollup["urls_analyzed"] == 5
    assert rollup["urls_with_jsonld"] == 5
    assert rollup["type_counts"]["Product"] == 5


@pytest.mark.parametrize("schema_type", ["FAQPage", "HowTo"])
def test_retired_type_is_not_a_pass_or_missing_field_failure(schema_type):
    result = gsc_structured_data.validate_block({"@type": schema_type})
    assert result["verdict"] == "unsupported"
    assert result["missing_required"] == []
    assert result["retired_types"] == [schema_type]


@pytest.mark.parametrize("schema_type", ["Article", "NewsArticle", "BlogPosting", "Organization"])
def test_recommended_fields_are_not_required(schema_type):
    result = gsc_structured_data.validate_block({"@type": schema_type})
    assert result["verdict"] == "partial"
    assert result["missing_required"] == []
    assert result["validation_scope"] == "top_level_presence_only"


def test_recipe_ingredients_and_instructions_are_recommended():
    result = gsc_structured_data.validate_block({"@type": "Recipe", "name": "Soup", "image": "x"})
    assert result["verdict"] == "partial"
    assert result["missing_required"] == []
    assert "Recipe.recipeInstructions" in result["missing_recommended"]


def test_course_provider_is_recommended_and_list_context_is_unchecked():
    result = gsc_structured_data.validate_block({"@type": "Course", "name": "X", "description": "Y"})
    assert result["verdict"] == "unchecked"
    assert result["missing_required"] == []
    assert "Course.provider" in result["missing_recommended"]


def test_aggregate_rating_review_count_does_not_false_fail():
    result = gsc_structured_data.validate_block({
        "@type": "AggregateRating", "ratingValue": 4, "reviewCount": 12,
    })
    assert result["missing_required"] == []
    assert result["verdict"] == "unchecked"  # Needs item/parent context.


def test_rollup_preserves_invalid_and_unsupported_and_fetch_failures():
    result = gsc_structured_data._rollup([
        {"error": "fetch_failed"},
        {"block_count": 2, "blocks": [{"verdict": "invalid"}, {"verdict": "unsupported"}]},
    ])
    assert result["urls_attempted"] == 2
    assert result["urls_analyzed"] == 1
    assert result["fetch_failures"] == 1
    assert result["block_verdicts"]["invalid"] == 1
    assert result["block_verdicts"]["unsupported"] == 1

def test_sitemap_namespaces_entities_duplicates_and_stable_sampling(monkeypatch):
    xml = """<s:urlset xmlns:s="http://www.sitemaps.org/schemas/sitemap/0.9">
    <s:url><s:loc>https://example.com/a?x=1&amp;y=2</s:loc></s:url>
    <s:url><s:loc>https://example.com/b</s:loc></s:url>
    <s:url><s:loc>https://example.com/b</s:loc></s:url>
    <s:url><s:loc>https://outside.test/a</s:loc></s:url></s:urlset>"""
    monkeypatch.setattr(gsc_structured_data, "_fetch_text", lambda _: xml)
    info = {}
    first = gsc_structured_data._fetch_sitemap_urls("example.com", 10, diagnostics=info)
    assert set(first) == {"https://example.com/a?x=1&y=2", "https://example.com/b"}
    assert gsc_structured_data._fetch_sitemap_urls("example.com", 10) == first
    assert info["discovered_urls"] == 2
    assert info["excluded_urls"] == 1
    assert info["exhaustive"] is False


def test_sitemap_traversal_is_bounded_and_prefix_is_retained(monkeypatch):
    from unittest.mock import MagicMock
    index = '<sitemapindex>' + ''.join(
        f'<sitemap><loc>https://example.com/child{i}.xml</loc></sitemap>' for i in range(20)) + '</sitemapindex>'
    fetch = MagicMock(side_effect=lambda url: index if url.endswith('sitemap.xml') else
        '<urlset><url><loc>https://example.com/shop/a</loc></url>'
        '<url><loc>https://example.com/outside</loc></url></urlset>')
    monkeypatch.setattr(gsc_structured_data, "_fetch_text", fetch)
    result = gsc_structured_data._fetch_sitemap_urls("https://example.com/shop/", 10)
    assert result == ["https://example.com/shop/a"]
    assert fetch.call_count == 6
    assert fetch.call_args_list[0].args[0] == "https://example.com/shop/sitemap.xml"


@pytest.mark.parametrize("xml", ["<urlset>", '<!DOCTYPE urlset [<!ENTITY x "hi">]><urlset/>'])
def test_invalid_sitemaps_are_disclosed(monkeypatch, xml):
    monkeypatch.setattr(gsc_structured_data, "_fetch_text", lambda _: xml)
    result = gsc_structured_data.analyze_sitemap_sample("example.com")
    assert result["error"] == "no_sitemap_urls"
    assert result["sampling"]["sitemap_requests"] == 2
    assert all(x["error"] == "invalid_sitemap" for x in result["sampling"]["issues"])


@pytest.mark.parametrize("limit", [0, -1, 101, True])
def test_sample_limits_fail_before_fetch(monkeypatch, limit):
    monkeypatch.setattr(gsc_structured_data, "_fetch_text", lambda _: pytest.fail("no fetch"))
    with pytest.raises(ValueError, match="between 1 and 100"):
        gsc_structured_data.analyze_sitemap_sample("example.com", sample_size=limit)

def test_prefix_without_slash_does_not_include_host_suffix(monkeypatch):
    monkeypatch.setattr(gsc_structured_data, "_fetch_text", lambda _: '<urlset>'
        '<url><loc>https://example.com.evil.test/a</loc></url>'
        '<url><loc>https://example.com/a</loc></url></urlset>')
    assert gsc_structured_data._fetch_sitemap_urls("https://example.com", 10) == ["https://example.com/a"]
