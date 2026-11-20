# Research Assistant Swarm 🐝

A **multi-agent research system**: ask a question, and a team of specialized AI
agents — coordinated by a [LangGraph](https://langchain-ai.github.io/langgraph/)
orchestrator — plan the research, search the web with [Tavily](https://tavily.com/),
summarize, fact-check, and write a **cited report**. A premium FastAPI + Tailwind
web UI streams every agent's progress live.

> Fully local. No external org infrastructure, no database — request state lives
> in memory.

## The swarm

| Agent                     | Role                                                         |
| ------------------------- | ------------------------------------------------------------ |
| 🧭 **Planner**      | Breaks the question into focused sub-questions               |
| 🔎 **Searcher**     | Runs a Tavily web search per sub-question (parallel fan-out) |
| 📝 **Summarizer**   | Condenses results into key findings with sources             |
| ✅ **Fact-Checker** | Verifies claims; can loop back for more searches             |
| ✍️ **Writer**     | Synthesizes the final cited Markdown report                  |

```
START → planner → (Send per sub-question) → searcher → summarizer → fact_checker
fact_checker --[gaps & retries left]--> refine → searcher      (verification loop)
fact_checker --[ok | retries exhausted]--> writer → END
```

## Tech

- **Orchestration:** LangGraph (`StateGraph`, `Send` fan-out, reducers, streaming)
- **LLM:** Groq (`langchain-groq`)
- **Web search:** Tavily (`langchain-tavily`)
- **Backend:** FastAPI + SSE (`sse-starlette`)
- **Frontend:** single-page HTML + Tailwind (CDN), vanilla JS `EventSource`

## Setup

1. **Create a virtual environment & install deps**

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1      # Windows PowerShell
   # source .venv/bin/activate       # macOS/Linux
   pip install -r requirements.txt
   ```
2. **Add API keys** — copy `.env.example` to `.env` and fill in:

   - `GROQ_API_KEY` — free at [https://console.groq.com/keys](https://console.groq.com/keys)
   - `TAVILY_API_KEY` — free at [https://app.tavily.com/](https://app.tavily.com/)
3. **Confirm the model** — set `GROQ_MODEL` in `.env` to a currently-served
   Groq model. Check the list at [https://console.groq.com/docs/models](https://console.groq.com/docs/models)
   (the default `llama-3.3-70b-versatile` may have been deprecated).

## Run

```powershell
uvicorn app.main:app --reload
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000) and ask a question.

Check keys are loaded: [http://127.0.0.1:8000/api/health](http://127.0.0.1:8000/api/health)

### Backend-only smoke test (no UI)

```powershell
python -m app.graph
```

## Project layout

```
app/
  config.py    # settings + API keys from .env
  llm.py       # ChatGroq factory
  tools.py     # Tavily search tool
  state.py     # ResearchState (TypedDict + reducers)
  agents.py    # the 5 agent node functions + prompts
  graph.py     # LangGraph wiring (+ CLI smoke test)
  main.py      # FastAPI app + SSE endpoint
static/
  index.html   # premium single-page UI
```

## How it works

- The **Planner** returns a list of `Send("searcher", …)` objects, so LangGraph
  runs one **Searcher** per sub-question *in parallel*. Their results merge via a
  list **reducer** on the shared state.
- Each node emits progress through `get_stream_writer()`; the FastAPI endpoint
  relays those as **Server-Sent Events** to the browser, driving the live
  agent-pipeline animation.
- The **Fact-Checker** can route back through **refine → searcher** up to
  `MAX_FACTCHECK_RETRIES` times to fill gaps before the **Writer** produces the
  final report.
