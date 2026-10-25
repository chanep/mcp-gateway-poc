import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command
from agent.graph import build_gateway_agent

async def main():
    print("=" * 70)
    print("PHONECENTRAL MCP GATEWAY - INTERACTIVE LANGGRAPH AGENT (ReAct + HITL)")
    print("=" * 70)
    print("Agent connects to Gateway via SSE and discovers tools dynamically.")
    print("Mutating/destructive actions require your explicit confirmation.\n")

    gateway_url = "http://127.0.0.1:8000/catalog/sse"
    checkpointer = MemorySaver()

    try:
        agent = await build_gateway_agent(gateway_url=gateway_url, checkpointer=checkpointer)
    except Exception as e:
        print(f"\nERROR connecting to Gateway at {gateway_url}: {e}")
        print("Please ensure the Gateway server is running in another terminal:")
        print("   uv run uvicorn gateway.server:app --port 8000\n")
        return

    config = {"configurable": {"thread_id": "session-main"}}

    default_prompt = (
        "Inspect ticket TICKET-101 in the ticketing system. "
        "If it references a failed call with call_id, retrieve the call details "
        "from telephony and create an issue on my GitHub repository alerting the team."
    )

    print(f"Sample suggestion (The Incident Triage):\n\"{default_prompt}\"\n")

    while True:
        try:
            user_input = input("Enter prompt (type 'demo' for sample, 'exit' to quit): ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nExiting...")
            break

        if not user_input or user_input.lower() == "exit":
            break
        if user_input.lower() == "demo":
            user_input = default_prompt

        print(f"\n[User]: {user_input}\n")

        current_input = {"messages": [HumanMessage(content=user_input)]}

        while True:
            # Execute official LangGraph agent
            async for event in agent.astream(current_input, config=config, stream_mode="values"):
                last_msg = event["messages"][-1]
                if isinstance(last_msg, AIMessage):
                    if last_msg.content:
                        print(f"[Agent]: {last_msg.content}")
                    if last_msg.tool_calls:
                        for tc in last_msg.tool_calls:
                            print(f"  [Tool Request]: {tc['name']} -> {tc['args']}")
                elif isinstance(last_msg, ToolMessage):
                    print(f"  [Tool Result]: {str(last_msg.content)[:160]}...")

            # Check if execution paused on native Human-in-the-loop interrupt
            state = await agent.aget_state(config)
            if state.tasks and any(task.interrupts for task in state.tasks):
                interrupt_val = state.tasks[0].interrupts[0].value
                print("\n" + "=" * 70)
                print("HUMAN-IN-THE-LOOP - CONFIRMATION REQUIRED")
                print(f"Message: {interrupt_val.get('message')}")
                print(f"Action: {interrupt_val.get('action')}")
                print(f"Arguments: {interrupt_val.get('arguments')}")
                print("=" * 70)

                decision = input("Approve this execution? [y/N]: ").strip().lower()
                approved = decision in ("y", "yes")

                if approved:
                    print("APPROVED: Resuming execution...\n")
                else:
                    print("REJECTED: Cancelling operation...\n")

                # Resume using native LangGraph Command
                current_input = Command(resume={"approved": approved})
            else:
                break

        print("\n" + "-" * 70 + "\n")

if __name__ == "__main__":
    asyncio.run(main())
