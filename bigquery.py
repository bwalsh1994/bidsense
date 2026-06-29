import logging
import json
from datetime import datetime, timezone
from google.cloud import bigquery

log = logging.getLogger(__name__)

PROJECT   = "ai-campaign-safety-layer"
DATASET   = "bidsense"
BQ_CLIENT = bigquery.Client(project=PROJECT)

def get_spend_rules(client_account_id: str) -> list:
    query = f"""
        SELECT rule_name, rule_value, rule_action
        FROM `{PROJECT}.{DATASET}.rules_config`
        WHERE client_account_id = @account_id
          AND rule_category = 'spend_controls'
          AND is_active = TRUE
        ORDER BY rule_name
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("account_id", "STRING", client_account_id)
        ]
    )
    results = BQ_CLIENT.query(query, job_config=job_config).result()
    rules = [dict(row) for row in results]
    log.info(f"Loaded {len(rules)} spend rules for {client_account_id}")
    return rules

def get_client_name(client_account_id: str) -> str:
    query = f"""
        SELECT DISTINCT client_name
        FROM `{PROJECT}.{DATASET}.rules_config`
        WHERE client_account_id = @account_id
        LIMIT 1
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("account_id", "STRING", client_account_id)
        ]
    )
    results = list(BQ_CLIENT.query(query, job_config=job_config).result())
    return results[0]["client_name"] if results else client_account_id

def write_audit_log(
    action_id: str,
    client_account_id: str,
    client_name: str,
    agent_instruction: str,
    proposed_action: dict,
    rules_evaluated: list,
    rule_triggered: str,
    outcome: str,
    spend_value: float,
    spend_protected: float,
    observe_mode: bool
):
    table_id = f"{PROJECT}.{DATASET}.audit_log"
    rows = [{
        "action_id":          action_id,
        "timestamp":          datetime.now(timezone.utc).isoformat(),
        "client_account_id":  client_account_id,
        "client_name":        client_name,
        "platform":           "META",
        "agent_instruction":  agent_instruction,
        "proposed_action":    json.dumps(proposed_action),
        "rules_evaluated":    json.dumps(rules_evaluated),
        "rule_triggered":     rule_triggered,
        "outcome":            outcome,
        "reviewer_id":        None,
        "reviewer_decision":  None,
        "reviewer_timestamp": None,
        "execution_status":   "PENDING" if outcome == "APPROVED" else None,
        "platform_response":  None,
        "spend_value":        spend_value,
        "spend_protected":    spend_protected if outcome in ["BLOCKED", "BLOCK"] else 0.0,
        "observe_mode":       observe_mode
    }]
    errors = BQ_CLIENT.insert_rows_json(table_id, rows)
    if errors:
        log.error(f"Audit log write error: {errors}")
    else:
        log.info(f"Audit log written: {action_id} → {outcome}")