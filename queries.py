"""
po_queries.py — SQL query constants for the Racpad Support Tool.

All queries use %(name)s placeholders for psycopg2 named parameters.
Updated to include manufacturer model numbers for display in the app.
"""

# ─────────────────────────────────────────────────────────────────────────────
# PO622 Diagnostic Queries
# ─────────────────────────────────────────────────────────────────────────────

PO_OVERVIEW = """
SELECT
    po.purchase_order_id,
    po.purchase_order_number,
    pot.ref_code                AS po_type,
    pot.desc_en                 AS po_type_description,
    post.ref_code               AS po_status,
    post.desc_en                AS po_status_description,
    po.order_date,
    po.estimated_delivery_date,
    po.ship_to_store            AS store_number,
    po.close_date,
    po.cancel_date,
    po.created_by,
    po.created_date
FROM racadm.purchase_order po
JOIN racadm.purchase_order_type pot
    ON po.purchase_order_type_id = pot.purchase_order_type_id
JOIN racadm.purchase_order_status_type post
    ON po.purchase_order_status_type_id = post.purchase_order_status_type_id
WHERE po.purchase_order_number = %(po_number)s
  AND po.ship_to_store = %(store_number)s
"""

PO_LINE_ITEM_STATUS = """
SELECT
    pod.purchase_order_detail_id,
    pod.purchase_order_line_number,
    rim.rms_item_number,
    rim.desc_en AS item_description,
    mmm.manufacturer_model_number AS model_number,
    pod.quantity_ordered,
    pod.vendor_unit_cost,
    pod.quantity_canceled,
    COUNT(podr.po_detail_received_id) FILTER (
        WHERE (podr.partial_po_reason_type_id IS NULL OR podr.partial_po_reason_type_id = 0)
          AND podr.reversal_status_type_id IS NULL
    ) AS fully_received_count,
    COUNT(podr.po_detail_received_id) FILTER (
        WHERE podr.partial_po_reason_type_id IS NOT NULL
          AND podr.partial_po_reason_type_id != 0
    ) AS partial_received_count,
    COUNT(podr.po_detail_received_id) FILTER (
        WHERE podr.reversal_status_type_id IS NOT NULL
    ) AS reversed_count,
    COUNT(podr.po_detail_received_id) FILTER (
        WHERE podr.reversal_date IS NOT NULL
          AND podr.reversal_status_type_id IS NULL
    ) AS stuck_reversal_count,
    pod.quantity_ordered - COUNT(podr.po_detail_received_id) FILTER (
        WHERE (podr.partial_po_reason_type_id IS NULL OR podr.partial_po_reason_type_id = 0)
          AND podr.reversal_status_type_id IS NULL
    ) AS remaining_to_receive
FROM racadm.purchase_order po
JOIN racadm.purchase_order_detail pod
    ON po.purchase_order_id = pod.purchase_order_id
JOIN racadm.rms_item_master rim
    ON pod.rms_item_master_id = rim.rms_item_master_id
LEFT JOIN racadm.manufacturer_model_master mmm
    ON rim.rms_item_master_id = mmm.rms_item_master_id
LEFT JOIN racadm.purchase_order_detail_received podr
    ON pod.purchase_order_detail_id = podr.purchase_order_detail_id
WHERE po.purchase_order_number = %(po_number)s
  AND po.ship_to_store = %(store_number)s
GROUP BY pod.purchase_order_detail_id, pod.purchase_order_line_number,
         rim.rms_item_number, rim.desc_en, mmm.manufacturer_model_number,
         pod.quantity_ordered, pod.vendor_unit_cost, pod.quantity_canceled
ORDER BY pod.purchase_order_line_number
"""

