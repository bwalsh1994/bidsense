import logging
from datetime import datetime, timezone
from google.cloud import firestore

log = logging.getLogger(__name__)

FS_CLIENT = firestore.Client(project="ai-campaign-safety-layer")

def write_approval_queue(
    action_id: str,
    client_account_id: str,
    client_name: str,
    rule_triggered: str,
    reason: str,
    proposed_action: dict,
    spend_value: float,
    agent_instruction: str
):
    doc = {
        "action_id":          action_id,
        "client_account_id":  client_account_id,
        "client_name":        client_name,
        "rule_triggered":     rule_triggered,
        "reason":             reason,
        "proposed_action":    proposed_action,
        "spend_value":        spend_value,
        "agent_instruction":  agent_instruction,
        "status":             "PENDING",
        "created_at":         datetime.now(timezone.utc),
        "reviewed_at":        None,
        "reviewer_id":        None,
        "reviewer_decision":  None
    }
    FS_CLIENT.collection("approval_queue").document(action_id).set(doc)
    log.info(f"Approval queue entry written: {action_id}")