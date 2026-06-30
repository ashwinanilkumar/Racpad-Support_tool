"""
queries_config.py — SQL query constants for the App Config Triage tool.

All queries use %(name)s placeholders for psycopg2 named parameters.
Schema: configadm (ConfigDB)
"""

# ─────────────────────────────────────────────────────────────────────────────
# Validation query — check if a rule_name exists
# ─────────────────────────────────────────────────────────────────────────────

VALIDATE_RULE_NAME = """
SELECT 1
FROM   configadm.param_key
WHERE  param_key_name = %(rule_name)s
LIMIT  1
"""

# ─────────────────────────────────────────────────────────────────────────────
# Query 1 — Store Number + Rule Name (Full Hierarchy Fallback + Previous Value)
# Given a store number and rule name, searches all 9 hierarchy levels,
# ranks by specificity, and joins audit table for previous value.
# ─────────────────────────────────────────────────────────────────────────────

QUERY_STORE_HIERARCHY = """
WITH RECURSIVE store_ancestors AS (
    SELECT oh.org_hierarchy_id,
           oh.accounting_unit_level,
           oh.accounting_unit_number
    FROM   configadm.org_hierarchy oh
    WHERE  oh.accounting_unit_number = %(store_number)s
      AND  oh.accounting_unit_level  = 'STORE'

    UNION ALL

    SELECT oh.org_hierarchy_id,
           oh.accounting_unit_level,
           oh.accounting_unit_number
    FROM   store_ancestors sa
    JOIN   configadm.org_hierarchy_detail ohd
           ON ohd.org_hierarchy_id = sa.org_hierarchy_id
    JOIN   configadm.org_hierarchy oh
           ON oh.org_hierarchy_id = ohd.parent_org_hierarchy_id
),

store_geo AS (
    SELECT sp.abbreviation  AS state_code,
           ctry.abbreviation AS country_code
    FROM   configadm.org_hierarchy  oh
    JOIN   configadm.org_attribute  oa   ON oa.org_hierarchy_id  = oh.org_hierarchy_id
    JOIN   configadm.state_province sp   ON sp.state_province_id = oa.state_province_id
    JOIN   configadm.country        ctry ON ctry.country_id      = sp.country_id
    WHERE  oh.accounting_unit_number = %(store_number)s
      AND  oh.accounting_unit_level  = 'STORE'
    LIMIT 1
),

store_company AS (
    SELECT accounting_unit_number AS company_number
    FROM   store_ancestors
    WHERE  accounting_unit_level = 'COMPANY'
    LIMIT 1
),

store_lob AS (
    SELECT lob.ref_code AS lob_code
    FROM   configadm.company_store    cs
    JOIN   configadm.company          co  ON co.company_id           = cs.company_id
    JOIN   configadm.line_of_business lob ON lob.line_of_business_id = co.line_of_business_id
    WHERE  cs.accounting_unit = %(store_number)s
    LIMIT 1
),

all_configs AS (

    -- LEVEL 1: STORE (priority 1)
    SELECT plov.param_value,
           pk.param_key_name,
           pg.param_group_name,
           pcat.param_category_name,
           'STORE'                     AS hierarchy_level,
           1                           AS priority,
           a.association_ref_code,
           pa.association_ref_code     AS parent_association_ref_code,
           plov.active,
           pc.start_date,
           pc.end_date,
           pc.created_by,
           pc.created_date,
           pc.last_modified_by,
           pc.last_modified_date,
           plov.param_config_list_of_value_id
    FROM   configadm.association                a
    JOIN   configadm.association_type           at   ON at.association_type_id = a.association_type_id
                                                     AND at.association_type_name = 'STORE'
    JOIN   configadm.param_config               pc   ON pc.association_id = a.association_id
    JOIN   configadm.param_config_list_of_value plov ON plov.param_config_id = pc.param_config_id
    JOIN   configadm.param_key                  pk   ON pk.param_key_id = pc.param_key_id
    JOIN   configadm.param_group                pg   ON pg.param_group_id = pk.param_group_id
    JOIN   configadm.param_category             pcat ON pcat.param_category_id = pg.param_category_id
    LEFT JOIN configadm.association             pa   ON pa.association_id = pc.parent_association_id
    WHERE  a.association_ref_code = %(store_number)s
      AND  pk.param_key_name     = %(rule_name)s
      AND  plov.active           = 1
      AND  pc.end_date           > CURRENT_DATE

    UNION ALL

    -- LEVEL 2: DISTRICT (priority 2)
    SELECT plov.param_value,
           pk.param_key_name,
           pg.param_group_name,
           pcat.param_category_name,
           'DISTRICT'                  AS hierarchy_level,
           2                           AS priority,
           a.association_ref_code,
           pa.association_ref_code     AS parent_association_ref_code,
           plov.active,
           pc.start_date,
           pc.end_date,
           pc.created_by,
           pc.created_date,
           pc.last_modified_by,
           pc.last_modified_date,
           plov.param_config_list_of_value_id
    FROM   store_ancestors sa
    JOIN   configadm.association                a    ON a.association_ref_code = sa.accounting_unit_number
    JOIN   configadm.association_type           at   ON at.association_type_id = a.association_type_id
                                                     AND at.association_type_name = 'DISTRICT'
    JOIN   configadm.param_config               pc   ON pc.association_id = a.association_id
    JOIN   configadm.param_config_list_of_value plov ON plov.param_config_id = pc.param_config_id
    JOIN   configadm.param_key                  pk   ON pk.param_key_id = pc.param_key_id
    JOIN   configadm.param_group                pg   ON pg.param_group_id = pk.param_group_id
    JOIN   configadm.param_category             pcat ON pcat.param_category_id = pg.param_category_id
    LEFT JOIN configadm.association             pa   ON pa.association_id = pc.parent_association_id
    WHERE  sa.accounting_unit_level = 'DISTRICT'
      AND  pk.param_key_name       = %(rule_name)s
      AND  plov.active             = 1
      AND  pc.end_date             > CURRENT_DATE

    UNION ALL

    -- LEVEL 3: REGION (priority 3)
    SELECT plov.param_value,
           pk.param_key_name,
           pg.param_group_name,
           pcat.param_category_name,
           'REGION'                    AS hierarchy_level,
           3                           AS priority,
           a.association_ref_code,
           pa.association_ref_code     AS parent_association_ref_code,
           plov.active,
           pc.start_date,
           pc.end_date,
           pc.created_by,
           pc.created_date,
           pc.last_modified_by,
           pc.last_modified_date,
           plov.param_config_list_of_value_id
    FROM   store_ancestors sa
    JOIN   configadm.association                a    ON a.association_ref_code = sa.accounting_unit_number
    JOIN   configadm.association_type           at   ON at.association_type_id = a.association_type_id
                                                     AND at.association_type_name = 'REGION'
    JOIN   configadm.param_config               pc   ON pc.association_id = a.association_id
    JOIN   configadm.param_config_list_of_value plov ON plov.param_config_id = pc.param_config_id
    JOIN   configadm.param_key                  pk   ON pk.param_key_id = pc.param_key_id
    JOIN   configadm.param_group                pg   ON pg.param_group_id = pk.param_group_id
    JOIN   configadm.param_category             pcat ON pcat.param_category_id = pg.param_category_id
    LEFT JOIN configadm.association             pa   ON pa.association_id = pc.parent_association_id
    WHERE  sa.accounting_unit_level = 'REGION'
      AND  pk.param_key_name       = %(rule_name)s
      AND  plov.active             = 1
      AND  pc.end_date             > CURRENT_DATE

    UNION ALL

    -- LEVEL 4: COMPANY+STATE compound (priority 4)
    SELECT plov.param_value,
           pk.param_key_name,
           pg.param_group_name,
           pcat.param_category_name,
           'COMPANY+STATE'             AS hierarchy_level,
           4                           AS priority,
           a.association_ref_code,
           pa.association_ref_code     AS parent_association_ref_code,
           plov.active,
           pc.start_date,
           pc.end_date,
           pc.created_by,
           pc.created_date,
           pc.last_modified_by,
           pc.last_modified_date,
           plov.param_config_list_of_value_id
    FROM   store_geo sg
    CROSS JOIN store_company sc
    JOIN   configadm.association                a    ON a.association_ref_code = sg.state_code
    JOIN   configadm.association_type           at   ON at.association_type_id = a.association_type_id
                                                     AND at.association_type_name = 'STATE'
    JOIN   configadm.param_config               pc   ON pc.association_id = a.association_id
    JOIN   configadm.association                pa   ON pa.association_id = pc.parent_association_id
                                                     AND pa.association_ref_code = sc.company_number
    JOIN   configadm.association_type           pat  ON pat.association_type_id = pa.association_type_id
                                                     AND pat.association_type_name = 'COMPANY'
    JOIN   configadm.param_config_list_of_value plov ON plov.param_config_id = pc.param_config_id
    JOIN   configadm.param_key                  pk   ON pk.param_key_id = pc.param_key_id
    JOIN   configadm.param_group                pg   ON pg.param_group_id = pk.param_group_id
    JOIN   configadm.param_category             pcat ON pcat.param_category_id = pg.param_category_id
    WHERE  pk.param_key_name = %(rule_name)s
      AND  plov.active       = 1
      AND  pc.end_date       > CURRENT_DATE

    UNION ALL

    -- LEVEL 5: STATE pure (priority 5)
    SELECT plov.param_value,
           pk.param_key_name,
           pg.param_group_name,
           pcat.param_category_name,
           'STATE'                     AS hierarchy_level,
           5                           AS priority,
           a.association_ref_code,
           NULL::varchar               AS parent_association_ref_code,
           plov.active,
           pc.start_date,
           pc.end_date,
           pc.created_by,
           pc.created_date,
           pc.last_modified_by,
           pc.last_modified_date,
           plov.param_config_list_of_value_id
    FROM   store_geo sg
    JOIN   configadm.association                a    ON a.association_ref_code = sg.state_code
    JOIN   configadm.association_type           at   ON at.association_type_id = a.association_type_id
                                                     AND at.association_type_name = 'STATE'
    JOIN   configadm.param_config               pc   ON pc.association_id = a.association_id
    JOIN   configadm.param_config_list_of_value plov ON plov.param_config_id = pc.param_config_id
    JOIN   configadm.param_key                  pk   ON pk.param_key_id = pc.param_key_id
    JOIN   configadm.param_group                pg   ON pg.param_group_id = pk.param_group_id
    JOIN   configadm.param_category             pcat ON pcat.param_category_id = pg.param_category_id
    WHERE  pk.param_key_name           = %(rule_name)s
      AND  plov.active                 = 1
      AND  pc.end_date                 > CURRENT_DATE
      AND  pc.parent_association_id IS NULL

    UNION ALL

    -- LEVEL 6: COMPANY pure (priority 6)
    SELECT plov.param_value,
           pk.param_key_name,
           pg.param_group_name,
           pcat.param_category_name,
           'COMPANY'                   AS hierarchy_level,
           6                           AS priority,
           a.association_ref_code,
           NULL::varchar               AS parent_association_ref_code,
           plov.active,
           pc.start_date,
           pc.end_date,
           pc.created_by,
           pc.created_date,
           pc.last_modified_by,
           pc.last_modified_date,
           plov.param_config_list_of_value_id
    FROM   store_company sc
    JOIN   configadm.association                a    ON a.association_ref_code = sc.company_number
    JOIN   configadm.association_type           at   ON at.association_type_id = a.association_type_id
                                                     AND at.association_type_name = 'COMPANY'
    JOIN   configadm.param_config               pc   ON pc.association_id = a.association_id
    JOIN   configadm.param_config_list_of_value plov ON plov.param_config_id = pc.param_config_id
    JOIN   configadm.param_key                  pk   ON pk.param_key_id = pc.param_key_id
    JOIN   configadm.param_group                pg   ON pg.param_group_id = pk.param_group_id
    JOIN   configadm.param_category             pcat ON pcat.param_category_id = pg.param_category_id
    WHERE  pk.param_key_name           = %(rule_name)s
      AND  plov.active                 = 1
      AND  pc.end_date                 > CURRENT_DATE
      AND  pc.parent_association_id IS NULL

    UNION ALL

    -- LEVEL 7: LOB+COUNTRY compound (priority 7)
    -- Joins from the LOB side → does NOT depend on store_geo.
    -- Works even when org_attribute has no entry for the store.
    SELECT plov.param_value,
           pk.param_key_name,
           pg.param_group_name,
           pcat.param_category_name,
           'LOB+COUNTRY'               AS hierarchy_level,
           7                           AS priority,
           a.association_ref_code,
           pa.association_ref_code     AS parent_association_ref_code,
           plov.active,
           pc.start_date,
           pc.end_date,
           pc.created_by,
           pc.created_date,
           pc.last_modified_by,
           pc.last_modified_date,
           plov.param_config_list_of_value_id
    FROM   store_lob sl
    -- start from the LOB association
    JOIN   configadm.association                pa   ON pa.association_ref_code = sl.lob_code
    JOIN   configadm.association_type           pat  ON pat.association_type_id = pa.association_type_id
                                                     AND pat.association_type_name = 'LOB'
    -- param_configs whose parent_association is this LOB
    JOIN   configadm.param_config               pc   ON pc.parent_association_id = pa.association_id
    -- the config's own association must be of type COUNTRY
    JOIN   configadm.association                a    ON a.association_id = pc.association_id
    JOIN   configadm.association_type           at   ON at.association_type_id = a.association_type_id
                                                     AND at.association_type_name = 'COUNTRY'
    JOIN   configadm.param_config_list_of_value plov ON plov.param_config_id = pc.param_config_id
    JOIN   configadm.param_key                  pk   ON pk.param_key_id = pc.param_key_id
    JOIN   configadm.param_group                pg   ON pg.param_group_id = pk.param_group_id
    JOIN   configadm.param_category             pcat ON pcat.param_category_id = pg.param_category_id
    WHERE  pk.param_key_name = %(rule_name)s
      AND  plov.active       = 1
      AND  pc.end_date       > CURRENT_DATE

    UNION ALL

    -- LEVEL 8: COUNTRY pure (priority 8)
    SELECT plov.param_value,
           pk.param_key_name,
           pg.param_group_name,
           pcat.param_category_name,
           'COUNTRY'                   AS hierarchy_level,
           8                           AS priority,
           a.association_ref_code,
           NULL::varchar               AS parent_association_ref_code,
           plov.active,
           pc.start_date,
           pc.end_date,
           pc.created_by,
           pc.created_date,
           pc.last_modified_by,
           pc.last_modified_date,
           plov.param_config_list_of_value_id
    FROM   store_lob sl
    -- reach COUNTRY configs via the store's LOB, but only pure (no parent) ones
    JOIN   configadm.association                pa   ON pa.association_ref_code = sl.lob_code
    JOIN   configadm.association_type           pat  ON pat.association_type_id = pa.association_type_id
                                                     AND pat.association_type_name = 'LOB'
    -- find COUNTRY-type associations
    JOIN   configadm.association_type           at   ON at.association_type_name = 'COUNTRY'
    JOIN   configadm.association                a    ON a.association_type_id = at.association_type_id
    JOIN   configadm.param_config               pc   ON pc.association_id = a.association_id
                                                     AND pc.parent_association_id IS NULL
    JOIN   configadm.param_config_list_of_value plov ON plov.param_config_id = pc.param_config_id
    JOIN   configadm.param_key                  pk   ON pk.param_key_id = pc.param_key_id
    JOIN   configadm.param_group                pg   ON pg.param_group_id = pk.param_group_id
    JOIN   configadm.param_category             pcat ON pcat.param_category_id = pg.param_category_id
    -- Only include countries that are actually associated with this LOB's configs
    -- (i.e. this LOB has at least one LOB+COUNTRY config for this country)
    WHERE  pk.param_key_name           = %(rule_name)s
      AND  plov.active                 = 1
      AND  pc.end_date                 > CURRENT_DATE
      AND  EXISTS (
               SELECT 1
               FROM   configadm.param_config pc2
               JOIN   configadm.param_key    pk2 ON pk2.param_key_id = pc2.param_key_id
               WHERE  pc2.association_id       = a.association_id
                 AND  pc2.parent_association_id = pa.association_id
                 AND  pk2.param_key_name       = %(rule_name)s
           )

    UNION ALL

    -- LEVEL 9: LOB pure (priority 9)
    SELECT plov.param_value,
           pk.param_key_name,
           pg.param_group_name,
           pcat.param_category_name,
           'LOB'                       AS hierarchy_level,
           9                           AS priority,
           a.association_ref_code,
           NULL::varchar               AS parent_association_ref_code,
           plov.active,
           pc.start_date,
           pc.end_date,
           pc.created_by,
           pc.created_date,
           pc.last_modified_by,
           pc.last_modified_date,
           plov.param_config_list_of_value_id
    FROM   store_lob sl
    JOIN   configadm.association                a    ON a.association_ref_code = sl.lob_code
    JOIN   configadm.association_type           at   ON at.association_type_id = a.association_type_id
                                                     AND at.association_type_name = 'LOB'
    JOIN   configadm.param_config               pc   ON pc.association_id = a.association_id
    JOIN   configadm.param_config_list_of_value plov ON plov.param_config_id = pc.param_config_id
    JOIN   configadm.param_key                  pk   ON pk.param_key_id = pc.param_key_id
    JOIN   configadm.param_group                pg   ON pg.param_group_id = pk.param_group_id
    JOIN   configadm.param_category             pcat ON pcat.param_category_id = pg.param_category_id
    WHERE  pk.param_key_name           = %(rule_name)s
      AND  plov.active                 = 1
      AND  pc.end_date                 > CURRENT_DATE
      AND  pc.parent_association_id IS NULL
),

ranked AS (
    SELECT ac.*,
           ROW_NUMBER() OVER (ORDER BY ac.priority ASC) AS rn
    FROM   all_configs ac
)

SELECT r.param_value                AS current_value,
       prev_aud.param_value         AS previous_value,
       r.param_key_name,
       r.param_group_name,
       r.param_category_name,
       r.hierarchy_level,
       r.priority,
       (r.rn = 1)                   AS is_effective,
       r.association_ref_code,
       r.parent_association_ref_code,
       r.active,
       r.start_date,
       r.end_date,
       r.created_by,
       r.created_date,
       r.last_modified_by,
       r.last_modified_date,
       prev_aud.last_modified_by    AS prev_modified_by,
       prev_aud.last_modified_date  AS prev_modified_date,
       r.param_config_list_of_value_id
FROM   ranked r
LEFT JOIN LATERAL (
    SELECT aud.param_value,
           aud.last_modified_by,
           aud.last_modified_date
    FROM   configadm.aud_param_config_list_of_value aud
    WHERE  aud.param_config_list_of_value_id = r.param_config_list_of_value_id
    ORDER  BY aud.last_modified_date DESC
    LIMIT  1
) prev_aud ON true
ORDER BY r.priority ASC
"""

