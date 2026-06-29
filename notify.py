import requests
import logging
from google.cloud import secretmanager

log = logging.getLogger(__name__)

GCP_PROJECT = "ai-campaign-safety-layer"

def get_webhook_url() -> str:
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{GCP_PROJECT}/secrets/teams-webhook-url/versions/latest"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("utf-8").strip()

def send_flag_notification(action_id: str, client_name: str, rule_triggered: str, reason: str, spend_value: float, proposed_action: dict):
    """Send a Teams notification when an action is flagged for human review."""
    try:
        webhook_url = get_webhook_url()

        payload = {
            "type": "message",
            "attachments": [
                {
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "content": {
                        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                        "type": "AdaptiveCard",
                        "version": "1.4",
                        "body": [
                            {
                                "type": "TextBlock",
                                "text": "⚑ BidSense — Action Flagged for Review",
                                "weight": "Bolder",
                                "size": "Medium",
                                "color": "Warning"
                            },
                            {
                                "type": "FactSet",
                                "facts": [
                                    {"title": "Action ID",   "value": action_id},
                                    {"title": "Client",      "value": client_name},
                                    {"title": "Rule",        "value": rule_triggered},
                                    {"title": "Reason",      "value": reason},
                                    {"title": "Spend Value", "value": f"£{spend_value:,.2f}"},
                                ]
                            },
                            {
                                "type": "TextBlock",
                                "text": "Log into BidSense dashboard to approve or reject.",
                                "wrap": True,
                                "isSubtle": True
                            }
                        ]
                    }
                }
            ]
        }

        r = requests.post(webhook_url, json=payload, timeout=10)
        log.info(f"Teams notification sent: {r.status_code}")

    except Exception as e:
        log.error(f"Teams notification failed: {e}")

def send_block_notification(action_id: str, client_name: str, rule_triggered: str, reason: str, spend_protected: float):
    """Send a Teams notification when an action is blocked."""
    try:
        webhook_url = get_webhook_url()

        payload = {
            "type": "message",
            "attachments": [
                {
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "content": {
                        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                        "type": "AdaptiveCard",
                        "version": "1.4",
                        "body": [
                            {
                                "type": "TextBlock",
                                "text": "✕ BidSense — Action Blocked",
                                "weight": "Bolder",
                                "size": "Medium",
                                "color": "Attention"
                            },
                            {
                                "type": "FactSet",
                                "facts": [
                                    {"title": "Action ID",       "value": action_id},
                                    {"title": "Client",          "value": client_name},
                                    {"title": "Rule",            "value": rule_triggered},
                                    {"title": "Reason",          "value": reason},
                                    {"title": "Spend Protected", "value": f"£{spend_protected:,.2f}"},
                                ]
                            }
                        ]
                    }
                }
            ]
        }

        r = requests.post(webhook_url, json=payload, timeout=10)
        log.info(f"Teams block notification sent: {r.status_code}")

    except Exception as e:
        log.error(f"Teams block notification failed: {e}")
