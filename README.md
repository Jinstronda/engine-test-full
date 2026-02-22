# Engine-2

A multi-agent LLM engine built on LangGraph and FastAPI. Configured via a single `config.yaml` using a three-level hierarchy: **endpoints → systems → agent instances**.

---

## Concepts

### The three levels

```
endpoint          — an HTTP route with a typed contract and a prompt template
  └── system      — a named agent topology (single / sequential / orchestrator / decentralised)
        └── agent — an instance of a hardcoded agent type with a custom prompt
```

**Agent types** are hardcoded in `app/agents/registry.py`. Each type fixes the model and tool set. You configure instances (prompts only) in `config.yaml`.

| Type | Tools |
|---|---|
| `researcher` | `search_web` |
| `coder` | `calculate` |
| `writer` | _(none)_ |
| `analyst` | `calculate`, `search_web` |
| `validator` | `accept_output`, `reject_output` |

### Topologies

| Topology | Behaviour |
|---|---|
| `single` | One agent runs and returns. |
| `sequential` | Agents run in order. The last agent must be a `validator` type — it calls `accept_output` or `reject_output`. Rejected pipelines retry from the first agent (max 3 times). |
| `orchestrator` | The first agent routes to specialists by responding with `{"agent": "name"}`. Specialists return control to the first agent. Finishes with `{"agent": "__done__", "response": "..."}`. |
| `decentralised` | Any agent can delegate to a peer with `{"delegate": "name", "message": "..."}`. If an agent responds without that JSON it is the final answer. |

### Agent naming

Agents are named automatically: `{type}_{index}`. So a system with a `researcher` at index 0 and a `coder` at index 1 produces agents `researcher_0` and `coder_1`. Use these names in orchestrator routing prompts.

### Async functions

Scheduled jobs that run a system on a cron schedule without an HTTP trigger. Useful for recurring tasks (e.g. daily digests). The scheduler starts on boot and is restarted on `/reload`.

---

## Setup

```bash
cd engine-2
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

export ANTHROPIC_API_KEY=sk-ant-...
python run.py
```

The server starts at `http://localhost:8000` with hot-reload enabled.

### Docker

```bash
docker build -t fabriq-engine-2 .
docker run -p 9002:8000 \
  -v $(pwd)/config.yaml:/app/config.yaml \
  -e ANTHROPIC_API_KEY=sk-ant-... \
  fabriq-engine-2
```

`config.yaml` is volume-mounted so you can edit it and call `/reload` without rebuilding the image.

---

## HTTP API

### `POST /run/{endpoint_slug}`

Runs an endpoint and streams the response as [Server-Sent Events](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events).

**Request body:**
```json
{ "data": { "field": "value" } }
```
The keys in `data` must satisfy the endpoint's `contract`. Extra keys are ignored.

**SSE event types:**

| `type` | Meaning |
|---|---|
| `status` | Processing update — which agent is active. |
| `token` | The final response content. |
| `validation_rejected` | The validator rejected the output; pipeline is retrying. |
| `error` | Something went wrong. |
| `done` | Stream is finished. Always the last event. |

Each event is a JSON-encoded `RunResponseChunk`:
```json
{"type": "token", "content": "Here is the answer...", "agent": "writer_0"}
```

### `GET /health`

Returns the engine status and counts.
```json
{"status": "healthy", "systems": 5, "endpoints": 4}
```

### `GET /config`

Returns the full parsed config as JSON. Useful for debugging.

### `POST /reload`

Re-reads `config.yaml` from disk, invalidates the graph cache, and restarts the scheduler. Use this after editing the config file.
```json
{"status": "reloaded", "systems": 5, "endpoints": 4}
```

### Authentication

If `api_key` is set in `config.yaml`, all `POST` requests require the header:
```
X-API-Key: your-key-here
```
`GET` endpoints are always public. When `api_key` is `null` (the default), auth is disabled.

---

## `config.yaml` reference

```yaml
api_key: null             # string or null — enables X-API-Key auth
allowed_origins: ["*"]    # CORS origins

systems:
  - id: my-system         # unique identifier, referenced by endpoints
    name: My System       # human label
    description: ...      # optional
    topology: single      # single | sequential | orchestrator | decentralised
    agents:
      - type: researcher  # must be a key in AGENT_TYPE_REGISTRY
        prompt: "..."     # system prompt for this instance

endpoints:
  - slug: my-endpoint     # URL path: /run/my-endpoint
    description: ...      # optional
    system_id: my-system  # must match a system id above
    contract:
      - name: user_input  # required field name in request.data
        type: string      # string | number | boolean
    prompt: "Answer: {user_input}"  # template — {placeholders} filled from data

async_functions:
  - system_id: my-system
    prompt: "Summarise recent news."
    schedule:
      frequency: daily    # daily | weekly | monthly
      hour: 8             # 0-23 UTC
      day_of_week: mon    # required for weekly (mon/tue/.../sun or 0-6)
      day_of_month: 1     # required for monthly (1-31)
```