# ─────────────────────────────────────────────────────────────────────────────
# Query 1b — Direct District Lookup
# Input: %(rule_name)s, %(district_code)s (e.g. 'M0330')
# ─────────────────────────────────────────────────────────────────────────────

QUERY_DIRECT_DISTRICT = """
SELECT plov.param_value              AS current_value,
       prev_aud.param_value          AS previous_value,
       pk.param_key_name,
       pg.param_group_name,
       pcat.param_category_name,
       at.association_type_name      AS hierarchy_level,
       NULL::int                     AS priority,
       NULL::boolean                 AS is_effective,
       a.association_ref_code,
       pa.association_ref_code       AS parent_association_ref_code,
       plov.active,
       pc.start_date,
       pc.end_date,
       pc.created_by,
       pc.created_date,
       pc.last_modified_by,
       pc.last_modified_date,
       prev_aud.last_modified_by     AS prev_modified_by,
       prev_aud.last_modified_date   AS prev_modified_date,
       plov.param_config_list_of_value_id
FROM   configadm.association                a
JOIN   configadm.association_type           at   ON at.association_type_id = a.association_type_id
                                                 AND at.association_type_name = 'DISTRICT'
JOIN   configadm.param_config               pc   ON pc.association_id = a.association_id
JOIN   configadm.param_config_list_of_value plov ON plov.param_config_id = pc.param_config_id
JOIN   configadm.param_key                  pk   ON pk.param_key_id = pc.param_key_id
JOIN   configadm.param_group                pg   ON pg.param_group_id = pk.param_group_id
JOIN   configadm.param_category             pcat ON pcat.param_category_id = pg.param_category_id
LEFT JOIN configadm.association             pa   ON pa.association_id = pc.parent_association_id
LEFT JOIN LATERAL (
    SELECT aud.param_value, aud.last_modified_by, aud.last_modified_date
    FROM   configadm.aud_param_config_list_of_value aud
    WHERE  aud.param_config_list_of_value_id = plov.param_config_list_of_value_id
    ORDER  BY aud.last_modified_date DESC
    LIMIT  1
) prev_aud ON true
WHERE  a.association_ref_code = %(district_code)s
  AND  pk.param_key_name     = %(rule_name)s
  AND  plov.active           = 1
  AND  pc.end_date           > CURRENT_DATE
"""

