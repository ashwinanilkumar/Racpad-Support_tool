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
 