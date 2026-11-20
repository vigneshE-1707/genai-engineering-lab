"""The research swarm's agents, implemented as LangGraph node functions.

Each node emits human-readable progress events via ``get_stream_writer()`` so
the web UI can show the swarm working in real time.
"""

from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.config import get_stream_writer
from langgraph.types import Send

from .config import settings
from .llm import get_llm
from .tools import get_search_tool

# --------------------------------------------------------------------------- #
# Prompts
# --------------------------------------------------------------------------- #

PLANNER_SYS = (
    "You are the Planner in a research team. Break the user's question into "
    "{n} focused, non-overlapping sub-questions that together fully cover the "
    "topic. Each sub-question must be independently web-searchable.\n"
    "Respond with ONLY a JSON array of strings, nothing else. "
    'Example: ["...", "...", "..."]'
)

SUMMARIZER_SYS = (
    "You are the Summarizer. Given raw web-search results for several "
    "sub-questions, extract the key findings as concise bullet points. "
    "Attribute each claim to its source URL in parentheses. Be factual and "
    "do not invent anything not present in the provided content."
)

FACTCHECK_SYS = (
    "You are the Fact-Checker. Review the findings against the available "
    "sources. Decide whether the findings are well-supported and sufficient "
    "to answer the question.\n"
    "Respond with ONLY a JSON object of the form "
    '{"verdict": "pass" | "needs_more", "gaps": ["follow-up search query", ...]}. '
    'Use "pass" with an empty gaps list when the findings are solid. Use '
    '"needs_more" with 1-3 specific follow-up search queries when important '
    "aspects are missing or unsupported."
)

WRITER_SYS = (
    "You are the Writer. Using ONLY the verified findings, write a clear, "
    "well-structured research report in Markdown answering the user's "
    "question. Use headings and bullet points where helpful. Add inline "
    "citations as Markdown links to the source URLs. End with a '## Sources' "
    "section listing the sources as a bulleted list of Markdown links. "
    "If the findings are insufficient, say so plainly rather than inventing facts."
)


# --------------------------------------------------------------------------- #
# Parsing helpers
# --------------------------------------------------------------------------- #

def _extract_json(text: str) -> Any:
    """Best-effort extraction of the first JSON value in a string."""
    text = text.strip()
    # strip ```json ... ``` fences if present
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    # try the whole thing, then the first {...} or [...] block
    for candidate in (text, _first_block(text, "[", "]"), _first_block(text, "{", "}")):
        if not candidate:
            continue
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return None


def _first_block(text: str, open_ch: str, close_ch: str) -> str | None:
    start = text.find(open_ch)
    end = text.rfind(close_ch)
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return None


def parse_subquestions(text: str) -> list[str]:
    data = _extract_json(text)
    if isinstance(data, list):
        return [str(x).strip() for x in data if str(x).strip()]
    # fallback: split lines / bullets
    lines = [re.sub(r"^[\s\-\*\d\.\)]+", "", ln).strip() for ln in text.splitlines()]
    return [ln for ln in lines if ln][: settings.max_subquestions]


def parse_verdict(text: str) -> tuple[str, list[str]]:
    data = _extract_json(text)
    if isinstance(data, dict):
        verdict = str(data.get("verdict", "pass")).strip().lower()
        gaps = data.get("gaps", []) or []
        gaps = [str(g).strip() for g in gaps if str(g).strip()]
        if verdict != "needs_more":
            gaps = []
        return ("needs_more" if verdict == "needs_more" and gaps else "pass", gaps)
    return ("pass", [])


# --------------------------------------------------------------------------- #
# Nodes
# --------------------------------------------------------------------------- #

async def planner(state: dict) -> dict:
    writer = get_stream_writer()
    query = state["query"]
    writer({"agent": "planner", "status": "running",
            "message": f"Planning research for: {query}"})

    llm = get_llm()
    sys = PLANNER_SYS.format(n=settings.max_subquestions)
    resp = await llm.ainvoke([SystemMessage(content=sys), HumanMessage(content=query)])
    subqs = parse_subquestions(resp.content)[: settings.max_subquestions]
    if not subqs:
        subqs = [query]

    writer({"agent": "planner", "status": "done",
            "message": f"Drafted {len(subqs)} sub-question(s)", "data": subqs})
    return {"sub_questions": subqs, "retries": state.get("retries", 0)}