PO_DUPLICATE_SERIAL = """
SELECT
    podr.manufacturer_serial_number,
    rim.rms_item_number,
    mmm.manufacturer_model_number AS model_number,
    COUNT(*) AS times_used,
    ARRAY_AGG(podr.po_detail_received_id ORDER BY podr.created_date) AS received_ids,
    ARRAY_AGG(podr.created_date ORDER BY podr.created_date) AS receive_dates,
    ARRAY_AGG(podr.created_by ORDER BY podr.created_date) AS received_by_users
FROM racadm.purchase_order po
JOIN racadm.purchase_order_detail pod
    ON po.purchase_order_id = pod.purchase_order_id
JOIN racadm.rms_item_master rim
    ON pod.rms_item_master_id = rim.rms_item_master_id
LEFT JOIN racadm.manufacturer_model_master mmm
    ON rim.rms_item_master_id = mmm.rms_item_master_id
JOIN racadm.purchase_order_detail_received podr
    ON pod.purchase_order_detail_id = podr.purchase_order_detail_id
WHERE po.purchase_order_number = %(po_number)s
  AND po.ship_to_store = %(store_number)s
  AND podr.manufacturer_serial_number IS NOT NULL
  AND podr.manufacturer_serial_number != ''
GROUP BY podr.manufacturer_serial_number, rim.rms_item_number, mmm.manufacturer_model_number
HAVING COUNT(*) > 1
"""

PO_CONCURRENCY = """
SELECT
    a.po_detail_received_id AS receive_id_1,
    b.po_detail_received_id AS receive_id_2,
    a.created_date AS time_1,
    b.created_date AS time_2,
    EXTRACT(EPOCH FROM (b.created_date - a.created_date)) AS seconds_apart,
    a.created_by AS user_1,
    b.created_by AS user_2,
    rim.rms_item_number,
    mmm.manufacturer_model_number AS model_number,
    a.manufacturer_serial_number AS serial_1,
    b.manufacturer_serial_number AS serial_2
FROM racadm.purchase_order po
JOIN racadm.purchase_order_detail pod
    ON po.purchase_order_id = pod.purchase_order_id
JOIN racadm.rms_item_master rim
    ON pod.rms_item_master_id = rim.rms_item_master_id
LEFT JOIN racadm.manufacturer_model_master mmm
    ON rim.rms_item_master_id = mmm.rms_item_master_id
JOIN racadm.purchase_order_detail_received a
    ON pod.purchase_order_detail_id = a.purchase_order_detail_id
JOIN racadm.purchase_order_detail_received b
    ON pod.purchase_order_detail_id = b.purchase_order_detail_id
WHERE po.purchase_order_number = %(po_number)s
  AND po.ship_to_store = %(store_number)s
  AND a.po_detail_received_id < b.po_detail_received_id
  AND ABS(EXTRACT(EPOCH FROM (b.created_date - a.created_date))) <= 10
  AND (a.partial_po_reason_type_id IS NULL OR a.partial_po_reason_type_id = 0)
  AND (b.partial_po_reason_type_id IS NULL OR b.partial_po_reason_type_id = 0)
  AND a.reversal_status_type_id IS NULL
  AND b.reversal_status_type_id IS NULL
ORDER BY a.created_date
"""

