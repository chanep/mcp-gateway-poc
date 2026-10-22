from abc import ABC, abstractmethod
from typing import Any, Dict
from gateway.models import ServerDefinition

class BaseAdapter(ABC):
    def __init__(self, server_name: str, server_def: ServerDefinition):
        self.server_name = server_name
        self.server_def = server_def

    @abstractmethod
    async def execute(self, tool_name: str, args: Dict[str, Any]) -> Any:
        pass

    async def close(self):
        pass

