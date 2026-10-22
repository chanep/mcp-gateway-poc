import os
from typing import Any, List
from dotenv import load_dotenv

load_dotenv()

def get_chat_model(tools: List[Any]):
    """
    Returns configured chat model based on environment variables.
    Supports Google Gemini and OpenAI.
    """
    gemini_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")

    if gemini_key:
        from langchain_google_genai import ChatGoogleGenerativeAI
        model = ChatGoogleGenerativeAI(
            model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
            temperature=0.0
        )
        return model.bind_tools(tools)

    if openai_key:
        from langchain_openai import ChatOpenAI
        model = ChatOpenAI(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            temperature=0.0
        )
        return model.bind_tools(tools)

    return None
