"""Camada de LLM: provedores intercambiáveis (anthropic, openai, openrouter, ollama) com saída JSON validada."""
from app.llm.client import LLMClient, LLMError, LLMResult, get_client, status  # noqa: F401
