"""
diagnostics.py — PO622 Diagnostic Engine.

Executes diagnostic queries against the RAC DB and determines
the root cause of PO622 ("Unable to receive purchase order") errors.
"""

from db import execute_query
import queries


class PO622Diagnostic:
    """Run PO622 diagnostic queries and determine root cause."""

    def __init__(self, rac_conn):
        self.conn = rac_conn

    def run(self, po_number: str, store_number: str) -> dict:
        """Execute all diagnostic queries and return a structured result dict."""
        params = {"po_number": po_number, "store_number": store_number}

        overview = execute_query(self.conn, queries.PO_OVERVIEW, params)
        line_items = execute_query(self.conn, queries.PO_LINE_ITEM_STATUS, params)
        duplicate_serials = execute_query(self.conn, queries.PO_DUPLICATE_SERIAL, params)
        concurrency_issues = execute_query(self.conn, queries.PO_CONCURRENCY, params)
        timeline = execute_query(self.conn, queries.PO_TIMELINE, params)

        result = {
            "po_number": po_number,
            "store_number": store_number,
            "overview": overview,
            "line_items": line_items,
            "duplicate_serials": duplicate_serials,
            "concurrency_issues": concurrency_issues,
            "timeline": timeline,
            "root_cause": [],
        }

        result["root_cause"] = self._determine_root_cause(result)
        return result

    def _determine_root_cause(self, result: dict) -> list[dict]:
        """Analyze query results and return a list of root cause dicts."""
        causes = []

        for item in result["line_items"]:
            remaining = item.get("remaining_to_receive", 1)
            if remaining is not None and remaining <= 0:
                causes.append({
                    "type": "ALREADY_FULLY_RECEIVED",
                    "item": item.get("rms_item_number"),
                    "detail": (
                        f"Line {item.get('purchase_order_line_number')}: "
                        f"qty ordered={item.get('quantity_ordered')}, "
                        f"fully received={item.get('fully_received_count')}, "
                        f"remaining={remaining}"
                    ),
                    "action": "Reverse one of the duplicate/extra receives to free up capacity.",
                })

            stuck = item.get("stuck_reversal_count", 0)
            if stuck and stuck > 0:
                causes.append({
                    "type": "STUCK_REVERSAL",
                    "item": item.get("rms_item_number"),
                    "detail": (
                        f"Line {item.get('purchase_order_line_number')}: "
                        f"{stuck} receive(s) have reversal_date set but "
                        f"reversal_status_type_id is NULL."
                    ),
                    "action": "DB team must update reversal_status_type_id to complete the reversal.",
                })

        for dup in result["duplicate_serials"]:
            causes.append({
                "type": "DUPLICATE_SERIAL_NUMBER",
                "item": dup.get("rms_item_number"),
                "detail": (
                    f"Serial '{dup.get('manufacturer_serial_number')}' "
                    f"used {dup.get('times_used')} times."
                ),
                "action": "Reverse the duplicate receive entry.",
            })

        for conc in result["concurrency_issues"]:
            causes.append({
                "type": "CONCURRENT_RECEIVE",
                "item": conc.get("rms_item_number"),
                "detail": (
                    f"Receives {conc.get('receive_id_1')} and {conc.get('receive_id_2')} "
                    f"are {conc.get('seconds_apart')}s apart "
                    f"(users: {conc.get('user_1')}, {conc.get('user_2')})."
                ),
                "action": "Verify and reverse if duplicate.",
            })

        if not causes:
            causes.append({
                "type": "NO_ISSUE_FOUND",
                "item": None,
                "detail": "No PO622 root cause detected from available data.",
                "action": "Escalate to engineering for further investigation.",
            })

        return causes
