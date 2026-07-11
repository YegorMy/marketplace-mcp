from marketplaces_mcp.core.normalize import parse_price, normalize_title


def test_parse_price_rub_with_spaces():
    assert parse_price("12 990 ₽") == 12990


def test_parse_price_comma_decimal():
    assert parse_price("1 234,56") == 1234.56


def test_normalize_title():
    assert (
        normalize_title("  Новый iPhone 14 PRO Max!!! ")
        == "новый iphone 14 pro max"
    )
