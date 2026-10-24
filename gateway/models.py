from typing import Dict, List, Optional, Any, Literal
from pydantic import BaseModel, Field

RiskLevel = Literal["read", "write", "destructive"]
ServerType = Literal["cli_wrapper", "mcp_proxy", "http_mapping"]

class ToolArg(BaseModel):
    type: str = "string"
    description: Optional[str] = None
    required: bool = False
    default: Optional[Any] = None

class ToolDefinition(BaseModel):
    name: str = ""
    server_name: str = ""
    risk: RiskLevel = "read"
    description: str
    args: Dict[str, ToolArg] = Field(default_factory=dict)
    redact: List[str] = Field(default_factory=list)
    # HTTP specific
    method: Optional[str] = "GET"
    path: Optional[str] = None

class ServerDefinition(BaseModel):
    type: ServerType
    description: str
    command: Optional[str] = None
    args: List[str] = Field(default_factory=list)
    base_url: Optional[str] = None
    credential_ref: Optional[str] = None
    transport: Optional[str] = "stdio"
    # Governance & dynamic proxy settings
    default_risk: Optional[RiskLevel] = "read"
    risk_overrides: Dict[str, RiskLevel] = Field(default_factory=dict)
    redact_overrides: Dict[str, List[str]] = Field(default_factory=dict)
    # Tools dictionary (populated statically or dynamically via MCP list_tools)
    tools: Dict[str, ToolDefinition] = Field(default_factory=dict)

class RegistryConfig(BaseModel):
    version: str = "1.0"
    servers: Dict[str, ServerDefinition]
