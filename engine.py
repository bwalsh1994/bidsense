import logging
import uuid
from bigquery import get_spend_rules, get_audience_rules, get_campaign_structure_rules, get_recent_campaigns, get_client_name, write_audit_log
from firestore import write_approval_queue
from notify import send_flag_notification, send_block_notification

log = logging.getLogger(__name__)

OBSERVE_MODE = False


def pence_to_pounds(pence: int) -> float:
    return round(pence / 100, 2)


def evaluate_spend_controls(rules: list, proposed_action: dict) -> dict:
    daily_budget_pence = proposed_action.get("daily_budget_pence", 0)
    lifetime_budget_pence = proposed_action.get("lifetime_budget_pence", 0)
    rules_evaluated = []
    final_outcome = "APPROVED"
    rule_triggered = None
    reason = None

    rule_map = {r["rule_name"]: r for r in rules}

    if "max_daily_budget_pence" in rule_map and daily_budget_pence > 0:
        cap = int(rule_map["max_daily_budget_pence"]["rule_value"])
        action = rule_map["max_daily_budget_pence"]["rule_action"]
        passed = daily_budget_pence <= cap
        rules_evaluated.append({
            "rule": "max_daily_budget_pence",
            "cap_pence": cap,
            "proposed_pence": daily_budget_pence,
            "passed": passed,
            "action_if_fail": action
        })
        if not passed and final_outcome != "BLOCK":
            final_outcome = action
            rule_triggered = "spend_controls.max_daily_budget_pence"
            reason = (
                f"Daily budget £{pence_to_pounds(daily_budget_pence):,.2f} "
                f"exceeds client cap of £{pence_to_pounds(cap):,.2f}"
            )

    if "review_threshold_pence" in rule_map and daily_budget_pence > 0 and final_outcome == "APPROVED":
        threshold = int(rule_map["review_threshold_pence"]["rule_value"])
        passed = daily_budget_pence <= threshold
        rules_evaluated.append({
            "rule": "review_threshold_pence",
            "threshold_pence": threshold,
            "proposed_pence": daily_budget_pence,
            "passed": passed,
            "action_if_fail": "FLAG"
        })
        if not passed:
            final_outcome = "FLAG"
            rule_triggered = "spend_controls.review_threshold_pence"
            reason = (
                f"Daily budget £{pence_to_pounds(daily_budget_pence):,.2f} "
                f"exceeds review threshold of £{pence_to_pounds(threshold):,.2f}"
            )

    if "max_creation_budget_pence" in rule_map and lifetime_budget_pence > 0:
        cap = int(rule_map["max_creation_budget_pence"]["rule_value"])
        action = rule_map["max_creation_budget_pence"]["rule_action"]
        passed = lifetime_budget_pence <= cap
        rules_evaluated.append({
            "rule": "max_creation_budget_pence",
            "cap_pence": cap,
            "proposed_pence": lifetime_budget_pence,
            "passed": passed,
            "action_if_fail": action
        })
        if not passed and final_outcome not in ["BLOCK", "FLAG"]:
            final_outcome = action
            rule_triggered = "spend_controls.max_creation_budget_pence"
            reason = (
                f"Lifetime budget £{pence_to_pounds(lifetime_budget_pence):,.2f} "
                f"exceeds client cap of £{pence_to_pounds(cap):,.2f}"
            )

    return {
        "outcome": final_outcome,
        "rule_triggered": rule_triggered,
        "reason": reason,
        "rules_evaluated": rules_evaluated
    }