PO_TIMELINE = """
SELECT * FROM (
    -- PO Created
    SELECT
        'PO_CREATED' AS event_type,
        po.created_date AS event_time,
        po.created_by AS performed_by,
        'PO created. Status: ' || post.ref_code || ', Type: ' || pot.ref_code AS details,
        NULL::bigint AS po_detail_received_id,
        NULL::varchar AS serial_number,
        NULL::bigint AS rms_item_number,
        NULL::varchar AS model_number
    FROM racadm.purchase_order po
    JOIN racadm.purchase_order_type pot
        ON po.purchase_order_type_id = pot.purchase_order_type_id
    JOIN racadm.purchase_order_status_type post
        ON po.purchase_order_status_type_id = post.purchase_order_status_type_id
    WHERE po.purchase_order_number = %(po_number)s
      AND po.ship_to_store = %(store_number)s

    UNION ALL

    -- Full Receives
    SELECT
        'FULL_RECEIVE' AS event_type,
        podr.created_date AS event_time,
        podr.created_by AS performed_by,
        'Inventory ID: ' || COALESCE(podr.inventory_id::text, 'NULL') AS details,
        podr.po_detail_received_id,
        podr.manufacturer_serial_number AS serial_number,
        rim.rms_item_number,
        mmm.manufacturer_model_number AS model_number
    FROM racadm.purchase_order po
    JOIN racadm.purchase_order_detail pod ON po.purchase_order_id = pod.purchase_order_id
    JOIN racadm.rms_item_master rim ON pod.rms_item_master_id = rim.rms_item_master_id
    LEFT JOIN racadm.manufacturer_model_master mmm ON rim.rms_item_master_id = mmm.rms_item_master_id
    JOIN racadm.purchase_order_detail_received podr ON pod.purchase_order_detail_id = podr.purchase_order_detail_id
    WHERE po.purchase_order_number = %(po_number)s
      AND po.ship_to_store = %(store_number)s
      AND (podr.partial_po_reason_type_id IS NULL OR podr.partial_po_reason_type_id = 0)
      AND podr.reversal_date IS NULL

    UNION ALL

    -- Partial Receives
    SELECT
        'PARTIAL_RECEIVE' AS event_type,
        podr.created_date AS event_time,
        podr.created_by AS performed_by,
        'Partial reason type ID: ' || podr.partial_po_reason_type_id::text AS details,
        podr.po_detail_received_id,
        podr.manufacturer_serial_number AS serial_number,
        rim.rms_item_number,
        mmm.manufacturer_model_number AS model_number
    FROM racadm.purchase_order po
    JOIN racadm.purchase_order_detail pod ON po.purchase_order_id = pod.purchase_order_id
    JOIN racadm.rms_item_master rim ON pod.rms_item_master_id = rim.rms_item_master_id
    LEFT JOIN racadm.manufacturer_model_master mmm ON rim.rms_item_master_id = mmm.rms_item_master_id
    JOIN racadm.purchase_order_detail_received podr ON pod.purchase_order_detail_id = podr.purchase_order_detail_id
    WHERE po.purchase_order_number = %(po_number)s
      AND po.ship_to_store = %(store_number)s
      AND podr.partial_po_reason_type_id IS NOT NULL
      AND podr.partial_po_reason_type_id != 0

    UNION ALL

    -- Reversals
    SELECT
        CASE
            WHEN podr.reversal_status_type_id IS NOT NULL THEN 'REVERSAL_COMPLETE'
            ELSE 'REVERSAL_STUCK'
        END AS event_type,
        COALESCE(podr.reversal_date_time, podr.last_modified_date) AS event_time,
        podr.last_modified_by AS performed_by,
        'Reversal status type ID: ' || COALESCE(podr.reversal_status_type_id::text, 'NULL (STUCK!)')
            || ' | Reversal date: ' || COALESCE(podr.reversal_date::text, 'NULL') AS details,
        podr.po_detail_received_id,
        podr.manufacturer_serial_number AS serial_number,
        rim.rms_item_number,
        mmm.manufacturer_model_number AS model_number
    FROM racadm.purchase_order po
    JOIN racadm.purchase_order_detail pod ON po.purchase_order_id = pod.purchase_order_id
    JOIN racadm.rms_item_master rim ON pod.rms_item_master_id = rim.rms_item_master_id
    LEFT JOIN racadm.manufacturer_model_master mmm ON rim.rms_item_master_id = mmm.rms_item_master_id
    JOIN racadm.purchase_order_detail_received podr ON pod.purchase_order_detail_id = podr.purchase_order_detail_id
    WHERE po.purchase_order_number = %(po_number)s
      AND po.ship_to_store = %(store_number)s
      AND podr.reversal_date IS NOT NULL
) timeline
ORDER BY event_time ASC
"""
# ─────────────────────────────────────────────────────────────────────────────
# Pricing Validation Queries
#
# Flow: PO created → destination store → zone for store → check item_price
#       for RMS + zone + pricing_type → if none found or incomplete → alert
#
# Core table : prcadm.item_price  (NOT product_price)
# Zone join  : item_price.price_hierarchy_value::bigint = prcadm.zone.zone_id
#
# Run in order: Step 1 (racdb) → Step 2 (prcdb) → Step 3 (prcdb)
# ─────────────────────────────────────────────────────────────────────────────

