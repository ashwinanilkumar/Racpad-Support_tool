"""
test_pricing_gaps.py — Unit tests for pricing_validation.find_pricing_gaps()

Mocks DB connections to test gap detection logic without live databases.

Run:
    python -m pytest tests/test_pricing_gaps.py -v
"""

from datetime import date
from unittest.mock import patch, MagicMock

import pytest

from pricing_validation import find_pricing_gaps


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

DB_CONFIGS = {
    "racdb": {"host": "localhost", "port": "5432", "dbname": "racdb",
              "user": "test", "password": "test"},
    "prcdb": {"host": "localhost", "port": "5432", "dbname": "prcdb",
              "user": "test", "password": "test"},
}

SAMPLE_PO_ITEMS = [
    {
        "purchase_order_number": "16391903",
        "store_number": "02714",
        "order_date": date(2026, 6, 30),
        "po_created_date": date(2026, 6, 30),
        "po_status": "RCV",
        "line_number": 1,
        "rms_item_master_id": 1001,
        "rms_item_number": 55001,
        "item_description": "Sofa Set",
        "model_number": "MDL-100",
        "quantity_ordered": 1,
    },
    {
        "purchase_order_number": "16391903",
        "store_number": "02714",
        "order_date": date(2026, 6, 30),
        "po_created_date": date(2026, 6, 30),
        "po_status": "RCV",
        "line_number": 2,
        "rms_item_master_id": 1002,
        "rms_item_number": 55002,
        "item_description": "TV Stand",
        "model_number": "MDL-200",
        "quantity_ordered": 2,
    },
]

SAMPLE_STORE_ZONES = [
    {"store_number": "02714", "zone_id": 10, "zone_number": "Z1", "zone_name": "South Central"},
]

SAMPLE_PRICES_ALL = [
    {"rms_item_number": 55001, "zone_id": 10, "zone_number": "Z1",
     "pricing_type": "PERMANENT", "weekly_rate_new": 25.99,
     "weekly_rate_used": 19.99, "term": 78, "cash_price_multiplier": 2.0,
     "forced_cash_price": None, "turn": None, "is_complete": True},
    {"rms_item_number": 55002, "zone_id": 10, "zone_number": "Z1",
     "pricing_type": "PERMANENT", "weekly_rate_new": 15.99,
     "weekly_rate_used": 11.99, "term": 78, "cash_price_multiplier": 2.0,
     "forced_cash_price": None, "turn": None, "is_complete": True},
]

SAMPLE_PRICES_MISSING_ONE = [
    {"rms_item_number": 55001, "zone_id": 10, "zone_number": "Z1",
     "pricing_type": "PERMANENT", "weekly_rate_new": 25.99,
     "weekly_rate_used": 19.99, "term": 78, "cash_price_multiplier": 2.0,
     "forced_cash_price": None, "turn": None, "is_complete": True},
    # Item 55002 is MISSING → gap
]

SAMPLE_PRICES_INCOMPLETE = [
    {"rms_item_number": 55001, "zone_id": 10, "zone_number": "Z1",
     "pricing_type": "PERMANENT", "weekly_rate_new": 25.99,
     "weekly_rate_used": 19.99, "term": 78, "cash_price_multiplier": 2.0,
     "forced_cash_price": None, "turn": None, "is_complete": True},
    {"rms_item_number": 55002, "zone_id": 10, "zone_number": "Z1",
     "pricing_type": "PERMANENT", "weekly_rate_new": 15.99,
     "weekly_rate_used": None, "term": None, "cash_price_multiplier": None,
     "forced_cash_price": None, "turn": None, "is_complete": False},
]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@patch("pricing_validation._connect")
@patch("pricing_validation._fetch")
def test_no_gaps_when_all_priced(mock_fetch, mock_connect):
    """All items have pricing → empty list returned."""
    mock_connect.return_value = MagicMock()
    mock_fetch.side_effect = [
        SAMPLE_PO_ITEMS,       # Step 1: PO items
        SAMPLE_STORE_ZONES,    # Step 2: store zones
        SAMPLE_PRICES_ALL,     # Step 3a: item_price
        [],                    # Step 3b: item_price_hierarchy
    ]

    gaps = find_pricing_gaps(
        check_date=date(2026, 6, 30),
        db_configs=DB_CONFIGS,
    )

    assert gaps == []


