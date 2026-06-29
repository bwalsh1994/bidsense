import logging
import uuid
from bigquery import get_spend_rules, get_client_name, write_audit_log
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


def evaluate(proposed_action: dict, agent_instruction: str = "") -> dict:
    action_id = str(uuid.uuid4())
    client_account_id = proposed_action.get("client_account_id", "")
    client_name = get_client_name(client_account_id)

    daily_budget_pence = proposed_action.get("daily_budget_pence", 0)
    lifetime_budget_pence = proposed_action.get("lifetime_budget_pence", 0)
    spend_value = pence_to_pounds(max(daily_budget_pence, lifetime_budget_pence))

    log.info(f"Evaluating action {action_id} for {client_name}")

    spend_rules = get_spend_rules(client_account_id)
    result = evaluate_spend_controls(spend_rules, proposed_action)

    outcome = result["outcome"]
    rule_triggered = result["rule_triggered"]
    reason = result["reason"]
    rules_evaluated = result["rules_evaluated"]

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