# Step 1 ── racdb ─────────────────────────────────────────────────────────────
# PO line items for check_date, excluding fully-received lines.
# “Fully received” = received_qty >= quantity_ordered (non-partial, non-reversed).
#
# Parameters:
#   check_date  date  POs with order_date on this date  (default: CURRENT_DATE)
PRICING_VALIDATION_PO_ITEMS = """
SELECT
    po.purchase_order_number,
    po.ship_to_store                               AS store_number,
    po.order_date,
    po.created_date                                AS po_created_date,
    post.ref_code                                  AS po_status,
    pod.purchase_order_line_number                 AS line_number,
    rim.rms_item_master_id,
    rim.rms_item_number,
    rim.desc_en                                    AS item_description,
    COALESCE(mmm.manufacturer_model_number, 'N/A') AS model_number,
    pod.quantity_ordered
FROM racadm.purchase_order po
JOIN racadm.purchase_order_status_type post
    ON po.purchase_order_status_type_id = post.purchase_order_status_type_id
JOIN racadm.purchase_order_detail pod
    ON po.purchase_order_id = pod.purchase_order_id
JOIN racadm.rms_item_master rim
    ON pod.rms_item_master_id = rim.rms_item_master_id
LEFT JOIN racadm.manufacturer_model_master mmm
    ON rim.rms_item_master_id = mmm.rms_item_master_id
-- Count non-partial, non-reversed receives per line
LEFT JOIN (
    SELECT purchase_order_detail_id,
           COUNT(*) AS received_qty
    FROM racadm.purchase_order_detail_received
    WHERE (partial_po_reason_type_id IS NULL OR partial_po_reason_type_id = 0)
      AND reversal_status_type_id IS NULL
    GROUP BY purchase_order_detail_id
) recv ON recv.purchase_order_detail_id = pod.purchase_order_detail_id
WHERE po.order_date  = %(check_date)s
  AND post.ref_code != 'CANCELLED'
  -- Skip lines where all ordered units have already been received
  AND COALESCE(recv.received_qty, 0) < pod.quantity_ordered
  -- Optional filters (NULL = no filter applied)
  AND (%(store_number)s IS NULL OR po.ship_to_store = %(store_number)s)
  AND (%(po_number)s IS NULL OR po.purchase_order_number::text = %(po_number)s)
ORDER BY po.purchase_order_number, pod.purchase_order_line_number
"""

# Step 2 ── prcdb ─────────────────────────────────────────────────────────────
# Resolve store numbers to their active pricing zone, with full date validation
# against zone_store, zone, AND store (open/close dates).
#
# Parameters:
#   store_numbers  list[str]  store numbers from Step 1
#   check_date     date       same date used in Step 1
PRICING_VALIDATION_STORE_ZONES = """
SELECT
    zs.store_number,
    z.zone_id,
    z.zone_number,
    z.zone_name
FROM prcadm.zone_store zs
JOIN prcadm.zone z
    ON zs.zone_id = z.zone_id
-- LEFT JOIN so stores absent from prcadm.store still resolve a zone
LEFT JOIN prcadm.store s
    ON s.store_number = zs.store_number
WHERE zs.store_number = ANY(%(store_numbers)s)
  -- zone_store active on check_date
  AND (zs.start_date IS NULL OR zs.start_date <= %(check_date)s)
  AND (zs.end_date   IS NULL OR zs.end_date   >= %(check_date)s)
  -- zone itself active on check_date
  AND (z.start_date  IS NULL OR z.start_date  <= %(check_date)s)
  AND (z.end_date    IS NULL OR z.end_date    >= %(check_date)s)
  -- store open on check_date (NULL open_date = always open)
  AND (s.open_date   IS NULL OR s.open_date   <= %(check_date)s)
  AND (s.close_date  IS NULL OR s.close_date  >= %(check_date)s)
ORDER BY zs.store_number, z.zone_number
"""

