# Golden sets

`pharma.jsonl` and `k8s.jsonl` hold 150 golden cases each (`driftline.eval.types.GoldenCase`,
one JSON object per line). Every case was drafted from the real ingested corpora and then
passed `driftline.eval.curate.validate_case` against the database it came from. Cases that
failed validation were dropped. No case was written or edited by hand, and none was added
to make up a count.

| corpus | cases | traps | `point_in_time` | `current` | distinct expected versions |
|---|---|---|---|---|---|
| pharma | 150 | 50 | 126 | 24 | 64 |
| k8s | 150 | 47 | 136 | 14 | 38 |

The k8s set has 47 traps instead of 50 (31%): only 48 trap drafts validated, and one
duplicated another case's question.

## How a case is made

Command: `python -m driftline.eval curate --corpus <pharma|k8s> --n 150 --out ... --stats ... --manifest ...`

1. **Candidates.** Only documents with at least 3 versions are used. Versions are diffed by
   `doc_versions.section_hashes`.
   - **Trap candidate:** a section that changed between two consecutive versions, where the
     older text has at least one sentence the newer text no longer contains.
   - **Stable candidate:** a section that is identical in every version of its document.
2. **Drafting.** `claude-haiku-5-5` (extract tier, structured output) receives the items in
   batches of 8. It sees only the section text and an item number, never ids. For each item
   it writes a question, an answer, a verbatim quote, and (for traps) what the newer version
   would answer instead. It marks items unusable when nothing checkable changed or nothing
   is worth asking.
3. **Tying.** The code, not the model, sets `expected_version_ids` to the candidate's real
   version id: the older version for a trap, the version seen for a stable case.
   - `as_of` is the middle whole UTC day of that version's window. An open window ends on
     the curation date.
   - The quote is replaced by the chunk's own words (`locate_quote`).
4. **Validation** (`validate_case`). Every check must pass:
   - each expected version exists and belongs to the case's corpus;
   - the whole `as_of` day lies inside each version's `[valid_from, valid_to)` window;
   - each quote is in a chunk of an expected version, exactly or near-exactly
     (`quote_supported`, ratio ≥ 0.9);
   - for a trap, a next version exists and the quote is no longer in it (match ratio
     < 0.97);
   - the question has no date or release of its own, because that would override `as_of`
     (`extract_as_of_hint`).
5. **Selection.** Of the validated cases, at most `round(n/3)` traps are kept, then
   non-traps fill the set up to `n`. Exact duplicate questions are dropped.

**Kinds.** Traps are `point_in_time`. A stable case is `current` when its version is the
open (latest) one, and `point_in_time` otherwise.

## Version ids and re-ingest

`expected_version_ids` are the database-generated UUIDs of the curation database
described below. `<corpus>.versions.jsonl` lists every expected version with:
- source kind;
- external id;
- `version_key` and `version_no`;
- window;
- `content_hash`.

`content_hash` is deterministic from the content, so after a re-ingest of the same sources,
the cases can be mapped to the new ids exactly. A case whose version cannot be found must be
scored `stale_case`, never as a model failure.

## Sources (ingested 2026-10-25)

Ingested with the real connectors (`python -m driftline.ingest enqueue` and `worker --drain`,
plus the relay) into a dedicated, throwaway Postgres + Redis + TEI stack. Supersession
extraction was off (no LLM key in the ingest environment), so ingestion cost nothing.

### pharma (openFDA discovery, DailyMed SPL version archives)

The first 5 set_ids are the pinned labels from `deploy/drift-watch/sources.json`. The other
12 were found with an openFDA search (`openfda.product_type:"HUMAN PRESCRIPTION DRUG" AND
_exists_:boxed_warning AND _exists_:openfda.brand_name`). Each one's DailyMed history was
checked before it was ingested. "Versions ingested" counts the archived SPL versions that
DailyMed served.

