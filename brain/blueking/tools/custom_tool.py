from __future__ import annotations

import uuid
from typing import Any, override

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from blueking.utils.context import (
    embed_text,
    ensure_gestalt_collection,
    get_brain_state,
)


class MemorizeInput(BaseModel):
    """Input schema for MemorizeTool."""

    content: str = Field(..., description="Text to remember for future queries.")
    metadata: dict[str, Any] | None = Field(
        default=None,
        description="Optional metadata to store alongside the content.",
    )


class MemorizeTool(BaseTool):
    name: str = "memorize"
    description: str = (
        "Store information in the Gestalt memory for future recall. "
        "Use this to persist important context, facts, or summaries."
    )
    args_schema: type[BaseModel] = MemorizeInput
    
    @override
    def _run(self, content: str, metadata: dict[str, Any] | None = None) -> str:
        """
        Persist content and metadata into the Gestalt Chroma collection.

        :param content: Text to store for later recall.
        :param metadata: Optional metadata to accompany the content.
        :return: Human-readable confirmation containing the record id.
        """
        collection = ensure_gestalt_collection()
        embedding = embed_text(content)
        state = get_brain_state()
        meta = {"source": "gestalt"}
        if state is not None:
            meta["username"] = state.username
        if metadata:
            meta.update(metadata)

        record_id = str(uuid.uuid4())
        collection.add(
            ids=[record_id],
            documents=[content],
            embeddings=[embedding],
            metadatas=[meta],
        )
        return f"Memorized entry {record_id}"


class RecallInput(BaseModel):
    """Input schema for RecallTool."""

    query: str = Field(..., description="What to search for in Gestalt memory.")
    limit: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Maximum number of relevant entries to return.",
    )


class RecallTool(BaseTool):
    name: str = "recall"
    description: str = (
        "Retrieve relevant memories from the Gestalt memory store. "
        "Use this to fetch prior context before planning a response."
    )
    args_schema: type[BaseModel] = RecallInput
    
    @override
    def _run(self, query: str, limit: int = 3) -> str:
        """
        Query the Gestalt memory for relevant content.

        :param query: Search text to match against embeddings.
        :param limit: Maximum number of results to include.
        :return: Formatted summary of matching documents.
        """
        collection = ensure_gestalt_collection()
        embedding = embed_text(query)
        result = collection.query(query_embeddings=[embedding], n_results=limit)
        
        docs = result.get("documents", [[]]) if result else []
        metadatas = result.get("metadatas", [[]]) if result else []
        distances = result.get("distances", [[]]) if result else []
        
        if docs:
            docs = docs[0]
        else:
            return "No relevant memories found."

        if metadatas:
            metadatas = metadatas[0]
        else:
            raise RuntimeError("Metadata should length of retrieved documents")

        if distances:
            distances = distances[0]
        else:
            raise RuntimeError("Metadata should length of retrieved documents")

        lines: list[str] = []
        for doc, meta, dist in zip(docs, metadatas, distances, strict=True):
            meta_info = f"meta={meta}" if meta else "meta={}"
            lines.append(f"- score={dist:.4f} {meta_info} -> {doc}")
        return "Recalling memories:\n" + "\n".join(lines)


# Retain example tool for reference; not intended for Gestalt use.
class MyCustomToolInput(BaseModel):
    """Input schema for MyCustomTool."""

    argument: str = Field(..., description="Description of the argument.")


class MyCustomTool(BaseTool):
    name: str = "Name of my tool"
    description: str = (
        "Clear description for what this tool is useful for, your agent will "
        "need this information to use it."
    )
    args_schema: type[BaseModel] = MyCustomToolInput
    
    @override
    def _run(self, argument: str) -> str:  # pragma: no cover - example only
        """
        Example tool run implementation.

        :param argument: Placeholder argument for demonstration.
        :return: Example output string.
        """
        return "this is an example of a tool output, ignore it and move along."