# Step 3 ── prcdb ─────────────────────────────────────────────────────────────
# Check prcadm.item_price for active pricing covering PERMANENT, TEMPORARY,
# and MANUAL types for the given items and zones.
#
# Zone join: price_hierarchy_value is compared as TEXT against zone_ids cast to
# text via ANY().  This avoids the regex guard + ::bigint cast which prevented
# index usage on price_hierarchy_value.
#
# Returns one row per (rms_item_number, zone_id) with:
#   is_complete = true when at least one pricing_type has all required fields.
#
# Parameters:
#   rms_item_numbers  list[int]  rms_item_number values from Step 1
#   zone_ids_text     list[str]  zone_id values as TEXT from Step 2
PRICING_VALIDATION_EXISTING_PRICES = """
SELECT
    prim.rms_item_number,
    ip.price_hierarchy_value::bigint AS zone_id,
    BOOL_OR(
        CASE
            WHEN ip.pricing_type = 'MANUAL' THEN
                ip.weekly_rate_new  IS NOT NULL
                AND ip.weekly_rate_used IS NOT NULL
                AND ip.turn             IS NOT NULL
                AND (ip.cash_price_multiplier IS NOT NULL
                     OR ip.forced_cash_price  IS NOT NULL)
            ELSE
                ip.weekly_rate_new  IS NOT NULL
                AND ip.weekly_rate_used IS NOT NULL
                AND ip.term             IS NOT NULL
                AND (ip.cash_price_multiplier IS NOT NULL
                     OR ip.forced_cash_price  IS NOT NULL)
        END
    ) AS is_complete
FROM prcadm.item_price ip
JOIN prcadm.rms_item_master prim
    ON ip.rms_item_master_id = prim.rms_item_master_id
WHERE prim.rms_item_number         = ANY(%(rms_item_numbers)s)
  AND ip.price_hierarchy_value     = ANY(%(zone_ids_text)s)
  AND ip.pricing_type              IN ('PERMANENT', 'TEMPORARY', 'MANUAL')
  AND (ip.end_time IS NULL OR ip.end_time > CURRENT_TIMESTAMP)
GROUP BY prim.rms_item_number, ip.price_hierarchy_value
"""