# ─────────────────────────────────────────────────────────────────────────────
# Query 1c — Direct Region Lookup
# Input: %(rule_name)s, %(region_code)s
# ─────────────────────────────────────────────────────────────────────────────

QUERY_DIRECT_REGION = """
SELECT plov.param_value              AS current_value,
       prev_aud.param_value          AS previous_value,
       pk.param_key_name,
       pg.param_group_name,
       pcat.param_category_name,
       at.association_type_name      AS hierarchy_level,
       NULL::int                     AS priority,
       NULL::boolean                 AS is_effective,
       a.association_ref_code,
       pa.association_ref_code       AS parent_association_ref_code,
       plov.active,
       pc.start_date,
       pc.end_date,
       pc.created_by,
       pc.created_date,
       pc.last_modified_by,
       pc.last_modified_date,
       prev_aud.last_modified_by     AS prev_modified_by,
       prev_aud.last_modified_date   AS prev_modified_date,
       plov.param_config_list_of_value_id
FROM   configadm.association                a
JOIN   configadm.association_type           at   ON at.association_type_id = a.association_type_id
                                                 AND at.association_type_name = 'REGION'
JOIN   configadm.param_config               pc   ON pc.association_id = a.association_id
JOIN   configadm.param_config_list_of_value plov ON plov.param_config_id = pc.param_config_id
JOIN   configadm.param_key                  pk   ON pk.param_key_id = pc.param_key_id
JOIN   configadm.param_group                pg   ON pg.param_group_id = pk.param_group_id
JOIN   configadm.param_category             pcat ON pcat.param_category_id = pg.param_category_id
LEFT JOIN configadm.association             pa   ON pa.association_id = pc.parent_association_id
LEFT JOIN LATERAL (
    SELECT aud.param_value, aud.last_modified_by, aud.last_modified_date
    FROM   configadm.aud_param_config_list_of_value aud
    WHERE  aud.param_config_list_of_value_id = plov.param_config_list_of_value_id
    ORDER  BY aud.last_modified_date DESC
    LIMIT  1
) prev_aud ON true
WHERE  a.association_ref_code = %(region_code)s
  AND  pk.param_key_name     = %(rule_name)s
  AND  plov.active           = 1
  AND  pc.end_date           > CURRENT_DATE
"""

