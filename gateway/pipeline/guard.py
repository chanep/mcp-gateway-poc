from gateway.models import RiskLevel, ToolDefinition

class GuardException(Exception):
    def __init__(self, message: str, status_code: int = 403):
        super().__init__(message)
        self.status_code = status_code

def validate_risk_level(invoked_risk: RiskLevel, tool_def: ToolDefinition):
    """
    Validates that the invoked meta-tool matches the configured risk level in the registry.
    Prevents an LLM from calling invoke_read on a destructive or mutating tool (P2 - AuthZ).
    """
    declared_risk = tool_def.risk
    if invoked_risk == "read" and declared_risk in ("write", "destructive"):
        raise GuardException(
            f"Security Policy Violation (P2): Tool '{tool_def.server_name}.{tool_def.name}' "
            f"is classified as '{declared_risk.upper()}' but an execution via 'invoke_read' was attempted. "
            f"Must be invoked with 'invoke_{declared_risk}'.",
            status_code=403
        )
    if invoked_risk == "write" and declared_risk == "destructive":
        raise GuardException(
            f"Security Policy Violation (P2): Tool '{tool_def.server_name}.{tool_def.name}' "
            f"is DESTRUCTIVE and cannot be executed via 'invoke_write'. Requires 'invoke_destructive'.",
            status_code=403
        )
    return True
