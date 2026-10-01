"""
Route code for "Outrun the Police" — a short, hand-writable checksum of a
team's best accepted route, per brain/GATEWAY-INTEGRATION-SPEC.md §4 (p2g4):
"a short ROUTE CODE (a checksum of the route + risk), so teams can write it
down. Teams cannot be expected to hand-copy a long node list." Typed into
Final Extraction (p2g5) and checked via the gateway's POST /api/verify.
"""
import hashlib


def compute_route_code(team_code, route, risk):
    """
    First 8 hex chars of sha256(f"{team_code}:{'-'.join(route)}:{risk}"),
    formatted as two 4-char groups (e.g. "A1B2-C3D4") for readability.
    Deterministic: same team/route/risk always produces the same code.
    """
    raw = f"{team_code}:{'-'.join(route)}:{risk}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:8].upper()
    return f"{digest[:4]}-{digest[4:]}"