# ─────────────────────────────────────────────────────────────────────────────
# Query 2 — Direct Company Lookup
# ─────────────────────────────────────────────────────────────────────────────

QUERY_DIRECT_COMPANY = """
SELECT plov.param_value              AS current_value,
       prev_aud.param_value          AS previous_value,
       pk.param_key_name,
       pg.param_group_name,
       pcat.param_category_name,
       at.association_type_name      AS hierarchy_level,
       NULL::int                     AS priority,
       NULL::boolean                 AS is_effective,
       a.association_ref_code,
       pa.association_ref_code       AS parent_association_ref_code,
       plov.active,
       pc.start_date,
       pc.end_date,
       pc.created_by,
       pc.created_date,
       pc.last_modified_by,
       pc.last_modified_date,
       prev_aud.last_modified_by     AS prev_modified_by,
       prev_aud.last_modified_date   AS prev_modified_date,
       plov.param_config_list_of_value_id
FROM   configadm.association                a
JOIN   configadm.association_type           at   ON at.association_type_id = a.association_type_id
                                                 AND at.association_type_name = 'COMPANY'
JOIN   configadm.param_config               pc   ON pc.association_id = a.association_id
JOIN   configadm.param_config_list_of_value plov ON plov.param_config_id = pc.param_config_id
JOIN   configadm.param_key                  pk   ON pk.param_key_id = pc.param_key_id
JOIN   configadm.param_group                pg   ON pg.param_group_id = pk.param_group_id
JOIN   configadm.param_category             pcat ON pcat.param_category_id = pg.param_category_id
LEFT JOIN configadm.association             pa   ON pa.association_id = pc.parent_association_id
LEFT JOIN LATERAL (
    SELECT aud.param_value, aud.last_modified_by, aud.last_modified_date
    FROM   configadm.aud_param_config_list_of_value aud
    WHERE  aud.param_config_list_of_value_id = plov.param_config_list_of_value_id
    ORDER  BY aud.last_modified_date DESC
    LIMIT  1
) prev_aud ON true
WHERE  a.association_ref_code = %(company_code)s
  AND  pk.param_key_name     = %(rule_name)s
  AND  plov.active           = 1
  AND  pc.end_date           > CURRENT_DATE
"""

