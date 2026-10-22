import shutil
import subprocess
import json
import os
from typing import Any, Dict
from gateway.adapters.base import BaseAdapter

class CliAdapter(BaseAdapter):
    """
    Adapter that executes CLI commands (e.g., GitHub CLI 'gh') safely (P1 and P5).
    If 'gh' is not installed or GH_MOCK=1, automatically falls back to an
    in-memory simulator for zero-friction local development.
    """
    def __init__(self, server_name: str, server_def):
        super().__init__(server_name, server_def)
        self.has_real_cli = shutil.which(server_def.command or "gh") is not None and os.getenv("GH_MOCK") != "1"
        self._mock_issues = []
        self._mock_prs = [
            {
                "number": 42,
                "title": "fix(sms): handle SIP 500 retry timeout in UV",
                "state": "OPEN",
                "author": {"login": "john-dev"},
                "body": "Fixes premature connection termination on telephony carrier timeouts."
            },
            {
                "number": 41,
                "title": "feat(audio): buffer packet loss on webrtc calls",
                "state": "OPEN",
                "author": {"login": "mary-eng"},
                "body": "Adds jitter buffer optimization for low-bandwidth clients."
            }
        ]

    async def execute(self, tool_name: str, args: Dict[str, Any]) -> Any:
        if self.has_real_cli:
            return await self._execute_real_cli(tool_name, args)
        else:
            return await self._execute_mock_cli(tool_name, args)

    async def _execute_real_cli(self, tool_name: str, args: Dict[str, Any]) -> Any:
        try:
            if tool_name == "list_prs":
                limit = str(args.get("limit", 5))
                res = subprocess.run(
                    ["gh", "pr", "list", "--limit", limit, "--json", "number,title,state,author"],
                    capture_output=True, text=True, check=True
                )
                return json.loads(res.stdout)

            elif tool_name == "get_pr":
                pr_num = str(args["pr_number"])
                res = subprocess.run(
                    ["gh", "pr", "view", pr_num, "--json", "number,title,body,state,author"],
                    capture_output=True, text=True, check=True
                )
                return json.loads(res.stdout)

            elif tool_name == "create_issue":
                title = args["title"]
                body = args["body"]
                res = subprocess.run(
                    ["gh", "issue", "create", "--title", title, "--body", body],
                    capture_output=True, text=True, check=True
                )
                return {
                    "status": "CREATED",
                    "output": res.stdout.strip(),
                    "title": title
                }
            else:
                raise ValueError(f"Unknown CLI tool: {tool_name}")
        except subprocess.CalledProcessError as e:
            return {"error": e.stderr.strip() or str(e)}

    async def _execute_mock_cli(self, tool_name: str, args: Dict[str, Any]) -> Any:
        if tool_name == "list_prs":
            limit = args.get("limit", 5)
            return self._mock_prs[:limit]

        elif tool_name == "get_pr":
            pr_num = args.get("pr_number")
            for pr in self._mock_prs:
                if pr["number"] == pr_num:
                    return pr
            return {"error": f"PR #{pr_num} not found."}

        elif tool_name == "create_issue":
            new_issue = {
                "id": len(self._mock_issues) + 101,
                "number": len(self._mock_issues) + 101,
                "title": args["title"],
                "body": args["body"],
                "status": "OPEN",
                "html_url": f"https://github.com/dialpad-org/dialpad-core/issues/{len(self._mock_issues) + 101}",
                "_source": "CLI Adapter (Mock Runner)"
            }
            self._mock_issues.append(new_issue)
            return {
                "status": "CREATED",
                "issue_url": new_issue["html_url"],
                "issue_number": new_issue["number"],
                "title": new_issue["title"]
            }

        raise ValueError(f"Unsupported tool in CLI adapter: {tool_name}")
