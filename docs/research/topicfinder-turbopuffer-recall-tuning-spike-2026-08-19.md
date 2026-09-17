# TopicFinder Turbopuffer Recall Tuning Spike

Date: 2026-08-19

Purpose: find the minimum Turbopuffer query/index mode that reaches Neon-control recall parity on the completed 200-query eval while preserving Turbopuffer's latency win.

## Context

- Completed side-by-side result:
  - Turbopuffer default ANN `recall@1000 mean = 0.782`
  - Neon pgvector HNSW control `recall@1000 mean = 0.895`
  - Exact denominator: local f32 cosine brute force over the same 82,178 servable chunks
  - Turbopuffer query used default public ANN: `ns.query(rank_by=("vector", "ANN", emb), top_k=1000)`
  - Turbopuffer built-in recall estimate: `0.92`
  - Turbopuffer server latency: about `13ms` warm, `22ms` to `32ms` cold
  - Neon latency from side-by-side: cold `726ms` to `5600ms`, warm about `105ms`
- Corpus:
  - 82,178 servable chunks
  - `[1024]f16`, cosine, `gcp-us-central1`
  - one servable-only namespace
- Cost is already decided in Turbopuffer's favor. This pass only adjudicates recall and latency.

## Public API Finding

As of 2026-08-19, the documented Turbopuffer query API and generated Python SDK expose these query fields relevant to this spike:

- `rank_by`: supports `ANN` approximate vector search and `kNN` exact vector search
- `top_k` / `limit`: return count, max 10,000
- `consistency`: `{"level": "strong"}` or `{"level": "eventual"}`
- `distance_metric`: vector similarity function
- `include_attributes` / `exclude_attributes`
- `filters`
- `multi_query` and `rerank_by=("RRF",)` for hybrid/multi-query use

The public docs and typed SDK do not expose a query-time ANN effort knob such as `ef_search`, `probes`, `search_multiple`, `exhaustiveness`, or `recall`.

Therefore:

- Do not treat `top_k`, `limit`, `consistency`, or `include_attributes` as recall-effort knobs.
- Do not claim an undocumented knob works unless the API accepts it and either `explain_query`, response metadata, or measured recall/latency changes consistently.
- `consistency` can affect visibility of unindexed writes. It should not affect recall once namespace metadata shows indexing complete.
- `kNN` exact search is the public recall ceiling/debug mode, not ANN tuning.

## Required Inputs

Reuse artifacts from the completed side-by-side run:

```bash
export ART=artifacts/vector-recall-spike
export QUERIES_JSONL="$ART/queries.jsonl"
export GROUND_TRUTH_JSONL="$ART/ground_truth.jsonl"
export NEON_CONTROL_SUMMARY="$ART/summary.json"
export TURBOPUFFER_REGION=gcp-us-central1
export TURBOPUFFER_NAMESPACE=<existing or reingested servable namespace>
export TURBOPUFFER_API_KEY=<operator-provided>
```

Required Neon control numbers:

```bash
export NEON_RECALL1000_MEAN=0.895
export NEON_COLD_P95_MS=5600
export NEON_WARM_P95_MS=105
```

If the prior run has exact per-query Neon recall, load it and use it for per-query deltas. The primary gate is still Turbopuffer mean `recall@1000 >= 0.895`.

## Reingest Requirements

Because exact `kNN` in Turbopuffer requires a filter, reingest or patch the test namespace so every row has a filterable all-docs boolean.

Schema for the tuning namespace:

```python
schema = {
    "vector": {"type": "[1024]f16", "ann": {"distance_metric": "cosine_distance"}},
    "video_id": {"type": "string", "filterable": False},
    "chunk_id": {"type": "string", "filterable": False},
    "all_docs": {"type": "bool", "filterable": True},
    "model": {"type": "string", "filterable": False},
}
```

Every upserted row must include:

```python
"all_docs": True
```