# ─────────────────────────────────────────────────────────────────────────────
# Query 3 — Direct State Lookup
# ─────────────────────────────────────────────────────────────────────────────

QUERY_DIRECT_STATE = """
SELECT plov.param_value              AS current_value,
       prev_aud.param_value          AS previous_value,
       pk.param_key_name,
       pg.param_group_name,
       pcat.param_category_name,
       at.association_type_name      AS hierarchy_level,
       NULL::int                     AS priority,
       NULL::boolean                 AS is_effective,
       a.association_ref_code,
       pa.association_ref_code       AS parent_association_ref_code,
       plov.active,
       pc.start_date,
       pc.end_date,
       pc.created_by,
       pc.created_date,
       pc.last_modified_by,
       pc.last_modified_date,
       prev_aud.last_modified_by     AS prev_modified_by,
       prev_aud.last_modified_date   AS prev_modified_date,
       plov.param_config_list_of_value_id
FROM   configadm.association                a
JOIN   configadm.association_type           at   ON at.association_type_id = a.association_type_id
                                                 AND at.association_type_name = 'STATE'
JOIN   configadm.param_config               pc   ON pc.association_id = a.association_id
JOIN   configadm.param_config_list_of_value plov ON plov.param_config_id = pc.param_config_id
JOIN   configadm.param_key                  pk   ON pk.param_key_id = pc.param_key_id
JOIN   configadm.param_group                pg   ON pg.param_group_id = pk.param_group_id
JOIN   configadm.param_category             pcat ON pcat.param_category_id = pg.param_category_id
LEFT JOIN configadm.association             pa   ON pa.association_id = pc.parent_association_id
LEFT JOIN LATERAL (
    SELECT aud.param_value, aud.last_modified_by, aud.last_modified_date
    FROM   configadm.aud_param_config_list_of_value aud
    WHERE  aud.param_config_list_of_value_id = plov.param_config_list_of_value_id
    ORDER  BY aud.last_modified_date DESC
    LIMIT  1
) prev_aud ON true
WHERE  a.association_ref_code = %(state_code)s
  AND  pk.param_key_name     = %(rule_name)s
  AND  plov.active           = 1
  AND  pc.end_date           > CURRENT_DATE
"""