def evaluate_audience_rules(rules: list, proposed_action: dict) -> dict:
    """
    Evaluate audience rules against a proposed action.
    Checks minimum audience size and required exclusion lists.
    """
    estimated_audience_size = proposed_action.get("estimated_audience_size", None)
    exclusion_list = proposed_action.get("exclusion_list", [])
    rules_evaluated = []
    final_outcome = "APPROVED"
    rule_triggered = None
    reason = None

    rule_map = {r["rule_name"]: r for r in rules}

    # ── Rule 1: min_audience_size (hard block) ────────────────────────────────
    if "min_audience_size" in rule_map and estimated_audience_size is not None:
        min_size = int(rule_map["min_audience_size"]["rule_value"])
        action = rule_map["min_audience_size"]["rule_action"]
        passed = estimated_audience_size >= min_size
        rules_evaluated.append({
            "rule": "min_audience_size",
            "min_size": min_size,
            "proposed_size": estimated_audience_size,
            "passed": passed,
            "action_if_fail": action
        })
        if not passed and final_outcome != "BLOCK":
            final_outcome = action
            rule_triggered = "audience_rules.min_audience_size"
            reason = (
                f"Estimated audience size {estimated_audience_size:,} "
                f"is below minimum of {min_size:,}"
            )

    # ── Rule 2: min_audience_size_flag (review threshold) ────────────────────
    if "min_audience_size_flag" in rule_map and estimated_audience_size is not None and final_outcome == "APPROVED":
        flag_size = int(rule_map["min_audience_size_flag"]["rule_value"])
        passed = estimated_audience_size >= flag_size
        rules_evaluated.append({
            "rule": "min_audience_size_flag",
            "flag_size": flag_size,
            "proposed_size": estimated_audience_size,
            "passed": passed,
            "action_if_fail": "FLAG"
        })
        if not passed:
            final_outcome = "FLAG"
            rule_triggered = "audience_rules.min_audience_size_flag"
            reason = (
                f"Estimated audience size {estimated_audience_size:,} "
                f"is below review threshold of {flag_size:,}"
            )

    # ── Rule 3: require_exclusion_list ────────────────────────────────────────
    if "require_exclusion_list" in rule_map:
        required = rule_map["require_exclusion_list"]["rule_value"].lower() == "true"
        action = rule_map["require_exclusion_list"]["rule_action"]
        passed = not required or len(exclusion_list) > 0
        rules_evaluated.append({
            "rule": "require_exclusion_list",
            "required": required,
            "exclusions_present": len(exclusion_list),
            "passed": passed,
            "action_if_fail": action
        })
        if not passed and final_outcome not in ["BLOCK", "FLAG"]:
            final_outcome = action
            rule_triggered = "audience_rules.require_exclusion_list"
            reason = "No exclusion list present — required for all campaigns"

    return {
        "outcome": final_outcome,
        "rule_triggered": rule_triggered,
        "reason": reason,
        "rules_evaluated": rules_evaluated
    }
def evaluate_campaign_structure(rules: list, proposed_action: dict, recent_campaigns: list) -> dict:
    """
    Evaluate campaign structure rules against a proposed action.
    Checks objective whitelist, duplicate detection, and naming convention.
    """
    campaign_name = proposed_action.get("name", "")
    objective = proposed_action.get("objective", "")
    rules_evaluated = []
    final_outcome = "APPROVED"
    rule_triggered = None
    reason = None

    rule_map = {r["rule_name"]: r for r in rules}

    # ── Rule 1: objective_whitelist ───────────────────────────────────────────
    if "objective_whitelist" in rule_map and objective:
        permitted = [o.strip() for o in rule_map["objective_whitelist"]["rule_value"].split(",")]
        action = rule_map["objective_whitelist"]["rule_action"]
        passed = objective in permitted
        rules_evaluated.append({
            "rule": "objective_whitelist",
            "permitted": permitted,
            "proposed_objective": objective,
            "passed": passed,
            "action_if_fail": action
        })
        if not passed and final_outcome != "BLOCK":
            final_outcome = action
            rule_triggered = "campaign_structure.objective_whitelist"
            reason = (
                f"Objective {objective} is not permitted for this client. "
                f"Permitted: {', '.join(permitted)}"
            )

    # ── Rule 2: duplicate_detection ───────────────────────────────────────────
    if "duplicate_detection_days" in rule_map and final_outcome == "APPROVED":
        days = int(rule_map["duplicate_detection_days"]["rule_value"])
        duplicates = [
            c for c in recent_campaigns
            if c.get("name", "").lower() == campaign_name.lower()
            and c.get("objective", "") == objective
        ]
        passed = len(duplicates) == 0
        rules_evaluated.append({
            "rule": "duplicate_detection",
            "window_days": days,
            "duplicates_found": len(duplicates),
            "passed": passed,
            "action_if_fail": "FLAG"
        })
        if not passed:
            final_outcome = "FLAG"
            rule_triggered = "campaign_structure.duplicate_detection"
            reason = (
                f"Campaign with name '{campaign_name}' and objective {objective} "
                f"already exists within the last {days} days"
            )

    # ── Rule 3: naming_convention ─────────────────────────────────────────────
    if "naming_convention" in rule_map and final_outcome == "APPROVED":
        required_keyword = rule_map["naming_convention"]["rule_value"]
        action = rule_map["naming_convention"]["rule_action"]
        passed = required_keyword.lower() in campaign_name.lower()
        rules_evaluated.append({
            "rule": "naming_convention",
            "required_keyword": required_keyword,
            "campaign_name": campaign_name,
            "passed": passed,
            "action_if_fail": action
        })
        if not passed:
            final_outcome = action
            rule_triggered = "campaign_structure.naming_convention"
            reason = (
                f"Campaign name '{campaign_name}' does not contain "
                f"required keyword '{required_keyword}'"
            )

    return {
        "outcome": final_outcome,
        "rule_triggered": rule_triggered,
        "reason": reason,
        "rules_evaluated": rules_evaluated
    }

