import logging
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from engine import evaluate

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

app = FastAPI(title="BidSense Guardrails Engine", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["*"],
)
@app.options("/rules/{client_account_id}")
async def rules_options(client_account_id: str):
    return {}

class ActionRequest(BaseModel):
    proposed_action:   dict
    agent_instruction: str = ""

class DecisionResponse(BaseModel):
    action_id:       str
    outcome:         str
    rule_triggered:  str | None
    reason:          str | None
    spend_value:     float
    rules_evaluated: list
    observe_mode:    bool

@app.get("/health")
def health():
    return {"status": "ok", "service": "bidsense-guardrails"}

@app.post("/evaluate", response_model=DecisionResponse)
def evaluate_action(request: ActionRequest):
    try:
        decision = evaluate(
            proposed_action   = request.proposed_action,
            agent_instruction = request.agent_instruction
        )
        return decision
    except Exception as e:
        log.error(f"Evaluation error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8080)
@app.get("/stats")
async def get_stats():
    """Returns aggregated stats from the real audit log for the dashboard."""
    from bigquery import get_audit_stats, get_recent_audit_log
    stats = get_audit_stats()
    recent = get_recent_audit_log(limit=10)
    return {"stats": stats, "recent": recent}


@app.get("/approval-queue")
async def get_approval_queue():
    """Returns pending items from Firestore approval queue."""
    from firestore import get_pending_approvals
    items = get_pending_approvals()
    return {"items": items}

@app.get("/rules/{client_account_id}")
async def get_rules(client_account_id: str):
    """Returns all active rules for a client account from BigQuery."""
    from bigquery import get_all_rules
    rules = get_all_rules(client_account_id)
    return {"rules": rules, "client_account_id": client_account_id}


@app.patch("/rules/{client_account_id}")
async def update_rule(client_account_id: str, update: dict):
    """Updates a single rule in BigQuery."""
    from bigquery import update_rule_in_bigquery
    rule_name = update.get("rule_name")
    rule_category = update.get("rule_category")
    rule_value = update.get("rule_value")
    is_active = update.get("is_active")
    success = update_rule_in_bigquery(client_account_id, rule_category, rule_name, rule_value, is_active)
    return {"success": success, "rule_name": rule_name}