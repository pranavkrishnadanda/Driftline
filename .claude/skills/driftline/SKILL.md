---
name: driftline
description: Answer version- or date-sensitive questions from the documents Driftline has ingested (drug labels from openFDA/DailyMed, Kubernetes docs per release, uploaded document folders) through the Driftline MCP server, with exact-quote citations from the versions in force at a given time. Use it when the user asks what a document said as of a date or release, what changed between versions, when a rule changed, or wants to be alerted when a cited source changes. Always pass as_of for historical questions.
---

# Driftline

Driftline is a version-aware knowledge engine. It stores every version of each ingested
document with a validity window `[valid_from, valid_to)`, and it answers a question only
from the versions that were in force at the requested time. Each claim is backed by an
exact quote, and every quote is checked against the cited version.

## When to use it

Use Driftline when the answer depends on **when** or **which version** you mean, and the
documents are in Driftline's corpora (call `list_sources()` if you are not sure):

- "What did the label say about liver monitoring in 2023?"
- "Was the `PodSecurityPolicy` API still served in Kubernetes v1.24?"
- "When did the dosing guidance change, and what exactly changed?"
- "Is the answer you gave me last month still true?"

Don't use it for general knowledge, for documents Driftline hasn't ingested, or when the
user wants your own analysis rather than what the sources say.

## Connect (once per machine)

The gateway serves MCP over Streamable HTTP at `/mcp` and needs a tenant API key as a
bearer token. Put the key in `DRIFTLINE_KEY` (see `docs/mcp.md` to create one), then run:

```bash
claude mcp add --transport http driftline http://localhost:8010/mcp --header "Authorization: Bearer $DRIFTLINE_KEY"
```

The shell expands `$DRIFTLINE_KEY` when the command runs, so the key itself is stored in
your Claude Code config. Add `--scope project` to write `.mcp.json` for the whole team
instead (then use `"Authorization": "Bearer ${DRIFTLINE_KEY}"` in its `headers`, so each
person's own key is read from their environment). Check the connection with
`claude mcp list` or `/mcp`. A `401` means the key is wrong. A `421` means the gateway
doesn't accept the host name in the URL (see `DRIFTLINE_MCP_ALLOWED_HOSTS` in `docs/mcp.md`).

## Picking a tool

| The user wants | Call |
|---|---|
| What the sources say, now or at a time | `ask(question=..., as_of=...)` |
| To know which corpora exist | `list_sources()` |
| A document's versions and their validity windows | `get_timeline(document_id=...)` |
| What changed between two versions | `diff_versions(document_id=..., from_version=..., to_version=...)` |
| To be alerted when an answer stops being true | `watch_answer(answer_id=...)` |

Get `document_id` from a citation of an `ask` result. Version numbers for
`diff_versions` are the `version_no` values from `get_timeline`.

## Always pass `as_of` for historical questions

Without `as_of`, Driftline answers **as of now**: it reads only the current versions. If
the question names a date, a year, a release or "back then", pass it as `as_of`. Don't
rely on the wording of the question alone. `as_of` accepts:

- an ISO date or timestamp: `"2024-03-01"`, `"2024-03-01T12:00:00Z"`;
- a year: `"2023"` (start of the year);
- a month: `"June 2023"`;
- a release: `"v1.28"` (the date that version came into force).

Examples:

```text
User: How often did the label say to check ALT in 2023?
ask(question="How often should ALT be checked?", as_of="2023")

User: Which admission controllers were enabled by default in Kubernetes 1.25?
ask(question="Which admission controllers are enabled by default?", as_of="v1.25", source_kinds=["git_docs"])

User: What were the storage instructions on 1 March 2024?
ask(question="What are the storage instructions?", as_of="2024-03-01")

User: What's the current boxed warning?
ask(question="What is the boxed warning?")
```

To compare two points in time, call `ask` twice with different `as_of` values, then use
`diff_versions` to show the exact text that changed.

`source_kinds` narrows the search to `openfda`, `git_docs` or `upload`. `timeout_s`
(default 60, max 300) is how long the call waits for the answer.

## Reading an `ask` result

`status` is one of these:

- **`answered`**: `answer` is the text, and `citations` lists the evidence. Each citation
  has `quote` (exact text from the source), `title`, `external_id`, `section_path`,
  `version_no`, and the version's validity window `valid_from` / `valid_to`. A null
  `valid_to` means that version is still in force. `as_of` echoes the time the answer is
  for. Quote the evidence and name its version and window, for example:
  *"Liver safety, v1, in force 2023-01-01 to 2025-01-01: 'Check ALT every 12 weeks.'"*
  `confidence` is between 0 and 1. `degraded: true` means a fallback model answered.
  `dropped_claims` are claims the verifier could not support. Don't repeat them as fact.
- **`insufficient_evidence`**: the in-force versions don't support an answer. Say so.
  Don't fill the gap from memory. `nearest_sources` lists the closest versions found
  (with their windows), which often shows that the user meant another date: offer to
  ask again with a different `as_of`.
- **`refused`**: the question is out of scope or unsafe to answer from the sources.
  Report that.
- **`"running"`** (the result is just `{status: "running", job_id}`): the answer took
  longer than `timeout_s`. The job keeps running on the server, and its result can be
  read over REST at `GET /v1/jobs/{job_id}` with the same bearer key. Otherwise call
  `ask` again with a larger `timeout_s` (this starts a new job). Tell the user it is
  still running. Don't report it as a failure.

A tool error that mentions `as_of` means the value wasn't a date, year, month or known
release. Fix the value and retry. "Driftline is busy; retry in N s" is backpressure:
wait that long, then retry.

## Following up

- **What changed?** Call `get_timeline(document_id=...)` for the versions, each with
  `version_no`, `version_key` (such as `release-1.28`), and `valid_from` / `valid_to`.
  Then call `diff_versions(document_id=..., from_version=1, to_version=2)`. The default
  is the previous version against the latest. The result gives each section's status
  (added, removed, changed, unchanged) and a unified diff, capped at 16 KB. When
  `truncated` is true, say the diff was cut.
- **Does the citation still hold?** If the cited version's `valid_to` is set, the text
  has since been replaced. Call `ask` again without `as_of` to get the current answer,
  and `diff_versions` to show the change.
- **Keep watching.** When the user relies on an answer, offer
  `watch_answer(answer_id=...)` with the `answer_id` from `ask`. Driftline re-checks its
  claims whenever a cited document changes, and raises a drift alert when one no longer
  holds.
- `relations` in the timeline shows links such as `supersedes` between documents. Follow
  them with `get_timeline` on the related `document_id`.