**Validation rules enforced at startup:**
- Every `endpoint.system_id` must match a system `id`.
- Every `async_function.system_id` must match a system `id`.
- Every `agent.type` must exist in the registry.
- `weekly` schedules require `day_of_week`; `monthly` require `day_of_month`.

---

## Walkthrough

The demo config ships with four endpoints covering every topology, plus one async function. Start the server, then follow the steps below in order.

### 0. Start the server

```bash
cd engine-2
source venv/bin/activate
export ANTHROPIC_API_KEY=sk-ant-...
python run.py
```

You should see:
```
INFO:     Engine-2 started (origins=['*'], auth=disabled, systems=5, endpoints=4, async_functions=1)
INFO:     Uvicorn running on http://0.0.0.0:8000
```

---

### 1. Health check

Confirms the engine is up and how many systems/endpoints were loaded.

```bash
curl http://localhost:8000/health
```

Expected:
```json
{"status": "healthy", "systems": 5, "endpoints": 4}
```

---

### 2. Inspect the loaded config

```bash
curl http://localhost:8000/config | python3 -m json.tool
```

This returns the full parsed config — useful for confirming that your YAML was read correctly.

---

### 3. Single-agent endpoint (`/run/quick-answer`)

**System:** `quick-research` — topology `single`, one `researcher_0`.

The request data must include `user_input` (string, required by the contract).

```bash
curl -X POST http://localhost:8000/run/quick-answer \
  -H "Content-Type: application/json" \
  -d '{"data": {"user_input": "What is LangGraph?"}}'
```

You will see a stream of SSE events:
```
data: {"type": "status", "content": "Processing request...", "agent": null}
data: {"type": "status", "content": "Agent 'researcher_0' processing...", "agent": "researcher_0"}
data: {"type": "token",  "content": "LangGraph is a library...", "agent": "researcher_0"}
data: {"type": "done",   "content": "", "agent": null}
```

**Test contract validation (should return 422):**

```bash
curl -X POST http://localhost:8000/run/quick-answer \
  -H "Content-Type: application/json" \
  -d '{"data": {"wrong_field": "hello"}}'
```

Expected: `422 Unprocessable Entity` with `"Missing required field 'user_input'"`.

**Test unknown endpoint (should return 404):**

```bash
curl -X POST http://localhost:8000/run/does-not-exist \
  -H "Content-Type: application/json" \
  -d '{"data": {}}'
```

Expected: `404 Not Found`.

---

### 4. Sequential + validator endpoint (`/run/content-pipeline`)

**System:** `content-pipeline` — topology `sequential`.
- `writer_0` drafts content.
- `validator_1` reviews it and calls `accept_output` or `reject_output`.
- If rejected, the pipeline restarts from `writer_0` (up to 3 times).

```bash
curl -X POST http://localhost:8000/run/content-pipeline \
  -H "Content-Type: application/json" \
  -d '{"data": {"topic": "the future of serverless computing"}}'
```

Normal flow (accepted on first try):
```
data: {"type": "status",  "content": "Processing request...", "agent": null}
data: {"type": "status",  "content": "Agent 'writer_0' processing...", "agent": "writer_0"}
data: {"type": "status",  "content": "Agent 'validator_1' processing...", "agent": "validator_1"}
data: {"type": "token",   "content": "The future of serverless...", "agent": "validator_1"}
data: {"type": "done",    "content": "", "agent": null}
```

If the validator rejects (you will see this in the stream before the retry):
```
data: {"type": "validation_rejected", "content": "Pipeline output rejected, retrying...", "agent": "validator_1"}
data: {"type": "status",  "content": "Agent 'writer_0' processing...", "agent": "writer_0"}
...
```

To force a rejection, temporarily set a strict validator prompt in `config.yaml`, then `/reload`.

---

### 5. Orchestrator endpoint (`/run/analyze`)

**System:** `code-analysis` — topology `orchestrator`.
- `analyst_0` receives the request and decides which specialist to call.
- `coder_1` handles code questions.
- `researcher_2` handles research questions.
- When done, `analyst_0` responds with `{"agent": "__done__", "response": "..."}`.

**Route to the coder:**

```bash
curl -X POST http://localhost:8000/run/analyze \
  -H "Content-Type: application/json" \
  -d '{"data": {"user_input": "What is the time complexity of quicksort?"}}'
```

