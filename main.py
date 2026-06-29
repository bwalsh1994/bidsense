import logging
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from engine import evaluate

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

app = FastAPI(title="BidSense Guardrails Engine", version="0.1.0")

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