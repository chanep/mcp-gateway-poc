import asyncio
import concurrent.futures
import yaml
from pathlib import Path
from typing import Dict
from gateway.models import RegistryConfig, ServerDefinition, ToolDefinition
from gateway.adapters.base import BaseAdapter
from gateway.adapters.cli_adapter import CliAdapter
from gateway.adapters.mcp_adapter import McpAdapter
from gateway.adapters.http_adapter import HttpAdapter

class RegistryManager:
    def __init__(self, config_path: str = "config/registry.yaml"):
        self.config_path = Path(config_path)
        self.config: RegistryConfig = self._load_config()
        self.adapters: Dict[str, BaseAdapter] = self._init_adapters()

    def _load_config(self) -> RegistryConfig:
        if not self.config_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {self.config_path}")

        with open(self.config_path, "r", encoding="utf-8") as f:
            raw_data = yaml.safe_load(f)

        servers = {}
        for s_name, s_data in raw_data.get("servers", {}).items():
            tools = {}
            for t_name, t_data in s_data.get("tools", {}).items():
                t_data["name"] = t_name
                t_data["server_name"] = s_name
                tools[t_name] = ToolDefinition(**t_data)
            s_data["tools"] = tools
            servers[s_name] = ServerDefinition(**s_data)

        return RegistryConfig(version=raw_data.get("version", "1.0"), servers=servers)

    def _init_adapters(self) -> Dict[str, BaseAdapter]:
        adapters = {}
        for s_name, s_def in self.config.servers.items():
            if s_def.type == "cli_wrapper":
                adapters[s_name] = CliAdapter(s_name, s_def)
            elif s_def.type == "mcp_proxy":
                adapters[s_name] = McpAdapter(s_name, s_def)
            elif s_def.type == "http_mapping":
                adapters[s_name] = HttpAdapter(s_name, s_def)
            else:
                raise ValueError(f"Unsupported server type: {s_def.type}")
        return adapters

    async def initialize(self):
        """Asynchronously discovers and registers dynamic tools from upstream MCP servers."""
        for s_name, adapter in self.adapters.items():
            if isinstance(adapter, McpAdapter):
                dynamic_tools = await adapter.discover_tools()
                self.config.servers[s_name].tools.update(dynamic_tools)

    def ensure_tools_loaded(self):
        """Synchronous guard to ensure dynamic tools are discovered if not yet populated."""
        for s_name, s_def in self.config.servers.items():
            if s_def.type == "mcp_proxy" and not s_def.tools:
                adapter = self.adapters.get(s_name)
                if isinstance(adapter, McpAdapter):
                    try:
                        loop = asyncio.get_running_loop()
                        with concurrent.futures.ThreadPoolExecutor() as pool:
                            dynamic_tools = pool.submit(asyncio.run, adapter.discover_tools()).result()
                    except RuntimeError:
                        dynamic_tools = asyncio.run(adapter.discover_tools())
                    s_def.tools.update(dynamic_tools)

    def get_tool(self, server_name: str, tool_name: str) -> ToolDefinition:
        self.ensure_tools_loaded()
        server = self.config.servers.get(server_name)
        if not server:
            raise KeyError(f"Server '{server_name}' does not exist in registry.")
        tool = server.tools.get(tool_name)
        if not tool:
            raise KeyError(f"Tool '{tool_name}' does not exist on server '{server_name}'.")
        return tool

    def get_adapter(self, server_name: str) -> BaseAdapter:
        adapter = self.adapters.get(server_name)
        if not adapter:
            raise KeyError(f"Adapter for server '{server_name}' not found.")
        return adapter
