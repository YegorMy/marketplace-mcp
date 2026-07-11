from marketplaces_mcp.core.matching import compute_offer_confidence, group_product_results
from marketplaces_mcp.core.models import ProductResult


def _product(title: str, price: float, marketplace: str) -> ProductResult:
    return ProductResult(marketplace=marketplace, title=title, url="https://example.com", price=price)


def test_compute_confidence_same_product_family():
    left = _product("Xiaomi Redmi 12 128GB black", 12300, "ozon")
    right = _product("Redmi 12 128 gb черный смартфон", 12400, "yandex_market")
    confidence = compute_offer_confidence(left, right)
    assert confidence > 0.5


def test_grouping_separates_different_products():
    offers = [
        _product("Xiaomi Redmi 12 128GB black", 12000, "ozon"),
        _product("Redmi 12 128 gb черный смартфон", 12100, "yandex_market"),
        _product("Набор для выпечки Brioche", 800, "ozon"),
    ]
    groups = group_product_results(offers, similarity_threshold=0.5)
    assert len(groups) == 2
    assert max(g.confidence for g in groups) >= 0.5
