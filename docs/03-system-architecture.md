# System Architecture

## Overall Architecture

The application follows a **single-process, event-driven architecture** with an async Python backend serving a static single-page frontend. There is no database, no message queue, and no background workers — all state lives in-memory within the LangGraph execution context for the duration of a single request.

```mermaid
graph TB
    subgraph Client["Client Layer"]
        Browser["Web Browser<br/>index.html + Tailwind + JS"]
    end

    subgraph Server["Application Layer (Single Process)"]
        FastAPI["FastAPI + Uvicorn<br/>ASGI Server"]
        LangGraph["LangGraph StateGraph<br/>Agent Orchestration"]
        Agents["Agent Node Functions<br/>planner, searcher, summarizer,<br/>fact_checker, refine, writer"]
    end

    subgraph External["External Services"]
        Groq["Groq API<br/>LLM Inference"]
        Tavily["Tavily API<br/>Web Search"]
    end

    Browser <-->|"HTTP + SSE"| FastAPI
    FastAPI --> LangGraph
    LangGraph --> Agents
    Agents -->|"langchain-groq"| Groq
    Agents -->|"langchain-tavily"| Tavily
```

## Frontend Architecture

The frontend is a **single HTML file** (`static/index.html`) with no build step, no framework, and no bundler.

```mermaid
graph TD
    subgraph HTML["index.html (249 lines)"]
        Structure["Semantic HTML Structure"]
        Styling["Tailwind CSS via CDN<br/>+ Custom glassmorphism CSS"]
        Logic["Vanilla JavaScript<br/>~150 lines"]
    end

    subgraph UI["UI Components"]
        Hero["Hero Section<br/>Title + Description"]
        SearchForm["Search Form<br/>Input + Submit Button"]
        Examples["Example Question Chips"]
        Pipeline["Agent Pipeline Cards<br/>5 agent status indicators"]
        ActivityLog["Activity Log Panel<br/>Scrollable event feed"]
        ReportPanel["Report Panel<br/>Markdown-rendered output"]
    end

    subgraph External["External CDN Resources"]
        TW["Tailwind CSS 3.4.13"]
        Marked["Marked.js 14.1.2"]
        Fonts["Google Fonts: Inter"]
    end

    Structure --> UI
    Styling --> TW
    Styling --> Fonts
    Logic --> ES["EventSource API<br/>SSE Client"]
    Logic --> Marked
    ES -->|"progress events"| Pipeline
    ES -->|"progress events"| ActivityLog
    ES -->|"report event"| ReportPanel
```

**Key design decisions:**
- No framework dependency — vanilla JS keeps the frontend zero-build and self-contained.
- Tailwind via CDN — avoids npm/node toolchain.
- `EventSource` for SSE — native browser API, no WebSocket library needed.
- `marked.js` renders the LLM-generated Markdown report on the client side.

## Backend Architecture

```mermaid
graph TD
    subgraph Entry["Entry Point"]
        Main["main.py<br/>FastAPI app instance"]
    end

    subgraph Routes["Route Handlers"]
        Index["GET /<br/>Serve index.html"]
        Health["GET /api/health<br/>Key validation"]
        Research["GET /api/research<br/>SSE stream"]
    end

    subgraph Core["Core Modules"]
        Config["config.py<br/>Pydantic Settings"]
        LLM["llm.py<br/>ChatGroq Factory"]
        Tools["tools.py<br/>TavilySearch Factory"]
        State["state.py<br/>ResearchState TypedDict"]
        AgentsMod["agents.py<br/>Node Functions + Prompts"]
        GraphMod["graph.py<br/>StateGraph Assembly"]
    end

    Main --> Routes
    Main --> Config
    Research --> GraphMod
    GraphMod --> AgentsMod
    GraphMod --> State
    AgentsMod --> LLM
    AgentsMod --> Tools
    AgentsMod --> Config
    LLM --> Config
    Tools --> Config
```

