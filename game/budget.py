"""
Team budget source for "Outrun the Police".

Swap point wired to the real central gateway (see
brain/GATEWAY-INTEGRATION-SPEC.md, brain/logs.md): tries
gateway_client.get_team_state() first and uses its `balance` field; falls
back to the env-var-driven BUDGET_DEFAULT (same as before this integration)
whenever the gateway is unreachable or not configured, so local dev/testing
without a gateway still works unchanged.
"""
import os

import gateway_client

BUDGET_DEFAULT = float(os.environ.get("BUDGET_DEFAULT", "100"))


def get_team_budget(team_code):
    """
    Returns the cost cap for this team's route submissions: the gateway's
    live balance for this team if reachable, else BUDGET_DEFAULT.
    """
    state = gateway_client.get_team_state(team_code)
    if state is not None and "balance" in state:
        return float(state["balance"])
    return BUDGET_DEFAULT