def evaluate(proposed_action: dict, agent_instruction: str = "") -> dict:
    action_id = str(uuid.uuid4())
    client_account_id = proposed_action.get("client_account_id", "")
    client_name = get_client_name(client_account_id)

    daily_budget_pence = proposed_action.get("daily_budget_pence", 0)
    lifetime_budget_pence = proposed_action.get("lifetime_budget_pence", 0)
    spend_value = pence_to_pounds(max(daily_budget_pence, lifetime_budget_pence))

    log.info(f"Evaluating action {action_id} for {client_name}")

    spend_rules = get_spend_rules(client_account_id)
    spend_result = evaluate_spend_controls(spend_rules, proposed_action)

    outcome = spend_result["outcome"]
    rule_triggered = spend_result["rule_triggered"]
    reason = spend_result["reason"]
    rules_evaluated = spend_result["rules_evaluated"]

    if outcome == "APPROVED":
        audience_rules = get_audience_rules(client_account_id)
        audience_result = evaluate_audience_rules(audience_rules, proposed_action)
        if audience_result["outcome"] != "APPROVED":
            outcome = audience_result["outcome"]
            rule_triggered = audience_result["rule_triggered"]
            reason = audience_result["reason"]
        rules_evaluated += audience_result["rules_evaluated"]

    if outcome == "APPROVED":
        structure_rules = get_campaign_structure_rules(client_account_id)
        recent_campaigns = get_recent_campaigns(client_account_id, days=30)
        structure_result = evaluate_campaign_structure(structure_rules, proposed_action, recent_campaigns)
        if structure_result["outcome"] != "APPROVED":
            outcome = structure_result["outcome"]
            rule_triggered = structure_result["rule_triggered"]
            reason = structure_result["reason"]
        rules_evaluated += structure_result["rules_evaluated"]

    if OBSERVE_MODE:
        log.info(f"OBSERVE MODE — would have been {outcome}, logging as OBSERVE")
        outcome = "OBSERVE"

    spend_protected = spend_value if outcome in ["BLOCK", "BLOCKED"] else 0.0

    write_audit_log(
        action_id=action_id,
        client_account_id=client_account_id,
        client_name=client_name,
        agent_instruction=agent_instruction,
        proposed_action=proposed_action,
        rules_evaluated=rules_evaluated,
        rule_triggered=rule_triggered or "",
        outcome=outcome,
        spend_value=spend_value,
        spend_protected=spend_protected,
        observe_mode=OBSERVE_MODE
    )

    if outcome == "FLAG":
        write_approval_queue(
            action_id=action_id,
            client_account_id=client_account_id,
            client_name=client_name,
            rule_triggered=rule_triggered,
            reason=reason,
            proposed_action=proposed_action,
            spend_value=spend_value,
            agent_instruction=agent_instruction
        )
        send_flag_notification(
            action_id=action_id,
            client_name=client_name,
            rule_triggered=rule_triggered,
            reason=reason,
            spend_value=spend_value,
            proposed_action=proposed_action
        )

    elif outcome in ["BLOCK", "BLOCKED"]:
        send_block_notification(
            action_id=action_id,
            client_name=client_name,
            rule_triggered=rule_triggered,
            reason=reason,
            spend_protected=spend_protected
        )

    return {
        "action_id": action_id,
        "outcome": outcome,
        "rule_triggered": rule_triggered,
        "reason": reason,
        "spend_value": spend_value,
        "rules_evaluated": rules_evaluated,
        "observe_mode": OBSERVE_MODE
    }