# ─────────────────────────────────────────────────────────────────────────────
# Query 4 — Direct Country Lookup
# ─────────────────────────────────────────────────────────────────────────────

QUERY_DIRECT_COUNTRY = """
SELECT plov.param_value              AS current_value,
       prev_aud.param_value          AS previous_value,
       pk.param_key_name,
       pg.param_group_name,
       pcat.param_category_name,
       at.association_type_name      AS hierarchy_level,
       NULL::int                     AS priority,
       NULL::boolean                 AS is_effective,
       a.association_ref_code,
       pa.association_ref_code       AS parent_association_ref_code,
       plov.active,
       pc.start_date,
       pc.end_date,
       pc.created_by,
       pc.created_date,
       pc.last_modified_by,
       pc.last_modified_date,
       prev_aud.last_modified_by     AS prev_modified_by,
       prev_aud.last_modified_date   AS prev_modified_date,
       plov.param_config_list_of_value_id
FROM   configadm.association                a
JOIN   configadm.association_type           at   ON at.association_type_id = a.association_type_id
                                                 AND at.association_type_name = 'COUNTRY'
JOIN   configadm.param_config               pc   ON pc.association_id = a.association_id
JOIN   configadm.param_config_list_of_value plov ON plov.param_config_id = pc.param_config_id
JOIN   configadm.param_key                  pk   ON pk.param_key_id = pc.param_key_id
JOIN   configadm.param_group                pg   ON pg.param_group_id = pk.param_group_id
JOIN   configadm.param_category             pcat ON pcat.param_category_id = pg.param_category_id
LEFT JOIN configadm.association             pa   ON pa.association_id = pc.parent_association_id
LEFT JOIN LATERAL (
    SELECT aud.param_value, aud.last_modified_by, aud.last_modified_date
    FROM   configadm.aud_param_config_list_of_value aud
    WHERE  aud.param_config_list_of_value_id = plov.param_config_list_of_value_id
    ORDER  BY aud.last_modified_date DESC
    LIMIT  1
) prev_aud ON true
WHERE  a.association_ref_code = %(country_code)s
  AND  pk.param_key_name     = %(rule_name)s
  AND  plov.active           = 1
  AND  pc.end_date           > CURRENT_DATE
"""

