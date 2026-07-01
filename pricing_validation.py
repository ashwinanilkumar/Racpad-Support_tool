"""
pricing_validation.py — Post-PO Pricing Gap Validator (Library Module)
======================================================================
Identifies PO line items that have no active pricing in prcadm.item_price
for the store's pricing zone.

Gap types:
  MISSING    — no item_price row for (rms_item_number, zone_id, any type)
  INCOMPLETE — row exists but required fields are NULL

Primary entry point:
    find_pricing_gaps(check_date, db_configs, filters) -> list[dict]

Also usable as a CLI:
    python pricing_validation.py                    # checks today's POs
    python pricing_validation.py --date 2026-06-28  # checks a specific date
"""

import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from typing import Optional

import psycopg2
import psycopg2.errors
import psycopg2.extras

from queries import (
    PRICING_VALIDATION_PO_ITEMS,
    PRICING_VALIDATION_STORE_ZONES,
    PRICING_VALIDATION_EXISTING_PRICES,
    PRICING_VALIDATION_HIERARCHY_RESOLVE,
    PRICING_VALIDATION_HIERARCHY_L1_ITEM,
    PRICING_VALIDATION_HIERARCHY_L2_BRACKET,
    PRICING_VALIDATION_HIERARCHY_L3_SUBDEPT,
    PRICING_VALIDATION_HIERARCHY_L4_DEPT,
    PRICING_VALIDATION_PRODUCT_PRICES,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

# Per-statement timeout (seconds) — applies per batch, not globally.
# Small batches should complete in <30s; this is a safety net.
STATEMENT_TIMEOUT_S = 90

# Batch sizes tuned for production safety:
#   - 3a (item_price): simpler query, can handle more items per batch
#   - 3b resolve: just resolving hierarchy IDs, very fast
#   - 3b levels: each level query is focused on one FK, small batches
BATCH_SIZE_3A = 100
BATCH_SIZE_3B_RESOLVE = 200
BATCH_SIZE_3B_LEVEL = 100
BATCH_SIZE_3C = 100

def _connect(config: dict, label: str):
    """Open a read-only psycopg2 connection from a config dict."""
    try:
        conn = psycopg2.connect(
            host=config["host"],
            port=int(config.get("port", 5432)),
            dbname=config["dbname"],
            user=config["user"],
            password=config.get("password", ""),
            connect_timeout=10,
            sslmode="prefer",
            options=f"-c statement_timeout={STATEMENT_TIMEOUT_S * 1000}",
        )
        conn.set_session(readonly=True, autocommit=True)
        return conn
    except psycopg2.OperationalError as exc:
        raise ConnectionError(f"Cannot connect to {label}: {exc}") from exc


def _fetch(conn, sql: str, params: dict) -> list[dict]:
    """Execute a parameterized query and return rows as dicts."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        return [dict(row) for row in cur.fetchall()]


def _batched(lst, size):
    """Yield successive chunks of `lst` of length `size`."""
    for i in range(0, len(lst), size):
        yield lst[i:i + size]


def _fetch_with_retry(conn, sql, params, array_key, batch_label="batch", max_retries=2):
    """
    Execute a query; on statement timeout, halve the array param and retry.
    This adaptive approach handles unexpectedly heavy item sets gracefully.
    """
    try:
        return _fetch(conn, sql, params)
    except psycopg2.errors.QueryCanceled:
        arr = params[array_key]
        if len(arr) <= 5 or max_retries <= 0:
            raise  # Cannot split further — genuine performance problem
        mid = len(arr) // 2
        logger.warning("%s timed out with %d items — splitting in half and retrying",
                       batch_label, len(arr))
        left_params = {**params, array_key: arr[:mid]}
        right_params = {**params, array_key: arr[mid:]}
        left = _fetch_with_retry(conn, sql, left_params, array_key,
                                 f"{batch_label}L", max_retries - 1)
        right = _fetch_with_retry(conn, sql, right_params, array_key,
                                  f"{batch_label}R", max_retries - 1)
        return left + right


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def find_pricing_gaps(
    check_date: Optional[date] = None,
    db_configs: Optional[dict] = None,
    filters: Optional[dict] = None,
    on_progress: Optional[callable] = None,
) -> list[dict]:
    """
    Identify PO line items missing a product_price record in prcdb.

    Parameters
    ----------
    check_date : date, optional
        Date to check POs for (default: today).
    db_configs : dict, optional
        Must contain 'racdb' and 'prcdb' keys, each a dict with
        host, port, dbname, user, password.
        If None, reads from environment variables.
    filters : dict, optional
        Optional filters: {"store": "1234", "po_number": "622"}.
        Applied as post-query filters on Step 1 results.
    on_progress : callable, optional
        Callback(step, status, detail) for progress reporting.
        step: int (1-4), status: str, detail: str.

    Returns
    -------
    list[dict]
        Each dict contains: purchase_order_number, line_number,
        rms_item_master_id, rms_item_number, model_number,
        store_number, zone_id, zone_number, zone_name, gap_reason.
        Empty list if no gaps found.
    """
    def _progress(step, status, detail=""):
        if on_progress:
            on_progress(step, status, detail)
    if check_date is None:
        check_date = date.today()

    if db_configs is None:
        db_configs = {
            "racdb": {
                "host": os.environ.get("RACDB_HOST", "localhost"),
                "port": os.environ.get("RACDB_PORT", "5432"),
                "dbname": os.environ.get("RACDB_NAME", "racdb"),
                "user": os.environ.get("RACDB_USER", "racdb_user"),
                "password": os.environ.get("RACDB_PASSWORD", ""),
            },
            "prcdb": {
                "host": os.environ.get("PRCDB_HOST", "localhost"),
                "port": os.environ.get("PRCDB_PORT", "5432"),
                "dbname": os.environ.get("PRCDB_NAME", "prcdb"),
                "user": os.environ.get("PRCDB_USER", "prcdb_user"),
                "password": os.environ.get("PRCDB_PASSWORD", ""),
            },
        }

    filters = filters or {}

    # --- Step 1: PO items from racdb ---
    # Filters are pushed into SQL for performance (avoids fetching all rows).
    _progress(1, "running", "Connecting to RAC database and fetching PO items…")
    logger.info("Step 1/3: Querying racdb for PO line items on %s", check_date)
    rac_conn = _connect(db_configs["racdb"], "racdb")
    try:
        po_items = _fetch(rac_conn, PRICING_VALIDATION_PO_ITEMS, {
            "check_date": check_date,
            "store_number": filters.get("store") or None,
            "po_number": filters.get("po_number") or None,
        })
    finally:
        rac_conn.close()

    if not po_items:
        logger.info("No non-cancelled PO line items found for %s.", check_date)
        _progress(1, "done", "No PO items found for this date.")
        return []

    num_pos = len({r["purchase_order_number"] for r in po_items})
    _progress(1, "done", f"Found {len(po_items)} line item(s) across {num_pos} PO(s).")
    logger.info("Found %d line item(s) across %d PO(s).",
                len(po_items), num_pos)

    unique_stores = list({r["store_number"] for r in po_items})
    unique_item_numbers = list({r["rms_item_number"] for r in po_items})

    # --- Step 2: Store → zone mapping from prcdb ---
    _progress(2, "running", f"Resolving pricing zones for {len(unique_stores)} store(s)…")
    logger.info("Step 2/3: Resolving pricing zones for %d store(s)", len(unique_stores))
    prc_conn = _connect(db_configs["prcdb"], "prcdb")
    try:
        store_zone_rows = _fetch(prc_conn, PRICING_VALIDATION_STORE_ZONES, {
            "store_numbers": unique_stores,
            "check_date": check_date,
        })

        store_to_zones: dict[str, list[dict]] = {}
        for row in store_zone_rows:
            store_to_zones.setdefault(row["store_number"], []).append(row)

        all_zone_ids = list({row["zone_id"] for row in store_zone_rows})

        if not all_zone_ids:
            logger.warning("No pricing zones resolved for any store — all items are gaps.")
            _progress(2, "done", "No pricing zones found — all items are gaps.")
            gaps = []
            for item in po_items:
                gaps.append(_build_gap(item, zone_id=None, zone_number=None,
                                       zone_name=None,
                                       reason="Store has no active pricing zone"))
            return gaps

        # --- Step 3: pricing check — item_price AND item_price_hierarchy ---
        _progress(2, "done", f"Resolved {len(all_zone_ids)} zone(s) for {len(store_to_zones)} store(s).")
        _progress(3, "running", f"Checking pricing for {len(unique_item_numbers)} item(s) × {len(all_zone_ids)} zone(s)…")
        # An item is considered priced if it has valid rows in EITHER system:
        #   3a. item_price (PERMANENT/TEMPORARY/MANUAL, direct column values)
        #   3b. item_price_hierarchy + pricing_param_value (RACPad pricing screen)
        #
        # Architecture (production-safe):
        #   - Micro-batches to keep each SQL statement fast (<30s target)
        #   - Adaptive retry: if a batch times out, it's halved automatically
        #   - 3b split into two phases (resolve hierarchy IDs, then 4 level queries)
        #   - 3a and 3b run in parallel via ThreadPoolExecutor
        logger.info("Step 3/3: Checking item_price + item_price_hierarchy for %d item(s) × %d zone(s)",
                    len(unique_item_numbers), len(all_zone_ids))

        # Convert zone_ids to text for Step 3a (matches VARCHAR column directly)
        zone_ids_text = [str(z) for z in all_zone_ids]

        # ── 3a: item_price (direct column-based pricing) ──────────────────────
        def _run_3a():
            t0 = time.monotonic()
            _progress(3, "running", f"3a — querying item_price ({len(unique_item_numbers)} items, batches of {BATCH_SIZE_3A})…")
            results = []
            batches = list(_batched(unique_item_numbers, BATCH_SIZE_3A))
            for idx, batch in enumerate(batches, 1):
                _progress(3, "running", f"3a — batch {idx}/{len(batches)} ({len(batch)} items)…")
                results.extend(_fetch_with_retry(
                    prc_conn, PRICING_VALIDATION_EXISTING_PRICES,
                    {"rms_item_numbers": batch, "zone_ids_text": zone_ids_text},
                    array_key="rms_item_numbers",
                    batch_label=f"3a-batch{idx}",
                ))
            elapsed = time.monotonic() - t0
            logger.info("Step 3a done: %d rows in %.1fs", len(results), elapsed)
            _progress(3, "running", f"3a done — {len(results)} row(s) in {elapsed:.1f}s.")
            return results

        # ── 3b: hierarchy pricing (two-phase approach) ─────────────────────────
        def _run_3b():
            t0 = time.monotonic()
            conn_3b = _connect(db_configs["prcdb"], "prcdb")
            try:
                # Phase 1: Resolve item hierarchy IDs (lightweight)
                _progress(3, "running", "3b — resolving item hierarchy chain…")
                hierarchy_rows_raw = []
                for batch in _batched(unique_item_numbers, BATCH_SIZE_3B_RESOLVE):
                    hierarchy_rows_raw.extend(_fetch(conn_3b, PRICING_VALIDATION_HIERARCHY_RESOLVE, {
                        "rms_item_numbers": batch,
                    }))

                if not hierarchy_rows_raw:
                    logger.info("Step 3b: no hierarchy rows resolved.")
                    _progress(3, "running", "3b — no hierarchy entities found.")
                    return []

                # Build lookup maps: entity_id → set of rms_item_numbers
                item_master_map = {}   # rms_item_master_id → {rms_item_number, ...}
                bracket_map = {}       # rms_bracket_id → {rms_item_number, ...}
                subdept_map = {}       # rms_subdepartment_id → {rms_item_number, ...}
                dept_map = {}          # rms_department_id → {rms_item_number, ...}

                for row in hierarchy_rows_raw:
                    item_num = row["rms_item_number"]
                    item_master_map.setdefault(row["rms_item_master_id"], set()).add(item_num)
                    if row["rms_bracket_id"]:
                        bracket_map.setdefault(row["rms_bracket_id"], set()).add(item_num)
                    if row["rms_subdepartment_id"]:
                        subdept_map.setdefault(row["rms_subdepartment_id"], set()).add(item_num)
                    if row["rms_department_id"]:
                        dept_map.setdefault(row["rms_department_id"], set()).add(item_num)

                # Phase 2: Query each hierarchy level independently
                # Each level returns (entity_id, zone_id, key_names[])
                REQUIRED_KEYS = {"WeeklyRateNew", "WeeklyRateUsed", "WeeklyTerm"}
                CASH_KEYS = {"CashPriceMultiplier", "ForcedCashPrice"}

                def _is_complete(key_names):
                    keys = set(key_names) if key_names else set()
                    return REQUIRED_KEYS.issubset(keys) and bool(CASH_KEYS & keys)

                # Accumulate results as (rms_item_number, zone_id, is_complete)
                results = []

                levels = [
                    ("L1-Item", PRICING_VALIDATION_HIERARCHY_L1_ITEM, item_master_map),
                    ("L2-Bracket", PRICING_VALIDATION_HIERARCHY_L2_BRACKET, bracket_map),
                    ("L3-Subdept", PRICING_VALIDATION_HIERARCHY_L3_SUBDEPT, subdept_map),
                    ("L4-Dept", PRICING_VALIDATION_HIERARCHY_L4_DEPT, dept_map),
                ]

                for level_name, sql, entity_map in levels:
                    entity_ids = list(entity_map.keys())
                    if not entity_ids:
                        continue
                    _progress(3, "running", f"3b — {level_name} ({len(entity_ids)} entities, batches of {BATCH_SIZE_3B_LEVEL})…")
                    for batch in _batched(entity_ids, BATCH_SIZE_3B_LEVEL):
                        rows = _fetch_with_retry(
                            conn_3b, sql,
                            {"entity_ids": batch, "zone_ids": all_zone_ids},
                            array_key="entity_ids",
                            batch_label=f"3b-{level_name}",
                        )
                        for r in rows:
                            complete = _is_complete(r["key_names"])
                            # Map entity_id back to all item_numbers it covers
                            for item_num in entity_map.get(r["entity_id"], []):
                                results.append({
                                    "rms_item_number": item_num,
                                    "zone_id": r["zone_id"],
                                    "is_complete": complete,
                                })

                elapsed = time.monotonic() - t0
                logger.info("Step 3b done: %d rows in %.1fs", len(results), elapsed)
                _progress(3, "running", f"3b done — {len(results)} row(s) in {elapsed:.1f}s.")
                return results
            finally:
                conn_3b.close()

        # ── 3c: product_price (authoritative table queried by RACPad at receive time) ─
        def _run_3c():
            t0 = time.monotonic()
            conn_3c = _connect(db_configs["prcdb"], "prcdb")
            try:
                _progress(3, "running", f"3c — querying product_price ({len(unique_item_numbers)} items, batches of {BATCH_SIZE_3C})…")
                results = []
                batches = list(_batched(unique_item_numbers, BATCH_SIZE_3C))
                for idx, batch in enumerate(batches, 1):
                    _progress(3, "running", f"3c — batch {idx}/{len(batches)} ({len(batch)} items)…")
                    results.extend(_fetch_with_retry(
                        conn_3c, PRICING_VALIDATION_PRODUCT_PRICES,
                        {"rms_item_numbers": batch, "zone_ids": all_zone_ids},
                        array_key="rms_item_numbers",
                        batch_label=f"3c-batch{idx}",
                    ))
                elapsed = time.monotonic() - t0
                logger.info("Step 3c done: %d rows in %.1fs", len(results), elapsed)
                _progress(3, "running", f"3c done — {len(results)} row(s) in {elapsed:.1f}s.")
                return results
            finally:
                conn_3c.close()

        with ThreadPoolExecutor(max_workers=3) as executor:
            future_3a = executor.submit(_run_3a)
            future_3b = executor.submit(_run_3b)
            future_3c = executor.submit(_run_3c)
            # Generous overall timeout: sum of all possible batch timeouts
            overall_timeout = STATEMENT_TIMEOUT_S * 10
            price_rows = future_3a.result(timeout=overall_timeout)
            hierarchy_rows = future_3b.result(timeout=overall_timeout)
            product_price_rows = future_3c.result(timeout=overall_timeout)
    finally:
        prc_conn.close()

    _progress(3, "done", f"item_price: {len(price_rows)} row(s), hierarchy: {len(hierarchy_rows)} row(s), product_price: {len(product_price_rows)} row(s).")
    _progress(4, "running", "Analyzing gaps…")

    ip_exists = {(r["rms_item_number"], r["zone_id"]) for r in price_rows}
    ih_exists = {(r["rms_item_number"], r["zone_id"]) for r in hierarchy_rows}
    # product_price: the table RACPad queries at receive time — authoritative presence check
    pp_exists = {(r["rms_item_number"], r["zone_id"]) for r in product_price_rows}
    # MANUAL pricing is not published to product_price; items priced exclusively as
    # MANUAL must bypass the pp_exists check or they would always appear as MISSING.
    ip_manual_exists = {
        (r["rms_item_number"], r["zone_id"]) for r in price_rows if r.get("has_manual")
    }

    # (rms_item_number, zone_id) present in EITHER item_price system
    priced_exists: set[tuple] = ip_exists | ih_exists
    # (rms_item_number, zone_id) complete in EITHER item_price system
    priced_complete: set[tuple] = {
        (r["rms_item_number"], r["zone_id"]) for r in price_rows if r["is_complete"]
    } | {
        (r["rms_item_number"], r["zone_id"]) for r in hierarchy_rows if r["is_complete"]
    }

    # --- Gap detection ---
    # Priority order (highest to lowest):
    #   1. MISSING from product_price — RACPad will throw "Pricing details not found"
    #      even if item_price / item_price_hierarchy has data.
    #      Exception: items with pricing_type = MANUAL in item_price are exempt because
    #      MANUAL pricing is never published to product_price by design.
    #   2. MISSING from item_price — no item_price or hierarchy record at all.
    #   3. INCOMPLETE — item_price row exists but required fields are NULL.
    gaps = []
    for item in po_items:
        store = item["store_number"]
        zones = store_to_zones.get(store, [])

        if not zones:
            gaps.append(_build_gap(item, zone_id=None, zone_number=None,
                                   zone_name=None,
                                   reason="Store has no active pricing zone"))
            continue

        for zone in zones:
            key = (item["rms_item_number"], zone["zone_id"])
            # Items with MANUAL pricing in item_price are exempt from the product_price
            # check because MANUAL type is never written to product_price.
            requires_pp = key not in ip_manual_exists
            if requires_pp and key not in pp_exists:
                gaps.append(_build_gap(item, zone_id=zone["zone_id"],
                                       zone_number=zone["zone_number"],
                                       zone_name=zone["zone_name"],
                                       reason="MISSING — no product_price record"))
            elif key not in priced_exists:
                gaps.append(_build_gap(item, zone_id=zone["zone_id"],
                                       zone_number=zone["zone_number"],
                                       zone_name=zone["zone_name"],
                                       reason="MISSING — no item_price record"))
            elif key not in priced_complete:
                gaps.append(_build_gap(item, zone_id=zone["zone_id"],
                                       zone_number=zone["zone_number"],
                                       zone_name=zone["zone_name"],
                                       reason="INCOMPLETE — required fields are NULL"))

    logger.info("Gap detection complete: %d gap(s) found out of %d line item(s).",
                len(gaps), len(po_items))
    if gaps:
        _progress(4, "done", f"{len(gaps)} gap(s) found out of {len(po_items)} line item(s).")
    else:
        _progress(4, "done", f"No gaps — all {len(po_items)} line item(s) have complete pricing.")
    return gaps


def _build_gap(item: dict, zone_id, zone_number, zone_name, reason: str) -> dict:
    """Construct a normalized gap record."""
    return {
        "purchase_order_number": item["purchase_order_number"],
        "line_number": item.get("line_number"),
        "rms_item_master_id": item["rms_item_master_id"],
        "rms_item_number": item["rms_item_number"],
        "model_number": item.get("model_number", "N/A"),
        "item_description": item.get("item_description", ""),
        "store_number": item["store_number"],
        "order_date": item.get("order_date"),
        "po_status": item.get("po_status"),
        "zone_id": zone_id,
        "zone_number": zone_number,
        "zone_name": zone_name,
        "gap_reason": reason,
    }


# ---------------------------------------------------------------------------
# CLI entry point (backward-compatible)
# ---------------------------------------------------------------------------

def _cli():
    import argparse

    parser = argparse.ArgumentParser(description="Post-PO Pricing Gap Validator")
    parser.add_argument("--date", type=str, default=None,
                        help="Check date (YYYY-MM-DD). Default: today.")
    parser.add_argument("--store", type=str, default=None,
                        help="Filter by store number.")
    parser.add_argument("--po", type=str, default=None,
                        help="Filter by PO number.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    check = date.fromisoformat(args.date) if args.date else date.today()
    filters = {}
    if args.store:
        filters["store"] = args.store
    if args.po:
        filters["po_number"] = args.po

    try:
        gaps = find_pricing_gaps(check_date=check, filters=filters)
    except ConnectionError as e:
        sys.exit(str(e))

    if not gaps:
        print(f"All PO items on {check} have complete pricing records.")
        return

    missing = sum(1 for g in gaps if "MISSING" in g["gap_reason"])
    incomplete = sum(1 for g in gaps if "INCOMPLETE" in g["gap_reason"])
    print(f"\n{len(gaps)} PRICING GAP(S) FOUND  [{missing} missing, {incomplete} incomplete]\n" + "=" * 60)
    for gap in sorted(gaps, key=lambda g: (g["purchase_order_number"], g["rms_item_number"])):
        print(f"  PO {gap['purchase_order_number']} | Store {gap['store_number']} | "
              f"Item {gap['rms_item_number']} | Model {gap['model_number']} | "
              f"Zone {gap.get('zone_number', 'N/A')} | {gap['gap_reason']}")


if __name__ == "__main__":
    _cli()
