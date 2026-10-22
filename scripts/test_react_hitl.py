import asyncio
from langchain_core.tools import tool, StructuredTool
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command, interrupt
from langchain_core.messages import HumanMessage, AIMessage

# Mock LLM for testing create_react_agent without external API key
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel

async def test_react_hitl():
    @tool
    def search_tools(query: str):
        """Safe tool: searches tools."""
        return f"Found tool for {query}"

    @tool
    def invoke_write(server: str, tool: str, arguments: dict):
        """Sensitive tool: writes changes."""
        resp = interrupt({
            "action": "invoke_write",
            "server": server,
            "tool": tool,
            "arguments": arguments,
            "question": f"¿Aprobar creación en {server}.{tool}?"
        })
        if resp.get("approved"):
            return f"Success write on {server}.{tool}"
        return "Action cancelled by human."

    memory = MemorySaver()
    # Fake responses: first calls search_tools, then invoke_write, then gives final answer
    fake_responses = [
        AIMessage(content="", tool_calls=[{"id": "1", "name": "search_tools", "args": {"query": "tickets"}}]),
        AIMessage(content="", tool_calls=[{"id": "2", "name": "invoke_write", "args": {"server": "github", "tool": "create_issue", "arguments": {"title": "Bug"}}}]),
        AIMessage(content="Todo listo!")
    ]
    model = FakeMessagesListChatModel(responses=fake_responses)

    agent = create_react_agent(
        model=model,
        tools=[search_tools, invoke_write],
        checkpointer=memory
    )

    config = {"configurable": {"thread_id": "test-hitl-1"}}

    # Step 1: Run until interrupt
    print("Iniciando ejecución de create_react_agent...")
    events = []
    async for event in agent.astream({"messages": [HumanMessage(content="Ejecutá el flujo")]}, config=config):
        events.append(event)
        print("Event:", event)

    # Step 2: Check interrupt
    state = await agent.aget_state(config)
    print("\nInterrupts en estado:", state.tasks[0].interrupts)
    assert len(state.tasks[0].interrupts) > 0

    # Step 3: Resume with Command
    print("\nReanudando con Command(resume={'approved': True})...")
    async for event in agent.astream(Command(resume={"approved": True}), config=config):
        print("Resume Event:", event)

    print("\n¡create_react_agent con HITL dinámico funcionó a la perfección!")

if __name__ == "__main__":
    asyncio.run(test_react_hitl())