**Route to the researcher:**

```bash
curl -X POST http://localhost:8000/run/analyze \
  -H "Content-Type: application/json" \
  -d '{"data": {"user_input": "Who invented the internet?"}}'
```

Watch the `status` events — you will see `analyst_0` activate first, then the routed specialist, then `analyst_0` again to synthesise the final answer.

---

### 6. Decentralised endpoint (`/run/collab`)

**System:** `collab-research` — topology `decentralised`.
- `researcher_0` is the entry point.
- Either agent can delegate to the other with `{"delegate": "name", "message": "..."}`.
- The pipeline ends when an agent responds without a delegation JSON.

**Give a research question (researcher handles directly):**

```bash
curl -X POST http://localhost:8000/run/collab \
  -H "Content-Type: application/json" \
  -d '{"data": {"user_input": "What are the main cloud providers in 2025?"}}'
```

**Give a code question (researcher delegates to coder):**

```bash
curl -X POST http://localhost:8000/run/collab \
  -H "Content-Type: application/json" \
  -d '{"data": {"user_input": "Write a Python function to parse JSON safely."}}'
```

---

### 7. Hot reload

Edit `config.yaml` while the server is running — for example, change a prompt or add a new endpoint — then call:

```bash
curl -X POST http://localhost:8000/reload
```

Expected:
```json
{"status": "reloaded", "systems": 5, "endpoints": 4}
```

The graph cache is invalidated, the scheduler is restarted with the new async function schedule, and the next request picks up the new config. No container restart needed.

---

### 8. Authentication

Enable auth by setting a key in `config.yaml`:

```yaml
api_key: my-secret-key
```

Then reload:

```bash
curl -X POST http://localhost:8000/reload
```

Now all `POST` requests require the header:

```bash
curl -X POST http://localhost:8000/run/quick-answer \
  -H "Content-Type: application/json" \
  -H "X-API-Key: my-secret-key" \
  -d '{"data": {"user_input": "What is Python?"}}'
```

Without the header you get `401 Unauthorized`. The `/health` and `/config` `GET` endpoints remain public.

---

### 9. Docker end-to-end

```bash
cd engine-2
docker build -t fabriq-engine-2 .

docker run -p 9002:8000 \
  -v $(pwd)/config.yaml:/app/config.yaml \
  -e ANTHROPIC_API_KEY=sk-ant-... \
  fabriq-engine-2
```

All the same curl commands work against port 9002. Edit the local `config.yaml` and call `POST http://localhost:9002/reload` to apply changes without rebuilding.

---

## Consuming the SSE stream

The `/run/*` endpoints return `text/event-stream`. Each event is a line `data: <json>\n\n`. To consume programmatically:

**Python (httpx):**
```python
import httpx, json

with httpx.Client() as client:
    with client.stream(
        "POST",
        "http://localhost:8000/run/quick-answer",
        json={"data": {"user_input": "What is Python?"}},
    ) as r:
        for line in r.iter_lines():
            if line.startswith("data: "):
                chunk = json.loads(line[6:])
                if chunk["type"] == "token":
                    print(chunk["content"])
```

**JavaScript (fetch):**
```javascript
const res = await fetch("http://localhost:8000/run/quick-answer", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ data: { user_input: "What is Python?" } }),
});

const reader = res.body.getReader();
const decoder = new TextDecoder();

while (true) {
  const { done, value } = await reader.read();
  if (done) break;
  const text = decoder.decode(value);
  for (const line of text.split("\n")) {
    if (line.startsWith("data: ")) {
      const chunk = JSON.parse(line.slice(6));
      if (chunk.type === "token") console.log(chunk.content);
    }
  }
}
```

---

## Adding a new agent type

Edit `app/agents/registry.py` and add an entry to `AGENT_TYPE_REGISTRY`:

```python
"summariser": AgentTypeDefinition(
    name="summariser",
    description="Condenses long content into concise summaries.",
    model="claude-sonnet-4-20250514",
    tools=[],
),
```

Then reference it in `config.yaml`:
```yaml
systems:
  - id: my-system
    topology: single
    agents:
      - type: summariser
        prompt: "Summarise the following in three bullet points."
```

Restart (or `/reload`) and the new type is available.

## Adding a new tool

Add a function to `app/tools/builtins.py`:

```python
@register
@tool
def fetch_url(url: str) -> str:
    """Fetch the text content of a URL."""
    import urllib.request
    with urllib.request.urlopen(url) as r:
        return r.read(4096).decode()
```

Then assign it to an agent type in `registry.py`:
```python
"researcher": AgentTypeDefinition(
    ...
    tools=["search_web", "fetch_url"],
),
```
