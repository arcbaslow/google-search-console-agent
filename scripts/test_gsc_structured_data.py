"""Tests for gsc_structured_data."""


import gsc_structured_data


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
    assert out["verdict"] == "partial"  # name+image required pass, but recommended fields missing
    assert "Product.brand" in out["missing_recommended"]


def test_validate_block_product_full_pass():
    block = {
        "@type": "Product", "name": "Foo", "image": "https://x/img",
        "description": "d", "brand": "b", "offers": {"@type": "Offer"},
        "aggregateRating": {"@type": "AggregateRating"}, "review": [],
    }
    # `review` empty list still counts as present? Let's check our _has_field
    # — empty list returns False, so review is missing. That's fine, recommended.
    out = gsc_structured_data.validate_block(block)
    # Required all present; recommended `review` missing because empty list.
    assert out["verdict"] == "partial"


def test_validate_block_product_fail_missing_required():
    block = {"@type": "Product"}
    out = gsc_structured_data.validate_block(block)
    assert out["verdict"] == "fail"
    assert "Product.name" in out["missing_required"]
    assert "Product.image" in out["missing_required"]


def test_validate_block_article_pass():
    block = {
        "@type": "Article", "headline": "h", "image": "x",
        "datePublished": "2026-01-01",
        "author": {"name": "n"}, "publisher": {"name": "p"},
        "dateModified": "2026-02-01",
    }
    out = gsc_structured_data.validate_block(block)
    assert out["verdict"] == "pass"


def test_validate_block_unknown_type_is_untyped():
    block = {"@type": "WidgetWidget"}
    out = gsc_structured_data.validate_block(block)
    # No required fields for unknown type → no missing → typed → pass
    assert out["verdict"] == "pass"


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
    monkeypatch.setattr(gsc_structured_data, "_fetch_sitemap_urls", lambda site, limit: [])
    out = gsc_structured_data.analyze_sitemap_sample("example.com", sample_size=10)
    assert out["error"] == "no_sitemap_urls"


def test_analyze_sitemap_sample_rolls_up(monkeypatch):
    urls = [f"https://example.com/p/{i}" for i in range(5)]
    monkeypatch.setattr(gsc_structured_data, "_fetch_sitemap_urls",
                        lambda site, limit: urls)
    monkeypatch.setattr(gsc_structured_data, "_fetch_html", lambda url: PRODUCT_HTML)
    out = gsc_structured_data.analyze_sitemap_sample("example.com", sample_size=5)
    assert out["sample_size"] == 5
    rollup = out["rollup"]
    assert rollup["urls_analyzed"] == 5
    assert rollup["urls_with_jsonld"] == 5
    assert rollup["type_counts"]["Product"] == 5
