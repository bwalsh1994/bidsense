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

def get_audience_rules(client_account_id: str) -> list:
    """Fetch active audience rules for a client from BigQuery."""
    query = f"""
        SELECT rule_name, rule_value, rule_action
        FROM `{PROJECT}.{DATASET}.rules_config`
        WHERE client_account_id = @account_id
          AND rule_category = 'audience_rules'
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
    log.info(f"Loaded {len(rules)} audience rules for {client_account_id}")
    return rules

def get_campaign_structure_rules(client_account_id: str) -> list:
    """Fetch active campaign structure rules for a client from BigQuery."""
    query = f"""
        SELECT rule_name, rule_value, rule_action
        FROM `{PROJECT}.{DATASET}.rules_config`
        WHERE client_account_id = @account_id
          AND rule_category = 'campaign_structure'
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
    log.info(f"Loaded {len(rules)} structure rules for {client_account_id}")
    return rules


def get_recent_campaigns(client_account_id: str, days: int = 30) -> list:
    """Fetch recent campaigns from audit log for duplicate detection."""
    query = f"""
        SELECT
            JSON_VALUE(proposed_action, '$.name') as name,
            JSON_VALUE(proposed_action, '$.objective') as objective,
            timestamp
        FROM `{PROJECT}.{DATASET}.audit_log`
        WHERE client_account_id = @account_id
          AND outcome = 'APPROVED'
          AND timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @days DAY)
          AND JSON_VALUE(proposed_action, '$.action') = 'create_campaign'
        ORDER BY timestamp DESC
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("account_id", "STRING", client_account_id),
            bigquery.ScalarQueryParameter("days", "INT64", days)
        ]
    )
    results = BQ_CLIENT.query(query, job_config=job_config).result()
    campaigns = [dict(row) for row in results]
    log.info(f"Loaded {len(campaigns)} recent campaigns for duplicate check")
    return campaigns

def get_creative_rules(client_account_id: str) -> list:
    """Fetch active creative rules for a client from BigQuery."""
    query = f"""
        SELECT rule_name, rule_value, rule_action
        FROM `{PROJECT}.{DATASET}.rules_config`
        WHERE client_account_id = @account_id
          AND rule_category = 'creative_rules'
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
    log.info(f"Loaded {len(rules)} creative rules for {client_account_id}")
    return rules


def lookup_creative(client_account_id: str, image_hash: str) -> dict:
    """Look up a creative asset by hash in the approved library."""
    query = f"""
        SELECT asset_id, asset_name, asset_type, format, campaign_type,
               is_approved, approved_by, expires_at
        FROM `{PROJECT}.{DATASET}.creative_library`
        WHERE client_account_id = @account_id
          AND meta_image_hash = @image_hash
        LIMIT 1
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("account_id", "STRING", client_account_id),
            bigquery.ScalarQueryParameter("image_hash", "STRING", image_hash)
        ]
    )
    results = list(BQ_CLIENT.query(query, job_config=job_config).result())
    if results:
        log.info(f"Creative found: {results[0]['asset_name']}")
        return dict(results[0])
    log.warning(f"Creative hash {image_hash} not found in library")
    return {}