@patch("pricing_validation._connect")
@patch("pricing_validation._fetch")
def test_gap_detected_for_missing_item(mock_fetch, mock_connect):
    """Item 55002 has no item_price record → 1 MISSING gap."""
    mock_connect.return_value = MagicMock()
    mock_fetch.side_effect = [
        SAMPLE_PO_ITEMS,           # Step 1
        SAMPLE_STORE_ZONES,        # Step 2
        SAMPLE_PRICES_MISSING_ONE, # Step 3a (missing item 55002)
        [],                        # Step 3b: hierarchy (also missing)
    ]

    gaps = find_pricing_gaps(
        check_date=date(2026, 6, 30),
        db_configs=DB_CONFIGS,
    )

    assert len(gaps) == 1
    assert gaps[0]["rms_item_number"] == 55002
    assert gaps[0]["zone_id"] == 10
    assert "MISSING" in gaps[0]["gap_reason"]


@patch("pricing_validation._connect")
@patch("pricing_validation._fetch")
def test_gap_detected_for_incomplete_item(mock_fetch, mock_connect):
    """Item 55002 has item_price but required fields are NULL → INCOMPLETE gap."""
    mock_connect.return_value = MagicMock()
    mock_fetch.side_effect = [
        SAMPLE_PO_ITEMS,          # Step 1
        SAMPLE_STORE_ZONES,       # Step 2
        SAMPLE_PRICES_INCOMPLETE, # Step 3a (item 55002 incomplete)
        [],                       # Step 3b: hierarchy (also not priced)
    ]

    gaps = find_pricing_gaps(
        check_date=date(2026, 6, 30),
        db_configs=DB_CONFIGS,
    )

    assert len(gaps) == 1
    assert gaps[0]["rms_item_number"] == 55002
    assert "INCOMPLETE" in gaps[0]["gap_reason"]


@patch("pricing_validation._connect")
@patch("pricing_validation._fetch")
def test_no_po_items_returns_empty(mock_fetch, mock_connect):
    """No PO items on check_date → empty list."""
    mock_connect.return_value = MagicMock()
    mock_fetch.side_effect = [
        [],  # Step 1: no items
    ]

    gaps = find_pricing_gaps(
        check_date=date(2026, 6, 30),
        db_configs=DB_CONFIGS,
    )

    assert gaps == []


@patch("pricing_validation._connect")
@patch("pricing_validation._fetch")
def test_no_zone_assigned(mock_fetch, mock_connect):
    """Store has no zone → gap with 'No pricing zone assigned' reason."""
    mock_connect.return_value = MagicMock()
    mock_fetch.side_effect = [
        SAMPLE_PO_ITEMS,  # Step 1
        [],               # Step 2: no zones
    ]

    gaps = find_pricing_gaps(
        check_date=date(2026, 6, 30),
        db_configs=DB_CONFIGS,
    )

    assert len(gaps) == 2
    assert all(g["gap_reason"] == "Store has no active pricing zone" for g in gaps)


@patch("pricing_validation._connect")
@patch("pricing_validation._fetch")
def test_store_filter_applied(mock_fetch, mock_connect):
    """Filter by store is pushed to SQL; mock simulates DB returning only that store."""
    mock_connect.return_value = MagicMock()
    # Simulate the DB already filtering to only store 02714
    mock_fetch.side_effect = [
        SAMPLE_PO_ITEMS,       # Step 1: DB returns only store 02714 items
        SAMPLE_STORE_ZONES,    # Step 2
        SAMPLE_PRICES_ALL,     # Step 3a
        [],                    # Step 3b
    ]

    gaps = find_pricing_gaps(
        check_date=date(2026, 6, 30),
        db_configs=DB_CONFIGS,
        filters={"store": "02714"},
    )

    # All items priced → no gaps
    assert gaps == []


@patch("pricing_validation._connect")
@patch("pricing_validation._fetch")
def test_hierarchy_covers_missing_item_price(mock_fetch, mock_connect):
    """Item 55002 missing from item_price but present in hierarchy → NOT a gap."""
    mock_connect.return_value = MagicMock()
    hierarchy_row_55002 = {
        "rms_item_number": 55002,
        "zone_id": 10,
        "is_complete": True,
    }
    mock_fetch.side_effect = [
        SAMPLE_PO_ITEMS,           # Step 1
        SAMPLE_STORE_ZONES,        # Step 2
        SAMPLE_PRICES_MISSING_ONE, # Step 3a: item_price (55002 missing)
        [hierarchy_row_55002],     # Step 3b: hierarchy covers it
    ]

    gaps = find_pricing_gaps(
        check_date=date(2026, 6, 30),
        db_configs=DB_CONFIGS,
    )

    assert gaps == []


@patch("pricing_validation._connect")
def test_connection_error_raises(mock_connect):
    """Connection failure raises ConnectionError."""
    import psycopg2
    mock_connect.side_effect = ConnectionError("Cannot connect to racdb: connection refused")

    with pytest.raises(ConnectionError, match="Cannot connect to racdb"):
        find_pricing_gaps(check_date=date(2026, 6, 30), db_configs=DB_CONFIGS)
