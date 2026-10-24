import os
from typing import Any, List, Optional
from dotenv import load_dotenv

load_dotenv()

def get_chat_model(tools: Optional[List[Any]] = None):
    """
    Returns configured chat model based on environment variables.
    Supports Google Gemini and OpenAI.
    """
    gemini_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")

    model = None
    if gemini_key:
        from langchain_google_genai import ChatGoogleGenerativeAI
        model_name = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
        model = ChatGoogleGenerativeAI(
            model=model_name
        )
    elif openai_key:
        from langchain_openai import ChatOpenAI
        model_name = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        model = ChatOpenAI(
            model=model_name,
            temperature=0.0
        )

    if model is not None and tools is not None:
        return model.bind_tools(tools)
    return model