async def searcher(state: dict) -> dict:
    writer = get_stream_writer()
    q = state["sub_question"]
    writer({"agent": "searcher", "status": "running", "message": f"Searching: {q}"})

    tool = get_search_tool()
    try:
        raw = await tool.ainvoke({"query": q})
    except Exception as exc:  # noqa: BLE001 - surface any search failure gracefully
        writer({"agent": "searcher", "status": "error",
                "message": f"Search failed for '{q}': {exc}"})
        return {"search_results": [{"sub_question": q, "content": "", "sources": []}]}

    results = []
    if isinstance(raw, dict):
        results = raw.get("results", []) or []
    sources = [{"title": r.get("title", ""), "url": r.get("url", "")}
               for r in results if r.get("url")]
    content = "\n\n".join(
        f"{r.get('title', '')}: {r.get('content', '')}" for r in results
    )

    writer({"agent": "searcher", "status": "done",
            "message": f"Found {len(sources)} source(s) for: {q}", "data": sources})
    return {"search_results": [{"sub_question": q, "content": content, "sources": sources}]}


async def summarizer(state: dict) -> dict:
    writer = get_stream_writer()
    writer({"agent": "summarizer", "status": "running",
            "message": "Summarizing findings from all searches"})

    results = state.get("search_results", [])
    blocks = []
    for r in results:
        srcs = "; ".join(s["url"] for s in r.get("sources", []))
        blocks.append(
            f"Sub-question: {r['sub_question']}\n"
            f"Sources: {srcs}\n"
            f"Content: {r['content'][:3000]}"
        )
    context = "\n\n---\n\n".join(blocks) if blocks else "(no results)"

    llm = get_llm()
    resp = await llm.ainvoke([
        SystemMessage(content=SUMMARIZER_SYS),
        HumanMessage(content=f"Original question: {state['query']}\n\n{context}"),
    ])

    writer({"agent": "summarizer", "status": "done", "message": "Key findings compiled"})
    return {"summaries": [resp.content]}


async def fact_checker(state: dict) -> dict:
    writer = get_stream_writer()
    writer({"agent": "factchecker", "status": "running",
            "message": "Verifying claims against sources"})

    summary = "\n\n".join(state.get("summaries", []))
    all_sources = [
        s["url"]
        for r in state.get("search_results", [])
        for s in r.get("sources", [])
    ]

    llm = get_llm(temperature=0.0)
    resp = await llm.ainvoke([
        SystemMessage(content=FACTCHECK_SYS),
        HumanMessage(content=(
            f"Question: {state['query']}\n\n"
            f"Findings:\n{summary}\n\n"
            f"Available sources:\n" + "\n".join(all_sources)
        )),
    ])
    verdict, gaps = parse_verdict(resp.content)

    msg = f"Verdict: {verdict}" + (f" — {len(gaps)} gap(s) to fill" if gaps else "")
    writer({"agent": "factchecker", "status": "done", "message": msg})
    return {"verdict": verdict, "gaps": gaps}


async def refine(state: dict) -> dict:
    writer = get_stream_writer()
    gaps = state.get("gaps", [])
    writer({"agent": "planner", "status": "running",
            "message": f"Refining — {len(gaps)} follow-up search(es)"})
    return {"sub_questions": gaps, "retries": state.get("retries", 0) + 1}


async def writer_node(state: dict) -> dict:
    writer = get_stream_writer()
    writer({"agent": "writer", "status": "running", "message": "Writing final report"})

    summary = "\n\n".join(state.get("summaries", []))

    seen: set[str] = set()
    sources: list[dict] = []
    for r in state.get("search_results", []):
        for s in r.get("sources", []):
            url = s.get("url")
            if url and url not in seen:
                seen.add(url)
                sources.append(s)
    src_list = "\n".join(
        f"- [{s['title'] or s['url']}]({s['url']})" for s in sources
    ) or "(no sources found)"

    llm = get_llm()
    resp = await llm.ainvoke([
        SystemMessage(content=WRITER_SYS),
        HumanMessage(content=(
            f"Question: {state['query']}\n\n"
            f"Verified findings:\n{summary}\n\n"
            f"Sources to cite:\n{src_list}"
        )),
    ])

    writer({"agent": "writer", "status": "done", "message": "Report ready"})
    return {"report": resp.content}


# --------------------------------------------------------------------------- #
# Routing
# --------------------------------------------------------------------------- #

def fan_out_searches(state: dict) -> list[Send]:
    """Fan out one parallel Searcher invocation per sub-question."""
    return [
        Send("searcher", {"query": state["query"], "sub_question": q})
        for q in state.get("sub_questions", [])
    ]


def route_after_factcheck(state: dict) -> str:
    """Loop back to refine/search when the fact-checker found fillable gaps."""
    gaps = state.get("gaps", [])
    retries = state.get("retries", 0)
    if gaps and retries < settings.max_factcheck_retries:
        return "refine"
    return "write"
