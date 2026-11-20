"""Shared graph state for the research swarm."""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict


class ResearchState(TypedDict, total=False):
    """State passed between agents.

    ``search_results`` uses a reducer (list concatenation) because the Searcher
    node fans out — one parallel invocation per sub-question — and every branch
    writes to this key concurrently.
    """

    # user input
    query: str

    # planner output
    sub_questions: list[str]

    # per-invocation input for a fanned-out searcher (carried via Send)
    sub_question: str

    # accumulated across parallel searchers (reducer!)
    search_results: Annotated[list, operator.add]

    # single-node outputs (last write wins)
    summaries: list
    verdict: str
    gaps: list[str]
    retries: int
    report: str