| set_id | label | versions ingested (spl_version) |
|---|---|---|
| a60cc18b-0631-4cf0-b021-9f52224ece65 | Lipitor (atorvastatin calcium), Viatris | 3 (1, 5, 7) |
| fda754f6-d0f3-4dce-a17a-927d64f912f7 | Zoloft (sertraline), Viatris | 2 (1, 2): fewer than 3, so not used |
| de8b0b67-eb25-4684-83b5-7ad785314227 | Plavix (clopidogrel), Sanofi-Aventis | 4 |
| 19a69a72-ac5d-45d5-a94d-a5aaecbe4730 | Jantoven (warfarin), Upsher-Smith | 10 |
| 8a99d6d6-fd9e-45bb-b1bf-48c7f761232a | Paxlovid (nirmatrelvir; ritonavir), Pfizer | 8 |
| 000dc81d-ab91-450c-8eae-8eb74e72296f | Entresto (sacubitril and valsartan), Novartis | 10 |
| 00634b2b-4e48-4178-8877-28582af894ad | Doxorubicin HCl injection, Pfizer | 12 |
| 00b5e716-5564-4bbd-acaf-df2bc45a5663 | Azstarys (serdexmethylphenidate and dexmethylphenidate) | 6 |
| 00c424b5-6ccd-48ab-9e88-1986451120e2 | Elahere (mirvetuximab soravtansine), ImmunoGen | 7 |
| 00d3e846-dd92-448d-9ab8-6a07be823cc1 | Gablofen (baclofen injection), Piramal | 13 |
| 01a910ee-a33e-4be3-ac41-322d64c34311 | Xenpozyme (olipudase alfa-rpcp), Genzyme | 6 |
| 02438044-d6a3-49e9-a1ac-3aad21ef2c8c | Tikosyn (dofetilide), Pfizer | 16 |
| 028312dc-d155-4fd5-8abd-6bb9f011d3cc | Odomzo (sonidegib), Sun Pharma | 7 |
| 02c91fba-9c47-43ef-ac78-e82369798834 | Natazia (estradiol valerate; dienogest), Bayer | 10 |
| 053b9158-2a5b-48b9-bf47-5fa78a35ec33 | Cinqair (reslizumab), Teva | 7 |
| 0553e26c-f2aa-43aa-adf9-6eb951a501d3 | Zolpidem tartrate, Sandoz | 13 |
| 065f33e4-b587-4e66-b896-ca9ab7b7c876 | Yaz (drospirenone and ethinyl estradiol), Bayer | 14 |

### k8s (`kubernetes/website`, one version per release branch)

The branches are every second release from 1.22 to 1.36: release-1.22, 1.24, 1.26, 1.28,
1.30, 1.32, 1.34 and 1.36. `valid_from` is the publish date of the matching
`kubernetes/kubernetes` `v1.N.0` release.

No GitHub token is configured for the project, so the connector ran unauthenticated, with
60 GitHub API requests an hour. That limit set the scope: 8 branches × 6 paths, ingested in
two rate-limit windows. Branches 1.20 to 1.36 at every release would have needed about
3× the requests.

A branch whose file content equals the previous version adds no version.

| path | versions |
|---|---|
| content/en/docs/concepts/storage/volumes.md | 8 |
| content/en/docs/concepts/security/pod-security-standards.md | 8 |
| content/en/docs/concepts/workloads/pods/pod-lifecycle.md | 8 |
| content/en/docs/concepts/workloads/controllers/deployment.md | 7 (1.30 unchanged) |
| content/en/docs/concepts/services-networking/ingress.md | 7 (1.36 unchanged) |
| content/en/docs/reference/using-api/deprecation-guide.md | 6 (1.32, 1.36 unchanged) |

## Counts

From `pharma.stats.json` and `k8s.stats.json`, written by the final run of each corpus.

| | pharma | k8s |
|---|---|---|
| candidates sent to the model | 550 (400 trap, 150 stable) | 388 (188 trap, 200 stable) |
| LLM calls (batches of 8) | 69 | 49 |
| drafts returned | 550 | 388 |
| declined by the model as unusable | 276 | 124 |
| dropped before validation: trap answer equal to `answer_after` | 0 | 1 |
| **proposed** (became a `GoldenCase`) | 274 | 263 |
| rejected by validation: `trap_not_changed` (the quote is still in the next version) | 65 | 22 |
| rejected by validation: `quote_not_found` | 2 | 1 |
| **validated** | 208 (58 traps) | 240 (48 traps) |
| **kept** (trap cap, dedupe, n = 150) | 150 (50 traps) | 150 (47 traps) |

Validated cases that were not kept are surplus non-traps over the cap, and for k8s one trap
with a duplicate question. They were discarded, not edited.

## Model and cost

- **Model:** `claude-haiku-5-5` (Anthropic, extract tier), structured output, batched
  prompts.
- **Actual API cost: $0.407955 in total.** This is the sum of `llm_calls.cost_usd` in the
  curation database: 197 calls, 882,986 input and 639,321 output tokens, priced with
  `driftline.obs.cost.PRICES`. It covers every curation run, including two earlier pharma
  runs that were discarded:
  - pharma, run 1: 29 calls, $0.059873. Only 16 traps validated.
  - pharma, run 2: 50 calls, $0.097822. Run after the trap prompt was tightened to require
    a factual change, not a rewording; 36 traps validated.
  - pharma, final run: 69 calls, $0.134519.
  - k8s, final run: 49 calls, $0.115741.
- Recording the proposer cassette (`backend/tests/eval/cassettes/`) took 4 more Haiku calls
  in throwaway test databases, so they are not in `llm_calls`. The kept recording cost
  $0.000857, so the 4 calls add roughly $0.004.
- The budget guard (`--budget-usd 5`) never triggered.

## Known limits

- The model drafted the cases and the checks above are mechanical. No person has reviewed
  them.
- Validation proves each case is grounded: the version is real, the quote is in it,
  `as_of` is in its window, and a trap's quote is gone from the next version. It does not
  prove that every trap question is a good one. Some pharma traps hinge on editorial label
  changes, and some k8s quotes are Markdown fragments.
- The curation database had every chunk embedded with TEI `BAAI/bge-base-en-v1.5`, but the
  database itself is not committed. Running the evals needs the same sources ingested, plus
  the version manifests above.