When writing, also pass `distance_metric="cosine_distance"` if the executor's SDK/write helper uses the root write parameter. After ingest, call `ns.schema()` or `ns.metadata()` and record the actual schema. Stop if the vector column is not `[1024]f16` with cosine ANN.

After ingest, poll metadata until there are no unindexed writes. Record metadata in `tpuf_tuning_metadata.json`.

Optional precision namespace:

- Create a second namespace with identical ids and attributes but `vector` type `[1024]f32`.
- Use it only to detect f16 precision ceiling. Do not make it the default deployment choice without a cost/storage decision.

## Query Modes To Test

The sweep has three classes: public baseline modes, exact ceiling modes, and vendor/private effort modes.

### Public Baseline Modes

Run these first.

```json
[
  {
    "mode": "ann_default_strong",
    "rank_by": ["vector", "ANN", "$QUERY_VECTOR"],
    "consistency": {"level": "strong"},
    "limit": 1000
  },
  {
    "mode": "ann_default_eventual",
    "rank_by": ["vector", "ANN", "$QUERY_VECTOR"],
    "consistency": {"level": "eventual"},
    "limit": 1000
  },
  {
    "mode": "ann_default_strong_k2000",
    "rank_by": ["vector", "ANN", "$QUERY_VECTOR"],
    "consistency": {"level": "strong"},
    "limit": 2000
  }
]
```

Expected:

- `ann_default_strong` should reproduce the completed run within noise.
- `ann_default_eventual` should have the same recall after indexing completes. If it differs materially, stop and inspect indexing/freshness.
- `ann_default_strong_k2000` is for `recall@2000` and tail diagnostics. Its first 1000 rows should match or nearly match `ann_default_strong`.

### Exact Ceiling Modes

Run exact `kNN` if the API accepts it with the all-docs filter.

```python
response = ns.query(
    rank_by=("vector", "kNN", query_embedding),
    filters=("all_docs", "Eq", True),
    limit=1000,
    include_attributes=["video_id", "chunk_id"],
    consistency={"level": "strong"},
)
```

Also run `limit=2000`.

Mode names:

- `knn_exact_f16_k1000`
- `knn_exact_f16_k2000`
- optional `knn_exact_f32_k1000`
- optional `knn_exact_f32_k2000`

Interpretation:

- If `knn_exact_f16_k1000 recall < 0.895`, f16 precision or exact-denominator mismatch may be the ceiling. Run the f16 local ceiling check and optional f32 namespace before blaming ANN.
- If `knn_exact_f16_k1000 recall >= 0.895` but ANN plateaus below 0.895, the problem is ANN search effort/index quality, not f16 precision.
- If exact `kNN` is fast enough today, it is still not proof for the 1M-in-weeks corpus. Treat it as ceiling/debug unless the operator explicitly approves exact search as a short-term bridge.

### Vendor/Private Effort Modes

There is no documented public ANN effort parameter in the Python SDK type surface. If Turbopuffer support provides an exact parameter name, use it through `extra_body` and record the support answer in `tpuf_tuning_manifest.json`.

Do not invent names for the verdict.

The executor may run a discovery probe only to detect whether a supplied or suspected parameter is rejected or silently ignored.

For each candidate private parameter, run 5 probe queries and compare response shape, `explain_query`, recall, and latency:

```python
response = ns.query(
    rank_by=("vector", "ANN", qvec),
    limit=1000,
    include_attributes=["video_id", "chunk_id"],
    consistency={"level": "strong"},
    extra_body={PARAM_NAME: PARAM_VALUE},
)
```

Only include a parameter in the real sweep when at least one is true:

- Turbopuffer support confirms the parameter and valid values.
- The API rejects invalid values and accepts valid values.
- `ns.explain_query(..., extra_body={...})` changes plan/knob output.
- Recall and latency move monotonically across at least 3 increasing values.

If a parameter is confirmed, sweep by shape:

Numeric multiplicative effort:

```json
[1, 2, 4, 8, 16, 32]
```

Numeric bounded effort:

```json
[0, 1, 2, 3, 4, 5]
```

Enum effort:

```json
["default", "high", "higher", "max"]
```

For each value, run both `limit=1000` and `limit=2000`.

Mode names:

```text
ann_effort_<param>_<value>_k1000
ann_effort_<param>_<value>_k2000
```

## Precision Ceiling Checks

Run these local checks before final adjudication.

### Local f16 Exact Ceiling

Using the same f32 corpus/query vectors from ground truth:

```python
corpus_f16 = corpus_f32.astype("float16").astype("float32")
queries_doc_f16_query_f32 = queries_f32
queries_doc_f16_query_f16 = queries_f32.astype("float16").astype("float32")
```

Normalize after quantization and compute exact cosine top1000/top2000 for both query variants. Compare local f16 exact to local f32 exact:

```json
{
  "mode": "local_exact_doc_f16_query_f32_vs_exact_f32",
  "mean_recall_at_1000": 0.0,
  "p05_recall_at_1000": 0.0,
  "mean_recall_at_2000": 0.0
}
{
  "mode": "local_exact_doc_f16_query_f16_vs_exact_f32",
  "mean_recall_at_1000": 0.0,
  "p05_recall_at_1000": 0.0,
  "mean_recall_at_2000": 0.0
}
```

If both local f16 exact variants have `recall@1000 mean < 0.895`, f16 precision alone can explain failure against f32 ground truth.

### Turbopuffer kNN Ceiling

Compare `knn_exact_f16_k1000` against local f16 exact and local f32 exact. If TPuf kNN differs materially from local f16 exact, investigate vector encoding, normalization, distance metric, id alignment, and schema before running ANN sweeps.

## Measurement Protocol

For every mode and K in `{1000, 2000}`:

1. Use the same 200 query embeddings as the completed side-by-side.
2. Run one warm-up query not included in latency stats unless the phase is `cold`.
3. Run all 200 queries serially with one reused Turbopuffer client.
4. Capture:
   - returned ids in order
   - `performance.server_total_ms`
   - `performance.query_execution_ms`
   - `performance.cache_hit_ratio`
   - `performance.cache_temperature`
   - client wall time
   - result count
   - billing logical bytes if present
5. Repeat the full 200-query run twice for the passing candidate mode and for default ANN to check stability.

Write `tpuf_tuning_results.jsonl`:

```json
{
  "mode": "ann_default_strong",
  "query_id": "q_001",
  "k": 1000,
  "ids": ["..."],
  "server_total_ms": 13,
  "query_execution_ms": 12,
  "client_ms": 21.4,
  "cache_temperature": "warm",
  "result_count": 1000
}
```

Compute recall against the existing f32 exact ground truth:

```python
recall_at_k = len(set(tpuf_ids[:k]) & set(exact_ids[:k])) / k
```

Write `tpuf_tuning_summary.json` with aggregate:

```json
{
  "mode": "ann_effort_x_4_k1000",
  "k": 1000,
  "mean_recall": 0.0,
  "median_recall": 0.0,
  "p05_recall": 0.0,
  "min_recall": 0.0,
  "server_p50_ms": 0.0,
  "server_p95_ms": 0.0,
  "client_p50_ms": 0.0,
  "client_p95_ms": 0.0,
  "queries_below_neon_per_query": 0,
  "worst_query_id": "...",
  "worst_query_text": "..."
}
```

## Cold And Warm Latency

Warm:

- Call `ns.hint_cache_warm()`.
- Wait 60 seconds.
- Run the 200-query sweep for the candidate modes.

Cold:

- Preferred: after reingest completes, wait 10 minutes with no queries, then run the first 50 queries.
- Also run after 1 hour idle if schedule allows.
- If using a fresh copied/branched namespace for cold, record namespace name and creation method.