| Module | File | Responsibility |
|---|---|---|
| Configuration | `config.py` | Load `.env`, validate keys, export to `os.environ` |
| LLM Factory | `llm.py` | Create `ChatGroq` instances with configured model and temperature |
| Search Tool | `tools.py` | Create `TavilySearch` instances with configured result limit |
| State Schema | `state.py` | Define `ResearchState` TypedDict with reducers |
| Agent Logic | `agents.py` | All node functions, prompts, parsing helpers, routing logic |
| Graph Assembly | `graph.py` | Wire nodes and edges into a compiled `StateGraph` |
| API Server | `main.py` | FastAPI routes, static file serving, SSE event generator |

## AI Orchestration Architecture

The AI layer uses **LangGraph's StateGraph** with the following architecture:

```mermaid
stateDiagram-v2
    [*] --> planner
    planner --> searcher: Send() fan-out
    searcher --> summarizer: Results merged via reducer
    summarizer --> fact_checker
    fact_checker --> refine: needs_more AND retries < max
    fact_checker --> writer: pass OR retries exhausted
    refine --> searcher: Send() fan-out (loop)
    writer --> [*]
```

**Key architectural patterns:**

| Pattern | Implementation |
|---|---|
| Fan-out parallelism | `Send("searcher", ...)` per sub-question |
| State merging | `Annotated[list, operator.add]` reducer on `search_results` |
| Conditional routing | `route_after_factcheck()` returns "refine" or "write" |
| Streaming progress | `get_stream_writer()` emits events from inside nodes |
| Retry loop | `refine` node increments `retries`, re-enters fan-out |

### Agent Responsibilities

```mermaid
graph LR
    P["Planner<br/>Query → Sub-questions<br/>(JSON array)"]
    S["Searcher<br/>Sub-question → Web results<br/>(Tavily)"]
    SM["Summarizer<br/>Results → Key findings<br/>(Bullet points)"]
    FC["Fact-Checker<br/>Findings → Verdict<br/>(pass / needs_more)"]
    W["Writer<br/>Findings → Cited report<br/>(Markdown)"]

    P -->|"1:N"| S
    S -->|"N:1"| SM
    SM --> FC
    FC --> W
```

## State Architecture

The `ResearchState` is a `TypedDict` that acts as the shared memory across all agents:

```mermaid
classDiagram
    class ResearchState {
        +str query
        +list~str~ sub_questions
        +str sub_question
        +Annotated~list, operator.add~ search_results
        +list summaries
        +str verdict
        +list~str~ gaps
        +int retries
        +str report
    }
```

| Field | Writer | Reader(s) | Reducer |
|---|---|---|---|
| `query` | User input | All agents | Last-write-wins |
| `sub_questions` | Planner, Refine | fan_out_searches | Last-write-wins |
| `sub_question` | Send() payload | Searcher | Per-invocation |
| `search_results` | Searcher (parallel) | Summarizer, Fact-Checker, Writer | `operator.add` (concatenation) |
| `summaries` | Summarizer | Fact-Checker, Writer | Last-write-wins |
| `verdict` | Fact-Checker | route_after_factcheck | Last-write-wins |
| `gaps` | Fact-Checker | Refine, route_after_factcheck | Last-write-wins |
| `retries` | Planner, Refine | route_after_factcheck | Last-write-wins |
| `report` | Writer | SSE event generator | Last-write-wins |

## Deployment Architecture

```mermaid
graph LR
    subgraph Local["Developer Machine"]
        subgraph Runtime["Python 3.12 + venv"]
            Uvicorn["Uvicorn<br/>ASGI Server<br/>localhost:8000"]
            App["FastAPI + LangGraph"]
        end
        Env[".env file<br/>Secrets + Config"]
    end

    subgraph Cloud["External Cloud APIs"]
        Groq["Groq<br/>api.groq.com"]
        Tavily["Tavily<br/>api.tavily.com"]
    end

    Browser["Browser"] <-->|"HTTP/SSE"| Uvicorn
    Uvicorn --> App
    Env -.->|"loaded at startup"| App
    App -->|"HTTPS"| Groq
    App -->|"HTTPS"| Tavily
```

The application is designed for **local development** deployment:
- Single-process Uvicorn server
- No containerization (no Dockerfile)
- No database to provision
- Only external dependencies are API keys for Groq and Tavily