# Step 3b ── prcdb ─────────────────────────────────────────────────────────────
# Check prcadm.item_price_hierarchy + prcadm.pricing_param_value — the exact
# tables queried by the RACPad pricing administration screen.
#
# Covers all 4 hierarchy levels so bracket/subdept/dept-level pricing is not
# missed.  The item’s full hierarchy chain is resolved in a CTE using the
# prcadm.rms_item_master → rms_bracket → rms_subdepartment chain.
#
# An item’s hierarchy row is ACTIVE when:
#   iph.end_date    > CURRENT_DATE          (row still valid)
#   ppv.end_time   >= CURRENT_TIMESTAMP     (param value still active)
# Rows with no active pricing_param_value rows are excluded (no params = no price).
#
# is_complete = true when the aggregated params contain:
#   WeeklyRateNew + WeeklyRateUsed + WeeklyTerm
#   AND (CashPriceMultiplier OR ForcedCashPrice)
#
# Verified pricing_param_key_name values (all keys in prcadm.pricing_param_key):
#   CashPriceMultiplier, Clearance, EpoPercent, ForcedCashPrice,
#   SacDays, SacDaysPrinted, Turn, WeeklyAddOnRate,
#   WeeklyRateNew, WeeklyRateUsed, WeeklyTerm
#
# Parameters:
#   rms_item_numbers  list[int]  rms_item_number values from Step 1
#   zone_ids          list[int]  zone_id values from Step 2
PRICING_VALIDATION_HIERARCHY_PRICES = """
WITH item_hierarchy AS (
    SELECT
        prim.rms_item_master_id,
        prim.rms_item_number,
        prim.rms_bracket_id,
        rb.rms_subdepartment_id,
        rs.rms_department_id
    FROM prcadm.rms_item_master prim
    LEFT JOIN prcadm.rms_bracket rb
        ON prim.rms_bracket_id = rb.rms_bracket_id
    LEFT JOIN prcadm.rms_subdepartment rs
        ON rb.rms_subdepartment_id = rs.rms_subdepartment_id
    WHERE prim.rms_item_number = ANY(%(rms_item_numbers)s)
),
matched_hierarchy AS (
    -- Level 1: ITEM
    SELECT ih.rms_item_number, iph.item_price_hierarchy_id, iph.zone_id
    FROM item_hierarchy ih
    JOIN prcadm.item_price_hierarchy iph
        ON iph.rms_item_master_id = ih.rms_item_master_id
    WHERE iph.zone_id = ANY(%(zone_ids)s)
      AND iph.end_date > CURRENT_DATE

    UNION ALL

    -- Level 2: BRACKET
    SELECT ih.rms_item_number, iph.item_price_hierarchy_id, iph.zone_id
    FROM item_hierarchy ih
    JOIN prcadm.item_price_hierarchy iph
        ON iph.rms_bracket_id = ih.rms_bracket_id
    WHERE ih.rms_bracket_id IS NOT NULL
      AND iph.zone_id = ANY(%(zone_ids)s)
      AND iph.end_date > CURRENT_DATE

    UNION ALL

    -- Level 3: SUBDEPT
    SELECT ih.rms_item_number, iph.item_price_hierarchy_id, iph.zone_id
    FROM item_hierarchy ih
    JOIN prcadm.item_price_hierarchy iph
        ON iph.rms_subdepartment_id = ih.rms_subdepartment_id
    WHERE ih.rms_subdepartment_id IS NOT NULL
      AND iph.zone_id = ANY(%(zone_ids)s)
      AND iph.end_date > CURRENT_DATE

    UNION ALL

    -- Level 4: DEPT
    SELECT ih.rms_item_number, iph.item_price_hierarchy_id, iph.zone_id
    FROM item_hierarchy ih
    JOIN prcadm.item_price_hierarchy iph
        ON iph.rms_department_id = ih.rms_department_id
    WHERE ih.rms_department_id IS NOT NULL
      AND iph.zone_id = ANY(%(zone_ids)s)
      AND iph.end_date > CURRENT_DATE
),
param_keys AS (
    SELECT
        mh.rms_item_number,
        mh.zone_id,
        array_agg(DISTINCT ppk.pricing_param_key_name) AS key_names
    FROM matched_hierarchy mh
    JOIN prcadm.pricing_param_value ppv
        ON ppv.item_price_hierarchy_id = mh.item_price_hierarchy_id
       AND ppv.end_time >= CURRENT_TIMESTAMP
    JOIN prcadm.pricing_param_key ppk
        ON ppv.pricing_param_key_id = ppk.pricing_param_key_id
    GROUP BY mh.rms_item_number, mh.zone_id
)
SELECT
    rms_item_number,
    zone_id,
    (
        'WeeklyRateNew'  = ANY(key_names)
        AND 'WeeklyRateUsed' = ANY(key_names)
        AND 'WeeklyTerm'     = ANY(key_names)
        AND (
            'CashPriceMultiplier' = ANY(key_names)
            OR 'ForcedCashPrice'  = ANY(key_names)
        )
    ) AS is_complete
FROM param_keys
"""
 