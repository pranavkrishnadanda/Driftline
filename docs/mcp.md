# Driftline MCP server

The gateway serves an [MCP](https://modelcontextprotocol.io) server at `/mcp` over
Streamable HTTP, so agents such as Claude Code and Cursor can ask version-aware questions.
It has five tools: `ask`, `list_sources`, `diff_versions`, `get_timeline` and
`watch_answer`. The repo also ships a Claude Code Skill,
[`.claude/skills/driftline/SKILL.md`](../.claude/skills/driftline/SKILL.md), that teaches
an agent when and how to use them.

- URL: `http://localhost:8010/mcp` with the Compose stack (`DRIFTLINE_GATEWAY_PORT`, default 8010).
- Transport: Streamable HTTP (the MCP Python SDK's server, mounted in the FastAPI gateway).
- Auth: a tenant API key as `Authorization: Bearer <key>`, always required.

## Setup

1. Start the stack and ingest some documents (see the [README](../README.md#quick-start)).
   Ingesting creates the tenant, for example `demo`.
2. Create an API key for the tenant (see [API keys](#api-keys)) and export it:

   ```bash
   export DRIFTLINE_KEY=<the key>
   ```

3. Register the server with Claude Code:

   ```bash
   claude mcp add --transport http driftline http://localhost:8010/mcp --header "Authorization: Bearer $DRIFTLINE_KEY"
   ```

   The shell expands `$DRIFTLINE_KEY` when the command runs, and the key is stored in
   your Claude Code config (`~/.claude.json`, local scope by default). To share the
   server with your team, add `--scope project`. This writes `.mcp.json` in the
   project root. Replace the key in it with an environment reference, so it is never
   committed and each person uses their own key:

   ```json
   {
     "mcpServers": {
       "driftline": {
         "type": "http",
         "url": "http://localhost:8010/mcp",
         "headers": { "Authorization": "Bearer ${DRIFTLINE_KEY}" }
       }
     }
   }
   ```

4. Check it: `claude mcp list` should show `driftline` as connected, and `/mcp` inside
   Claude Code lists its tools. Note that `claude mcp add` doesn't validate the key, so a
   wrong key only shows up here.

**Cursor:** add the same server to `.cursor/mcp.json` (or `~/.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "driftline": {
      "url": "http://localhost:8010/mcp",
      "headers": { "Authorization": "Bearer ${env:DRIFTLINE_KEY}" }
    }
  }
}
```

## API keys

Each tenant has one API key. Driftline stores only its SHA-256 hex digest
(`tenants.api_key_hash`, computed by `driftline.auth.hash_api_key`), and a request is
served for the tenant whose hash matches. A key reads only its own tenant's sources,
documents and answers: another tenant's ids are reported as not found.

There is no CLI for keys yet, so set one with SQL. First generate a random key:

```bash
python3 -c "import secrets; print('dl_' + secrets.token_urlsafe(32))"
```

Then store its hash, replacing `YOUR_KEY` with the key and `demo` with the tenant name.
This creates the tenant if it doesn't exist, and replaces (rotates) its key if it does:

```sql
INSERT INTO tenants (name, api_key_hash)
VALUES ('demo', encode(sha256(convert_to('YOUR_KEY', 'UTF8')), 'hex'))
ON CONFLICT (name) DO UPDATE SET api_key_hash = EXCLUDED.api_key_hash;
```

With Compose, run it through `psql` in the Postgres container:

```bash
docker compose -f deploy/compose/docker-compose.yml exec postgres \
  psql -U driftline -d driftline -c "INSERT INTO tenants (name, api_key_hash) VALUES ('demo', encode(sha256(convert_to('YOUR_KEY', 'UTF8')), 'hex')) ON CONFLICT (name) DO UPDATE SET api_key_hash = EXCLUDED.api_key_hash;"
```

The SQL computes the same SHA-256 hex digest as `hash_api_key`. To
compute the hash in Python instead, run this from `backend/`:

```bash
uv run python -c "from driftline.auth import hash_api_key; print(hash_api_key('YOUR_KEY'))"
```

A tenant created by `python -m driftline.ingest enqueue` has an empty hash, which no key
matches. Its MCP access is off until you set a key. Use a different key for each tenant:
a hash shared by two tenants identifies neither.

## Allowed hosts (`DRIFTLINE_MCP_ALLOWED_HOSTS`)

`/mcp` has the MCP SDK's DNS-rebinding protection turned on. A request whose `Host`
header isn't in the allowed list gets **421 Misdirected Request**. A browser request
whose `Origin` isn't one of the same hosts (over http or https) gets **403**. The list
is a JSON array; `name:*` allows any port.

| Where | Default |
|---|---|
| Gateway settings (`driftline.config.Settings`) | `["localhost:*","127.0.0.1:*","[::1]:*"]` |
| Compose (`deploy/compose/docker-compose.yml`) | the same, plus `"gateway:*"` so other containers can call `http://gateway:8000/mcp` |

Add every name that clients use to reach the gateway. For Compose, set it in
`deploy/compose/.env`:

```bash
DRIFTLINE_MCP_ALLOWED_HOSTS=["localhost:*","127.0.0.1:*","[::1]:*","gateway:*","driftline.example.com"]
```

For a remote host behind a reverse proxy, list the public name, for example
`"driftline.example.com"`, or `"driftline.example.com:*"` if the URL has a port. The proxy
must forward the original `Host` header. Serve it over HTTPS, since the bearer key
travels in every request.

## Tool reference

These tables are taken from the tools' real input schemas (the tool list of `build_mcp`).
`backend/tests/mcp/test_skill_doc.py` fails if they drift from the code.

### `ask`

Answers a question from the documents in force at `as_of`, with verified exact-quote
citations. It waits up to `timeout_s` for the answer.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `question` | string, 1 to 2000 chars | yes | | The question. |
| `as_of` | string or null | no | now | When to answer for: an ISO date or timestamp, a year (`"2023"`), a month (`"June 2023"`) or a release (`"v1.28"`). |
| `source_kinds` | list of `openfda`, `git_docs`, `upload`, or null | no | all | Only search these source kinds. |
| `timeout_s` | integer, 1 to 300 | no | 60 | Seconds to wait for the answer. |

Returns the answer: `status` (`answered`, `insufficient_evidence` or `refused`),
`answer`, `claims`, `citations`, `dropped_claims`, `nearest_sources`, `as_of`,
`confidence`, `degraded`, `cached`, `answer_id` and `cost_usd`. Each citation has
`quote`, `chunk_id`, `version_id`, `document_id`, `title`, `external_id`, `version_no`,
`section_path`, `valid_from` and `valid_to` (null: still in force). If the answer isn't
ready within `timeout_s`, it returns `{"status": "running", "job_id": "..."}`. The job
keeps running, and `GET /v1/jobs/{job_id}` returns its answer later. An `as_of` that
isn't a date, year, month or known release is a tool error. Backpressure is the tool
error "Driftline is busy; retry in N s".

Example: `ask(question="How often should ALT be checked?", as_of="2023")`

### `list_sources`

Lists the document sources Driftline answers from for this key's tenant.

No parameters.

Returns `{"sources": [...]}`, where each source has `id`, `kind` (`openfda`, `git_docs`
or `upload`), `status`, `schedule`, `last_polled_at` and `documents` (a count).

### `diff_versions`

Shows what changed in a document between two of its versions. The default is the
previous version against the latest.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `document_id` | string (UUID) | yes | | The document, for example a citation's `document_id`. |
| `from_version` | integer ≥ 1, or null | no | the one before `to_version` | Version number to diff from. |
| `to_version` | integer ≥ 1, or null | no | latest | Version number to diff to. |

Version numbers are the `version_no` values from `get_timeline`. Returns `document_id`,
`from_version`, `to_version`, `from_version_id`, `to_version_id`, `sections` (each
section's `section_path` and `status`: `added`, `removed`, `changed` or `unchanged`),
`diff` (one unified diff of the sections that differ) and `truncated`. The diff is
capped at 16 KB. When it is cut, `truncated` is true and the diff ends with a
`... diff truncated` line.

Example: `diff_versions(document_id="…", from_version=1, to_version=2)`

### `get_timeline`

Returns a document's version history and relations.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `document_id` | string (UUID) | yes | | The document. |

Returns `document_id`, `external_id`, `title`, and `versions`. Each version has
`version_id`, `version_no`, `version_key` (such as `release-1.28`), `valid_from`,
`valid_to` (null: in force now), `diff_from_prev` (the sections changed from the
previous version) and `created_at`. It also returns `relations`: `outgoing` (links this
document declares, such as `supersedes`) and `incoming` (links that point at it).

Example: `get_timeline(document_id="…")`

### `watch_answer`

Watches an answer. Driftline re-checks its claims whenever a document it cites changes,
and raises a drift alert when a claim no longer holds.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `answer_id` | string (UUID) | yes | | The `answer_id` that `ask` returned. |

Returns `{"answer_id": "...", "watched": true}`.

Example: `watch_answer(answer_id="…")`

Unknown ids, and ids that belong to another tenant, are tool errors ("... not found")
in `diff_versions`, `get_timeline` and `watch_answer`.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `401 Unauthorized` with `WWW-Authenticate: Bearer ...`; `claude mcp list` shows the server failing to connect | The `Authorization` header is missing, or the key matches no tenant. Check that `DRIFTLINE_KEY` was set when you ran `claude mcp add` (an empty variable gives `Bearer ` with no key), and that the tenant's hash was set with the SQL above. Re-add the server with `claude mcp remove driftline`, then `claude mcp add ...`. |
| `421 Misdirected Request` ("Invalid Host header") | The `Host` the client sent isn't in `DRIFTLINE_MCP_ALLOWED_HOSTS`. Add the host name, for example `gateway:*` or `driftline.example.com`, and restart the gateway. |
| `403` ("Invalid Origin header") | A browser-based client sent an `Origin` whose host isn't allowed. Add that host to the same list. |
| `ask` returns `{"status": "running", ...}` | The answer took longer than `timeout_s`. Raise `timeout_s` (max 300), or read `GET /v1/jobs/{job_id}`. Check that an agent worker is running: `docker compose -f deploy/compose/docker-compose.yml ps`. |
| Tool error "Driftline is busy; retry in N s" | The agent queue is over its backpressure limit. Retry after N seconds, or scale the agent workers. |
| Tool error about `as_of` | Use an ISO date, a year, a month (`June 2023`) or a release that some document has (`v1.28`). |
| Connection refused | The gateway isn't running, or it is on another port. Check `curl localhost:8010/healthz` and `DRIFTLINE_GATEWAY_PORT`. |