# ─────────────────────────────────────────────────────────────────────────────
# Query 5 — Direct LOB Lookup
# ─────────────────────────────────────────────────────────────────────────────

QUERY_DIRECT_LOB = """
SELECT plov.param_value              AS current_value,
       prev_aud.param_value          AS previous_value,
       pk.param_key_name,
       pg.param_group_name,
       pcat.param_category_name,
       at.association_type_name      AS hierarchy_level,
       NULL::int                     AS priority,
       NULL::boolean                 AS is_effective,
       a.association_ref_code,
       pa.association_ref_code       AS parent_association_ref_code,
       plov.active,
       pc.start_date,
       pc.end_date,
       pc.created_by,
       pc.created_date,
       pc.last_modified_by,
       pc.last_modified_date,
       prev_aud.last_modified_by     AS prev_modified_by,
       prev_aud.last_modified_date   AS prev_modified_date,
       plov.param_config_list_of_value_id
FROM   configadm.association                a
JOIN   configadm.association_type           at   ON at.association_type_id = a.association_type_id
                                                 AND at.association_type_name = 'LOB'
JOIN   configadm.param_config               pc   ON pc.association_id = a.association_id
JOIN   configadm.param_config_list_of_value plov ON plov.param_config_id = pc.param_config_id
JOIN   configadm.param_key                  pk   ON pk.param_key_id = pc.param_key_id
JOIN   configadm.param_group                pg   ON pg.param_group_id = pk.param_group_id
JOIN   configadm.param_category             pcat ON pcat.param_category_id = pg.param_category_id
LEFT JOIN configadm.association             pa   ON pa.association_id = pc.parent_association_id
LEFT JOIN LATERAL (
    SELECT aud.param_value, aud.last_modified_by, aud.last_modified_date
    FROM   configadm.aud_param_config_list_of_value aud
    WHERE  aud.param_config_list_of_value_id = plov.param_config_list_of_value_id
    ORDER  BY aud.last_modified_date DESC
    LIMIT  1
) prev_aud ON true
WHERE  a.association_ref_code = %(lob_code)s
  AND  pk.param_key_name     = %(rule_name)s
  AND  plov.active           = 1
  AND  pc.end_date           > CURRENT_DATE
  AND  pc.parent_association_id IS NULL
"""

