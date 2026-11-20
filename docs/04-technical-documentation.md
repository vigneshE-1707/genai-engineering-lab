# Technical Documentation

## Repository Structure

```
MultiAgent/
├── .env                  # API keys and runtime configuration (git-ignored)
├── .env.example          # Template for .env with placeholder values
├── .gitignore            # Ignores .env, .venv, __pycache__, etc.
├── README.md             # Project overview and setup instructions
├── requirements.txt      # Python dependencies (9 packages)
├── app/                  # Backend application package
│   ├── __init__.py       # Package marker, defines __version__ = "0.1.0"
│   ├── config.py         # Pydantic Settings, environment loading
│   ├── llm.py            # ChatGroq LLM factory
│   ├── tools.py          # TavilySearch tool factory
│   ├── state.py          # ResearchState TypedDict definition
│   ├── agents.py         # Agent node functions, prompts, parsers, routing
│   ├── graph.py          # LangGraph StateGraph assembly + CLI smoke test
│   └── main.py           # FastAPI application, routes, SSE endpoint
├── static/               # Frontend static assets
│   └── index.html        # Single-page UI (HTML + CSS + JS)
└── docs/                 # Documentation (this folder)
```

## Module Documentation

### `app/config.py` — Application Settings

**Purpose:** Centralized configuration management. Loads environment variables from `.env`, validates API key presence, and exports keys to `os.environ` for downstream LangChain integrations.

| Class/Function | Description |
|---|---|
| `Settings(BaseSettings)` | Pydantic Settings model with all configuration fields |
| `Settings.keys_present` | Property returning `True` if both API keys are non-empty |
| `Settings.missing_keys()` | Returns list of missing key names |
| `settings` | Module-level singleton instance |

**Configuration fields:**

| Field | Env Variable | Default | Description |
|---|---|---|---|
| `groq_api_key` | `GROQ_API_KEY` | `""` | Groq API authentication key |
| `tavily_api_key` | `TAVILY_API_KEY` | `""` | Tavily API authentication key |
| `groq_model` | `GROQ_MODEL` | `"openai/gpt-oss-120b"` | LLM model identifier on Groq |
| `temperature` | `TEMPERATURE` | `0.3` | Default LLM generation temperature |
| `max_search_results` | `MAX_SEARCH_RESULTS` | `5` | Tavily results per query |
| `max_subquestions` | `MAX_SUBQUESTIONS` | `5` | Maximum sub-questions from Planner |
| `max_factcheck_retries` | `MAX_FACTCHECK_RETRIES` | `1` | Maximum fact-check retry loops |

**Key behavior:** After instantiation, `config.py` writes the API keys into `os.environ` so that `ChatGroq` and `TavilySearch` (which read keys from environment) work without explicit key passing.

---

### `app/llm.py` — LLM Factory

**Purpose:** Provides a single factory function to create configured `ChatGroq` instances.

| Function | Signature | Description |
|---|---|---|
| `get_llm()` | `get_llm(temperature: float | None = None) -> ChatGroq` | Returns a ChatGroq instance. Uses `settings.temperature` by default; callers can override (e.g., Fact-Checker uses `0.0`). |

**Communication:** Called by `agents.planner`, `agents.summarizer`, `agents.fact_checker`, and `agents.writer_node`.

---

### `app/tools.py` — Search Tool Factory

**Purpose:** Provides a factory function to create configured `TavilySearch` instances.

| Function | Signature | Description |
|---|---|---|
| `get_search_tool()` | `get_search_tool() -> TavilySearch` | Returns a TavilySearch configured with `max_results` and `topic="general"`. |

**Communication:** Called by `agents.searcher`.

---

### `app/state.py` — Graph State Schema

**Purpose:** Defines the `ResearchState` TypedDict that serves as shared memory for all LangGraph nodes.

```python
class ResearchState(TypedDict, total=False):
    query: str
    sub_questions: list[str]
    sub_question: str
    search_results: Annotated[list, operator.add]  # reducer
    summaries: list
    verdict: str
    gaps: list[str]
    retries: int
    report: str
```

**Key design:** The `search_results` field uses `Annotated[list, operator.add]` as a **reducer**, enabling parallel Searcher nodes to append their results concurrently without overwriting each other. All other fields use the default last-write-wins strategy.

---

### `app/agents.py` — Agent Logic

**Purpose:** Implements all agent node functions, system prompts, JSON parsing helpers, and routing functions. This is the largest module (273 lines) and contains the core business logic.

#### System Prompts

| Constant | Used By | Description |
|---|---|---|
| `PLANNER_SYS` | `planner()` | Instructs LLM to produce a JSON array of sub-questions |
| `SUMMARIZER_SYS` | `summarizer()` | Instructs LLM to extract key findings with source attribution |
| `FACTCHECK_SYS` | `fact_checker()` | Instructs LLM to return a verdict JSON with optional gaps |
| `WRITER_SYS` | `writer_node()` | Instructs LLM to write a cited Markdown report |

#### Parsing Helpers

| Function | Input | Output | Fallback |
|---|---|---|---|
| `_extract_json(text)` | Raw LLM response | Parsed JSON value | `None` |
| `_first_block(text, open, close)` | Text, delimiter chars | Substring between delimiters | `None` |
| `parse_subquestions(text)` | LLM response | `list[str]` of sub-questions | Line-split fallback |
| `parse_verdict(text)` | LLM response | `(verdict, gaps)` tuple | `("pass", [])` |

The `_extract_json` function handles multiple LLM output formats:
1. Direct JSON
2. JSON wrapped in `` ```json ``` `` fences
3. JSON embedded within prose text (extracts first `{...}` or `[...]` block)

