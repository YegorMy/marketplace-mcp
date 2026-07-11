from .config import Settings, get_settings
from .models import (
    CompareResponse,
    OfferGroup,
    ProductResult,
    SearchResponse,
)
from .normalize import normalize_title, parse_price, token_set, extract_numeric_tokens
from .matching import compute_offer_confidence, group_product_results

__all__ = [
    "CompareResponse",
    "OfferGroup",
    "ProductResult",
    "SearchResponse",
    "Settings",
    "get_settings",
    "normalize_title",
    "parse_price",
    "token_set",
    "extract_numeric_tokens",
    "compute_offer_confidence",
    "group_product_results",
]
