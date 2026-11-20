"""Assembles the research swarm as a LangGraph StateGraph.

Flow:

    START -> planner -(Send per sub-question)-> searcher -> summarizer -> fact_checker
    fact_checker --[gaps & retries left]--> refine -(Send)-> searcher   (verification loop)
    fact_checker --[ok | retries exhausted]--> writer -> END
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from . import agents
from .state import ResearchState


def build_graph():
    g = StateGraph(ResearchState)

    g.add_node("planner", agents.planner)
    g.add_node("searcher", agents.searcher)
    g.add_node("summarizer", agents.summarizer)
    g.add_node("fact_checker", agents.fact_checker)
    g.add_node("refine", agents.refine)
    g.add_node("writer", agents.writer_node)

    g.add_edge(START, "planner")
    g.add_conditional_edges("planner", agents.fan_out_searches, ["searcher"])
    g.add_edge("searcher", "summarizer")
    g.add_edge("summarizer", "fact_checker")
    g.add_conditional_edges(
        "fact_checker",
        agents.route_after_factcheck,
        {"refine": "refine", "write": "writer"},
    )
    g.add_conditional_edges("refine", agents.fan_out_searches, ["searcher"])
    g.add_edge("writer", END)

    return g.compile()


graph = build_graph()


if __name__ == "__main__":
    # Backend-only smoke test (no web UI). Requires valid API keys in .env.
    import asyncio

    from .config import settings

    async def _main() -> None:
        if not settings.keys_present:
            raise SystemExit(f"Missing keys: {', '.join(settings.missing_keys())}")

        question = "What are the main approaches to carbon capture and their trade-offs?"
        print(f"Q: {question}\n")
        async for mode, chunk in graph.astream(
            {"query": question, "retries": 0},
            stream_mode=["custom", "updates"],
        ):
            if mode == "custom":
                print(f"  [{chunk.get('agent')}] {chunk.get('message')}")
            elif mode == "updates":
                for node, upd in chunk.items():
                    if isinstance(upd, dict) and upd.get("report"):
                        print("\n===== REPORT =====\n")
                        print(upd["report"])

    asyncio.run(_main())
