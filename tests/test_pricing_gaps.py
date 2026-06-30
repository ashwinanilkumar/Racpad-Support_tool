"""
test_pricing_gaps.py — Unit tests for pricing_validation.find_pricing_gaps()

Mocks DB connections to test gap detection logic without live databases.

Run:
    python -m pytest tests/test_pricing_gaps.py -v
"""

from datetime import date
from unittest.mock import patch, MagicMock, call

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
    {"rms_item_number": 55001, "zone_id": 10, "is_complete": True},
    {"rms_item_number": 55002, "zone_id": 10, "is_complete": True},
]

SAMPLE_PRICES_MISSING_ONE = [
    {"rms_item_number": 55001, "zone_id": 10, "is_complete": True},
    # Item 55002 is MISSING → gap
]

SAMPLE_PRICES_INCOMPLETE = [
    {"rms_item_number": 55001, "zone_id": 10, "is_complete": True},
    {"rms_item_number": 55002, "zone_id": 10, "is_complete": False},
]

# Hierarchy resolve result for both items
SAMPLE_HIERARCHY_RESOLVE = [
    {"rms_item_master_id": 1001, "rms_item_number": 55001,
     "rms_bracket_id": 201, "rms_subdepartment_id": 301, "rms_department_id": 401},
    {"rms_item_master_id": 1002, "rms_item_number": 55002,
     "rms_bracket_id": 201, "rms_subdepartment_id": 301, "rms_department_id": 401},
]


def _make_fetch_side_effect(step1, step2, step3a_results, hierarchy_resolve, level_results=None):
    """
    Build a side_effect function for _fetch that dispatches based on the SQL query.
    This handles the new two-phase 3b architecture where _fetch is called multiple
    times with different queries.

    level_results: list of results for L1, L2, L3, L4 queries (default: empty for all)
    """
    from queries import (
        PRICING_VALIDATION_PO_ITEMS,
        PRICING_VALIDATION_STORE_ZONES,
        PRICING_VALIDATION_EXISTING_PRICES,
        PRICING_VALIDATION_HIERARCHY_RESOLVE,
        PRICING_VALIDATION_HIERARCHY_L1_ITEM,
        PRICING_VALIDATION_HIERARCHY_L2_BRACKET,
        PRICING_VALIDATION_HIERARCHY_L3_SUBDEPT,
        PRICING_VALIDATION_HIERARCHY_L4_DEPT,
    )
    if level_results is None:
        level_results = [[], [], [], []]

    def _side_effect(conn, sql, params):
        sql_stripped = sql.strip()
        if sql_stripped == PRICING_VALIDATION_PO_ITEMS.strip():
            return step1
        elif sql_stripped == PRICING_VALIDATION_STORE_ZONES.strip():
            return step2
        elif sql_stripped == PRICING_VALIDATION_EXISTING_PRICES.strip():
            return step3a_results
        elif sql_stripped == PRICING_VALIDATION_HIERARCHY_RESOLVE.strip():
            return hierarchy_resolve
        elif sql_stripped == PRICING_VALIDATION_HIERARCHY_L1_ITEM.strip():
            return level_results[0]
        elif sql_stripped == PRICING_VALIDATION_HIERARCHY_L2_BRACKET.strip():
            return level_results[1]
        elif sql_stripped == PRICING_VALIDATION_HIERARCHY_L3_SUBDEPT.strip():
            return level_results[2]
        elif sql_stripped == PRICING_VALIDATION_HIERARCHY_L4_DEPT.strip():
            return level_results[3]
        return []

    return _side_effect


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@patch("pricing_validation._connect")
@patch("pricing_validation._fetch")
def test_no_gaps_when_all_priced(mock_fetch, mock_connect):
    """All items have pricing → empty list returned."""
    mock_connect.return_value = MagicMock()
    mock_fetch.side_effect = _make_fetch_side_effect(
        step1=SAMPLE_PO_ITEMS,
        step2=SAMPLE_STORE_ZONES,
        step3a_results=SAMPLE_PRICES_ALL,
        hierarchy_resolve=SAMPLE_HIERARCHY_RESOLVE,
    )

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
    mock_fetch.side_effect = _make_fetch_side_effect(
        step1=SAMPLE_PO_ITEMS,
        step2=SAMPLE_STORE_ZONES,
        step3a_results=SAMPLE_PRICES_MISSING_ONE,
        hierarchy_resolve=SAMPLE_HIERARCHY_RESOLVE,
    )

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
    mock_fetch.side_effect = _make_fetch_side_effect(
        step1=SAMPLE_PO_ITEMS,
        step2=SAMPLE_STORE_ZONES,
        step3a_results=SAMPLE_PRICES_INCOMPLETE,
        hierarchy_resolve=SAMPLE_HIERARCHY_RESOLVE,
    )

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
    mock_fetch.side_effect = _make_fetch_side_effect(
        step1=[],
        step2=[],
        step3a_results=[],
        hierarchy_resolve=[],
    )

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
    mock_fetch.side_effect = _make_fetch_side_effect(
        step1=SAMPLE_PO_ITEMS,
        step2=[],  # No zones
        step3a_results=[],
        hierarchy_resolve=[],
    )

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
    mock_fetch.side_effect = _make_fetch_side_effect(
        step1=SAMPLE_PO_ITEMS,
        step2=SAMPLE_STORE_ZONES,
        step3a_results=SAMPLE_PRICES_ALL,
        hierarchy_resolve=SAMPLE_HIERARCHY_RESOLVE,
    )

    gaps = find_pricing_gaps(
        check_date=date(2026, 6, 30),
        db_configs=DB_CONFIGS,
        filters={"store": "02714"},
    )

    assert gaps == []


@patch("pricing_validation._connect")
@patch("pricing_validation._fetch")
def test_hierarchy_covers_missing_item_price(mock_fetch, mock_connect):
    """Item 55002 missing from item_price but present in hierarchy → NOT a gap."""
    mock_connect.return_value = MagicMock()
    # L1 (item level) returns pricing for item 55002 via its rms_item_master_id=1002
    l1_result = [
        {"entity_id": 1002, "zone_id": 10,
         "key_names": ["WeeklyRateNew", "WeeklyRateUsed", "WeeklyTerm", "CashPriceMultiplier"]},
    ]
    mock_fetch.side_effect = _make_fetch_side_effect(
        step1=SAMPLE_PO_ITEMS,
        step2=SAMPLE_STORE_ZONES,
        step3a_results=SAMPLE_PRICES_MISSING_ONE,
        hierarchy_resolve=SAMPLE_HIERARCHY_RESOLVE,
        level_results=[l1_result, [], [], []],
    )

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
