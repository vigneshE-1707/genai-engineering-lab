"""Groq chat-model factory."""

from __future__ import annotations

from langchain_groq import ChatGroq

from .config import settings


def get_llm(temperature: float | None = None) -> ChatGroq:
    """Return a configured ChatGroq instance.

    The API key is read from the ``GROQ_API_KEY`` environment variable, which
    ``config`` populates from settings.
    """
    return ChatGroq(
        model=settings.groq_model,
        temperature=settings.temperature if temperature is None else temperature,
    )
