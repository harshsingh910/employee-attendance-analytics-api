"""
Pagination Utilities (R10)
"""
from typing import Tuple


def get_skip_and_limit(page: int = 1, page_size: int = 20) -> Tuple[int, int]:
    """Calculate skip and limit offsets for 1-indexed pagination."""
    page = max(1, page)
    page_size = max(1, min(100, page_size))
    skip = (page - 1) * page_size
    return skip, page_size