# ─────────────────────────────────────────────────────────────────────────────
# Mapping: scope_type → (query, param_key_for_scope_value)
# ─────────────────────────────────────────────────────────────────────────────

SCOPE_QUERY_MAP = {
    "STORE":    (QUERY_STORE_HIERARCHY,  "store_number"),
    "DISTRICT": (QUERY_DIRECT_DISTRICT, "district_code"),
    "REGION":   (QUERY_DIRECT_REGION,   "region_code"),
    "COMPANY":  (QUERY_DIRECT_COMPANY,  "company_code"),
    "STATE":    (QUERY_DIRECT_STATE,    "state_code"),
    "COUNTRY":  (QUERY_DIRECT_COUNTRY,  "country_code"),
    "LOB":      (QUERY_DIRECT_LOB,      "lob_code"),
}

# ─────────────────────────────────────────────────────────────────────────────
# Scope-list queries — return all active associations for a given hierarchy
# type (for populating dropdowns and generating downloadable lists).
# ─────────────────────────────────────────────────────────────────────────────

# Single-type list: pass %(scope_type)s  e.g. 'STORE'
QUERY_LIST_BY_TYPE = """
SELECT
    a.association_id,
    a.association_ref_code   AS code,
    a.association_name       AS name,
    a.association_desc       AS description,
    at.association_type_name AS hierarchy_type
FROM configadm.association a
JOIN configadm.association_type at
    ON at.association_type_id = a.association_type_id
WHERE at.association_type_name = %(scope_type)s
ORDER BY a.association_ref_code;
"""

# All types in one query — results grouped by display_seq then code.
QUERY_LIST_ALL = """
SELECT
    at.association_type_name AS hierarchy_type,
    at.display_value         AS hierarchy_display_name,
    at.display_seq,
    a.association_id,
    a.association_ref_code   AS code,
    a.association_name       AS name,
    a.association_desc       AS description
FROM configadm.association a
JOIN configadm.association_type at
    ON at.association_type_id = a.association_type_id
WHERE at.association_type_name IN ('STORE', 'DISTRICT', 'REGION', 'STATE', 'COMPANY', 'COUNTRY', 'LOB')
ORDER BY at.display_seq, a.association_ref_code;
"""

# Allowed scope types for the scope-list endpoint
SCOPE_LIST_ALLOWED = {"STORE", "DISTRICT", "REGION", "STATE", "COMPANY", "COUNTRY", "LOB"}
