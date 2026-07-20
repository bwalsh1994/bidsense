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
def get_pending_approvals() -> list:
    """Returns pending items from the Firestore approval queue."""
    try:
        docs = DB.collection("approval_queue").where("status", "==", "PENDING").stream()
        items = []
        for doc in docs:
            data = doc.to_dict()
            items.append({
                "id": doc.id,
                "action_id": data.get("action_id"),
                "client_name": data.get("client_name"),
                "campaign_name": data.get("proposed_action", {}).get("name", "Unknown"),
                "rule_triggered": data.get("rule_triggered"),
                "reason": data.get("reason"),
                "spend_value": data.get("spend_value", 0),
                "agent_instruction": data.get("agent_instruction"),
                "created_at": str(data.get("created_at", ""))
            })
        return items
    except Exception as e:
        log.error(f"Error fetching approval queue: {e}")
        return []