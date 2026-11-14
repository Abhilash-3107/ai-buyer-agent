"""Authority: a valid PO is either auto-submitted or needs a human. Separate from validity on purpose."""
from __future__ import annotations

from .types import ApprovalDecision

APPROVAL_THRESHOLD_USD = 2000.0


def approval_for(po_value: float) -> ApprovalDecision:
    if po_value > APPROVAL_THRESHOLD_USD:
        return ApprovalDecision(False, f"PO value ${po_value:,.0f} exceeds auto-approval limit ${APPROVAL_THRESHOLD_USD:,.0f}")
    return ApprovalDecision(True, f"PO value ${po_value:,.0f} is within the auto-approval limit ${APPROVAL_THRESHOLD_USD:,.0f}")