#### Node Functions

| Function | LangGraph Node | LLM Call | Tool Call | Key Logic |
|---|---|---|---|---|
| `planner(state)` | `planner` | Yes (ChatGroq) | No | Generates sub-questions, falls back to original query |
| `searcher(state)` | `searcher` | No | Yes (Tavily) | Parallel fan-out, error-tolerant |
| `summarizer(state)` | `summarizer` | Yes (ChatGroq) | No | Truncates content to 3000 chars per block |
| `fact_checker(state)` | `fact_checker` | Yes (ChatGroq, temp=0) | No | Returns verdict + gaps |
| `refine(state)` | `refine` | No | No | Passes gaps as new sub-questions |
| `writer_node(state)` | `writer` | Yes (ChatGroq) | No | Deduplicates source URLs |

#### Routing Functions

| Function | Purpose | Returns |
|---|---|---|
| `fan_out_searches(state)` | Creates `Send` objects for parallel search | `list[Send]` |
| `route_after_factcheck(state)` | Decides whether to refine or write | `"refine"` or `"write"` |

---

### `app/graph.py` — Graph Assembly

**Purpose:** Assembles all nodes and edges into a compiled LangGraph `StateGraph`.

| Function | Description |
|---|---|
| `build_graph()` | Creates `StateGraph(ResearchState)`, adds 6 nodes, wires edges, returns compiled graph |
| `graph` | Module-level compiled graph instance |

**Graph wiring:**

```
START → planner
planner →(conditional: fan_out_searches)→ [searcher]
searcher → summarizer
summarizer → fact_checker
fact_checker →(conditional: route_after_factcheck)→ {refine, writer}
refine →(conditional: fan_out_searches)→ [searcher]
writer → END
```

**CLI smoke test:** Running `python -m app.graph` executes a hardcoded question through the graph and prints agent progress and the final report to stdout.

---

### `app/main.py` — FastAPI Application

**Purpose:** HTTP server entry point. Serves the frontend, provides a health-check endpoint, and streams research results via SSE.

#### Routes

| Method | Path | Handler | Description |
|---|---|---|---|
| `GET` | `/` | `index()` | Serves `static/index.html` |
| `GET` | `/api/health` | `health()` | Returns `{ok, missing_keys, model}` |
| `GET` | `/api/research` | `research(q)` | SSE stream of agent progress and final report |

#### SSE Event Generator (`event_gen`)

The async generator inside `research()`:

1. Checks `settings.keys_present` — emits error if keys missing.
2. Calls `graph.astream()` with `stream_mode=["custom", "updates"]`.
3. For each streamed item:
   - `custom` mode → emits `progress` SSE event (agent status updates).
   - `updates` mode → checks for `report` key → emits `report` SSE event.
4. After stream exhaustion → emits `done` event.
5. Catches any exception → emits `error` event.
6. Checks `request.is_disconnected()` to stop streaming if client disconnects.

---

### `static/index.html` — Frontend UI

**Purpose:** Single-page web interface with real-time agent-activity visualization.

| Component | Implementation | Description |
|---|---|---|
| Agent pipeline cards | 5 `div` elements with status dots | Shows idle/running/done/error per agent |
| Activity log | Scrollable div, appended via JS | Logs agent messages in real time |
| Report panel | `div#report` rendered by Marked.js | Displays the final Markdown report |
| Search form | `form#form` with text input | Submits query via EventSource |
| Example chips | Dynamically created buttons | Pre-fill the query field |

**JavaScript functions:**

| Function | Purpose |
|---|---|
| `setCard(key, status)` | Updates a pipeline card's visual state |
| `advance(key, status)` | Marks preceding agents as "done" when a later agent starts |
| `resetUI()` | Resets all cards to idle, clears log and report |
| `addLog(agent, message, kind)` | Appends a styled entry to the Activity log |
| `escapeHtml(s)` | Escapes HTML entities in log messages |
| `run(query)` | Opens EventSource, registers event handlers, manages lifecycle |
| `finish()` | Re-enables UI controls, closes EventSource |

## Data Validation

| Validation | Location | Mechanism |
|---|---|---|
| Query minimum length (3 chars) | `main.py:research()` | FastAPI `Query(..., min_length=3)` |
| API key presence | `config.py:Settings.keys_present` | Property check before graph execution |
| Sub-question parsing | `agents.py:parse_subquestions()` | JSON parse with line-split fallback |
| Verdict parsing | `agents.py:parse_verdict()` | JSON parse with safe default `("pass", [])` |
| Client-side query length | `index.html` JS | `query.length < 3` check in submit handler |

## Prompt Management

All prompts are defined as module-level string constants in `agents.py`:

| Prompt | Lines | Dynamic Elements |
|---|---|---|
| `PLANNER_SYS` | 25-31 | `{n}` — max number of sub-questions |
| `SUMMARIZER_SYS` | 33-37 | None |
| `FACTCHECK_SYS` | 40-49 | None |
| `WRITER_SYS` | 51-57 | None |

Each prompt follows a consistent pattern:
1. Role assignment ("You are the ...")
2. Task description
3. Output format specification
4. Constraints (e.g., "do not invent anything")

## Logging and Monitoring

The application does not implement structured logging, log files, or monitoring infrastructure. Observability is provided through:

- **SSE progress events:** Real-time agent status visible in the browser UI.
- **Console output:** Uvicorn's default access and error logging.
- **CLI smoke test:** `python -m app.graph` prints agent progress to stdout.

> [!NOTE]
> There is no application-level logging framework (e.g., Python `logging` module), no request tracing, and no metrics collection. These are potential areas for future improvement.
