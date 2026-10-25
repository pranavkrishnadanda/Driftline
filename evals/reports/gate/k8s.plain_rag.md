# Eval: k8s / plain_rag

Commit `ce44d2b91109426c9ab416d7b58816da61b44d92`. LLM: offline extractive LLM (DeterministicAdapter + ExtractiveResponder; extract=deterministic/offline-extract; answer=deterministic/offline-answer; judge=deterministic/offline-judge). 0 stale case(s) excluded.

| Metric | Value |
|---|---|
| cases | 40 |
| citation_precision | 0.2653 |
| citations | 98 |
| claims | 98 |
| claims_judged | 0 |
| cost_per_answer_usd | 0.000000 |
| error_count | 0 |
| faithfulness | 0.2653 |
| insufficient_evidence_accuracy | 1.0000 |
| latency_p95_ms | 107.2 |
| outdated_citation_rate | 0.7347 |
| scored | 40 |
| stale_case_count | 0 |
| trap_citation_precision | 0.3889 |
| trap_outdated_citation_rate | 0.6111 |

| Case | Status | Answer status | Precision | Outdated | Faithfulness | Note |
|---|---|---|---|---|---|---|
| k8s-003 | scored | answered | 0.33 | 0.67 | 0.33 |  |
| k8s-004 | scored | answered | 0.33 | 0.67 | 0.33 |  |
| k8s-005 | scored | answered | 0.67 | 0.33 | 0.67 |  |
| k8s-013 | scored | answered | 0.00 | 1.00 | 0.00 |  |
| k8s-014 | scored | answered | 0.00 | 1.00 | 0.00 |  |
| k8s-016 | scored | answered | 1.00 | 0.00 | 1.00 |  |
| k8s-018 | scored | answered | 0.50 | 0.50 | 0.50 |  |
| k8s-023 | scored | answered | 0.67 | 0.33 | 0.67 |  |
| k8s-031 | scored | answered | 0.00 | 1.00 | 0.00 |  |
| k8s-034 | scored | answered | 0.00 | 1.00 | 0.00 |  |
| k8s-036 | scored | answered | 0.33 | 0.67 | 0.33 |  |
| k8s-037 | scored | answered | 0.00 | 1.00 | 0.00 |  |
| k8s-039 | scored | answered | 1.00 | 0.00 | 1.00 |  |
| k8s-049 | scored | answered | 0.50 | 0.50 | 0.50 |  |
| k8s-050 | scored | answered | 0.00 | 1.00 | 0.00 |  |
| k8s-055 | scored | answered | 0.50 | 0.50 | 0.50 |  |
| k8s-059 | scored | answered | 0.33 | 0.67 | 0.33 |  |
| k8s-064 | scored | answered | 0.00 | 1.00 | 0.00 |  |
| k8s-066 | scored | answered | 0.00 | 1.00 | 0.00 |  |
| k8s-070 | scored | answered | 0.00 | 1.00 | 0.00 |  |
| k8s-071 | scored | answered | 0.00 | 1.00 | 0.00 |  |
| k8s-073 | scored | answered | 0.00 | 1.00 | 0.00 |  |
| k8s-076 | scored | answered | 0.00 | 1.00 | 0.00 |  |
| k8s-077 | scored | answered | 0.00 | 1.00 | 0.00 |  |
| k8s-080 | scored | answered | 0.50 | 0.50 | 0.50 |  |
| k8s-081 | scored | answered | 0.00 | 1.00 | 0.00 |  |
| k8s-082 | scored | answered | 0.33 | 0.67 | 0.33 |  |
| k8s-083 | scored | answered | 0.50 | 0.50 | 0.50 |  |
| k8s-085 | scored | answered | 0.00 | 1.00 | 0.00 |  |
| k8s-094 | scored | answered | 0.50 | 0.50 | 0.50 |  |
| k8s-096 | scored | answered | 0.33 | 0.67 | 0.33 |  |
| k8s-101 | scored | answered | 0.00 | 1.00 | 0.00 |  |
| k8s-107 | scored | answered | 0.50 | 0.50 | 0.50 |  |
| k8s-109 | scored | answered | 0.50 | 0.50 | 0.50 |  |
| k8s-113 | scored | answered | 0.50 | 0.50 | 0.50 |  |
| k8s-129 | scored | answered | 0.00 | 1.00 | 0.00 |  |
| k8s-133 | scored | answered | 0.00 | 1.00 | 0.00 |  |
| k8s-137 | scored | answered | 0.33 | 0.67 | 0.33 |  |
| k8s-139 | scored | answered | 0.00 | 1.00 | 0.00 |  |
| k8s-144 | scored | answered | 0.00 | 1.00 | 0.00 |  |