Report server-side p50/p95 and client-side p50/p95 separately. The pass bar uses server-side latency for Turbopuffer-vs-Neon headroom, with client-side noted for user experience.

## Output Table

The final report must include:

| mode | k | accepted_param | mean_recall | median_recall | p05_recall | min_recall | server_p50_ms | server_p95_ms | client_p50_ms | client_p95_ms | passes_neon_mean | notes |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| ann_default_strong | 1000 | public |  |  |  |  |  |  |  |  |  |  |
| ann_default_eventual | 1000 | public |  |  |  |  |  |  |  |  |  |  |
| ann_default_strong_k2000 | 2000 | public |  |  |  |  |  |  |  |  |  |  |
| knn_exact_f16_k1000 | 1000 | public |  |  |  |  |  |  |  |  |  | ceiling |
| knn_exact_f16_k2000 | 2000 | public |  |  |  |  |  |  |  |  |  | ceiling |
| ann_effort_<param>_<value>_k1000 | 1000 | support-confirmed |  |  |  |  |  |  |  |  |  |  |

Also include a compact pass-bar table:

| gate | value | pass |
| --- | ---: | --- |
| minimum passing mode |  |  |
| Turbopuffer mean recall@1000 |  |  |
| Neon control mean recall@1000 | 0.895 |  |
| Turbopuffer warm server p95 ms |  |  |
| Neon warm p95 ms | 105 |  |
| Turbopuffer cold server p95 ms |  |  |
| Neon cold p95 ms | 5600 |  |
| local f16 doc/query-f32 exact ceiling mean recall@1000 |  |  |
| local f16 doc/query-f16 exact ceiling mean recall@1000 |  |  |
| TPuf kNN exact f16 mean recall@1000 |  |  |

## Pass Bar

Turbopuffer passes this tuning spike if there is a deployable mode where:

1. `mean_recall@1000 >= 0.895` against the same f32 exact ground truth.
2. The mode is either public API or support-confirmed private API. No invented or silently ignored parameter qualifies.
3. Server warm p95 remains below Neon warm p95 `105ms`.
4. Server cold p95 remains below Neon cold p95 `5600ms`, and preferably below the product target `2000ms`.
5. Result count is exactly K for every query unless exact ground truth has fewer than K docs, which it does not here.

Pick the minimum effort that passes. If multiple modes tie on recall, choose the lower server p95.

## Verdict Criteria

Commit to Turbopuffer when:

- A public or support-confirmed ANN effort mode reaches `mean_recall@1000 >= 0.895`.
- That mode keeps Turbopuffer far faster than Neon on cold and warm latency.
- f16 ceiling checks show no hidden precision trap.

Escalate to Turbopuffer or fall back when:

- No documented/support-confirmed effort knob exists and default ANN remains below Neon.
- Exact `kNN` reaches Neon parity but ANN cannot. This means the namespace data and f16 precision are adequate, but ANN effort/index quality is insufficient.
- Exact `kNN` does not reach Neon parity and local f16 exact also falls below Neon. This means f16-vs-f32 precision may cap the metric; test `[1024]f32` before rejecting the vendor.
- Exact `kNN` reaches parity and is fast on 82k, but no ANN effort mode is available. This can be a short-term bridge only with operator approval, not proof for the 1M-in-weeks corpus.

## Sources

- Turbopuffer query API: https://turbopuffer.com/docs/query
- Turbopuffer performance guidance: https://turbopuffer.com/docs/performance
- Turbopuffer recall endpoint: https://turbopuffer.com/docs/recall
- Turbopuffer Python SDK query params: https://github.com/turbopuffer/turbopuffer-python/blob/main/src/turbopuffer/types/namespace_query_params.py
- Turbopuffer Python SDK namespace resource: https://github.com/turbopuffer/turbopuffer-python/blob/main/src/turbopuffer/resources/namespaces.py
