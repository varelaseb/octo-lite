# TopicFinder Turbopuffer vs Neon Control Recall Spike

Date: 2026-08-19

Purpose: settle the only open Turbopuffer decision question before commit: does Turbopuffer match or beat the current shipped Neon pgvector HNSW control on servable-only `recall@1000`, reranker-pass survival, and latency?

## Hard Constraints

- Never touch the Neon parent branch `br-sweet-glitter-ai6zev0l` or parent endpoint `ep-sparkling-dew`.
- Create one throwaway Neon child branch from `br-sweet-glitter-ai6zev0l` and run all pgvector reads there.
- Index only the servable corpus on both sides. There is no runtime `servable` filter in the recall test.
- Corpus source is the prior Exp-1 table `spike_searchable_transcript_chunks`: about 39,567 videos, 82,178 chunks, `voyage-context-4/ctx512-o0-d1024-v1`, `halfvec(1024)`.
- Neon HNSW at `ef_search=400` is the control. Exact brute-force cosine is only the denominator used to compute each system's recall number.
- Primary verdict is relative to Neon on the same queries. Turbopuffer must not regress from the Neon control.
- Do not adjudicate from Turbopuffer's built-in recall endpoint alone. Use it only as a vendor-side sanity check.

## Runner Requirements

Run from the closest practical GCP `us-central1` environment.

Preferred runner:

```bash
gcloud run jobs create tf-vector-recall-spike \
  --project turbo-video-489407 \
  --region us-central1 \
  --image <repo image with python, psql, gcloud, jq> \
  --tasks 1 \
  --max-retries 0
```

If the runner is not in `us-central1`, record `runner_region`, `runner_provider`, and baseline network timings. Estimate co-located latency as `measured_query_ms - measured_control_ms`, but mark all estimated latency rows as `estimated=true`.

Required local tools: `python>=3.11`, `psql`, `jq`, `curl`, `gcloud`.

Required Python packages: `psycopg[binary]`, `pgvector`, `numpy`, `pyarrow`, `pandas`, `tqdm`, `turbopuffer`, `voyageai`, `httpx`.

## Secrets

```bash
export GCP_PROJECT=turbo-video-489407
export NEON_PARENT_BRANCH_ID=br-sweet-glitter-ai6zev0l
export NEON_PARENT_ENDPOINT_ID=ep-sparkling-dew
export NEON_API_KEY="$(gcloud secrets versions access latest --project "$GCP_PROJECT" --secret NEON_API_KEY)"

# Operator provides one of these.
export TURBOPUFFER_API_KEY="$(gcloud secrets versions access latest --project "$GCP_PROJECT" --secret TURBOPUFFER_API_KEY 2>/dev/null || true)"
test -n "$TURBOPUFFER_API_KEY" || export TURBOPUFFER_API_KEY="$(sudo cat /root/turbopuffer_api_key)"

# Use the same Voyage credential path the app uses. If unavailable, fetch from Secret Manager.
export VOYAGE_API_KEY="${VOYAGE_API_KEY:-$(gcloud secrets versions access latest --project "$GCP_PROJECT" --secret VOYAGE_API_KEY 2>/dev/null || true)}"
```

Stop if any required secret is empty.

## Neon Branch Setup

Discover the Neon project id. Do not assume the GCP project id is the Neon project id.

```bash
mkdir -p artifacts/vector-recall-spike
curl -fsS -H "Authorization: Bearer $NEON_API_KEY" \
  "https://console.neon.tech/api/v2/projects" \
  > artifacts/vector-recall-spike/neon-projects.json

python3 - <<'PY'
import json
import os
import pathlib
import urllib.parse
import urllib.request

api_key = os.environ["NEON_API_KEY"]
parent_branch_id = os.environ["NEON_PARENT_BRANCH_ID"]
base = "https://console.neon.tech/api/v2"
out = pathlib.Path("artifacts/vector-recall-spike/neon-parent.json")

def get_json(url):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {api_key}"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)

projects = []
cursor = None
while True:
    params = {"limit": "100"}
    if cursor:
        params["cursor"] = cursor
    data = get_json(f"{base}/projects?{urllib.parse.urlencode(params)}")
    projects.extend(data.get("projects", []))
    pagination = data.get("pagination") or {}
    cursor = pagination.get("cursor") or data.get("next_cursor")
    if not cursor:
        break

matches = []
for project in projects:
    project_id = project["id"]
    branches = get_json(f"{base}/projects/{project_id}/branches").get("branches", [])
    for branch in branches:
        if branch.get("id") == parent_branch_id:
            matches.append({"project_id": project_id, "branch": branch})

if len(matches) != 1:
    raise SystemExit(f"expected exactly one project for {parent_branch_id}, got {len(matches)}")

out.write_text(json.dumps(matches[0], indent=2) + "\n")
PY
export NEON_PROJECT_ID="$(jq -r .project_id artifacts/vector-recall-spike/neon-parent.json)"
test -n "$NEON_PROJECT_ID"
```

The discovery step must return exactly one project containing `br-sweet-glitter-ai6zev0l`; otherwise stop.

Create the throwaway child branch with a read-write endpoint:

```bash
export SPIKE_ID="tf-vector-recall-$(date -u +%Y%m%dT%H%M%SZ)"
curl -fsS -X POST \
  -H "Authorization: Bearer $NEON_API_KEY" \
  -H "Content-Type: application/json" \
  "https://console.neon.tech/api/v2/projects/${NEON_PROJECT_ID}/branches" \
  -d "{\"endpoints\":[{\"type\":\"read_write\"}],\"branch\":{\"parent_id\":\"${NEON_PARENT_BRANCH_ID}\",\"name\":\"${SPIKE_ID}\"}}" \
  > artifacts/vector-recall-spike/neon-child.json

export NEON_CHILD_BRANCH_ID="$(jq -r .branch.id artifacts/vector-recall-spike/neon-child.json)"
export NEON_CHILD_ENDPOINT_ID="$(jq -r '.endpoints[] | select(.type=="read_write") | .id' artifacts/vector-recall-spike/neon-child.json)"
test "$NEON_CHILD_BRANCH_ID" != "$NEON_PARENT_BRANCH_ID"
test -n "$NEON_CHILD_ENDPOINT_ID"
```

Poll all returned operations until `finished`:

```bash
jq -r '.operations[]?.id' artifacts/vector-recall-spike/neon-child.json > artifacts/vector-recall-spike/neon-operation-ids.txt
while read -r OP_ID; do
  test -n "$OP_ID" || continue
  while true; do
    curl -fsS -H "Authorization: Bearer $NEON_API_KEY" \
      "https://console.neon.tech/api/v2/projects/${NEON_PROJECT_ID}/operations/${OP_ID}" \
      > "artifacts/vector-recall-spike/neon-operation-${OP_ID}.json"
    STATUS="$(jq -r .operation.status "artifacts/vector-recall-spike/neon-operation-${OP_ID}.json")"
    test "$STATUS" = "finished" && break
    test "$STATUS" = "failed" && cat "artifacts/vector-recall-spike/neon-operation-${OP_ID}.json" && exit 1
    sleep 5
  done
done < artifacts/vector-recall-spike/neon-operation-ids.txt
```

Then get an unpooled connection URI. Determine `database_name` and `role_name` from the child creation response if present; otherwise use the app defaults from target repo environment, and only then try `neondb` and `neondb_owner`.

```bash
curl -fsS -G \
  -H "Authorization: Bearer $NEON_API_KEY" \
  "https://console.neon.tech/api/v2/projects/${NEON_PROJECT_ID}/connection_uri" \
  --data-urlencode "branch_id=${NEON_CHILD_BRANCH_ID}" \
  --data-urlencode "endpoint_id=${NEON_CHILD_ENDPOINT_ID}" \
  --data-urlencode "database_name=${NEON_DATABASE_NAME}" \
  --data-urlencode "role_name=${NEON_ROLE_NAME}" \
  --data-urlencode "pooled=false" \
  > artifacts/vector-recall-spike/neon-connection-uri.json
export DATABASE_URL="$(jq -r .uri artifacts/vector-recall-spike/neon-connection-uri.json)"
```

Write `artifacts/vector-recall-spike/run_manifest.json` containing all branch ids, endpoint ids, runner info, package versions, git SHA, and timestamps. Do not include secrets.

## Corpus View Contract

On the child branch, create a stable view named `spike_eval_chunks` if it does not already exist.

It must expose exactly:

```sql
chunk_uid text not null
video_id text not null
chunk_id text not null
chunk_text text not null
embedding halfvec(1024) not null
```

Suggested SQL, adapt only column names after `\d+ spike_searchable_transcript_chunks`:

```sql
create or replace view spike_eval_chunks as
select
  coalesce(chunk_uid::text, video_id::text || ':' || chunk_index::text) as chunk_uid,
  video_id::text as video_id,
  coalesce(chunk_id::text, chunk_index::text) as chunk_id,
  coalesce(chunk_text, transcript_chunk, text)::text as chunk_text,
  embedding::halfvec(1024) as embedding
from spike_searchable_transcript_chunks;
```

Validate:

```sql
select count(*) as chunks, count(distinct video_id) as videos from spike_eval_chunks;
select vector_dims(embedding::vector) as dims from spike_eval_chunks limit 1;
select count(*) from spike_eval_chunks where embedding is null or chunk_text is null;
```

Expected: about `82178` chunks, about `39567` videos, `1024` dimensions, zero null embeddings/text. If count differs by more than 1%, stop and explain.

Check HNSW index exists on the servable-only table/view source:

```sql
select schemaname, tablename, indexname, indexdef
from pg_indexes
where indexdef ilike '%hnsw%' and indexdef ilike '%embedding%';
```

If absent, create it on the underlying table in the child branch only:

```sql
set maintenance_work_mem = '2GB';
create index concurrently spike_searchable_transcript_chunks_embedding_hnsw_cosine_idx
on spike_searchable_transcript_chunks
using hnsw (embedding halfvec_cosine_ops)
with (m = 16, ef_construction = 64);
```

Record index build wall time. Prior Exp-1 baseline was about 37s.

## Query Set

Produce `artifacts/vector-recall-spike/queries.jsonl` with 200 to 500 rows:

```json
{"query_id":"probe_001","query_text":"high fat high protein","source":"probe","class":"broad_scatter","embedding":[...]}
```

Selection rules:

1. Locate and reuse the prior Exp-1 8 probe queries from the target repo or prior spike artifacts. If not found, stop and ask the operator for the exact 8 unless the operator explicitly allows fallback probes.
2. Force include `"high fat high protein"` and tag it `broad_scatter`.
3. Add about 200 real query texts from query logs. Inspect likely tables/views containing search events, for example names matching `%search%`, `%query%`, `%event%`, `%semantic%`. Use only user-entered or production/pre-prod query text, not generated transcript text.
4. Dedupe by `lower(trim(query_text))`. Drop empty strings, non-English gibberish, and strings longer than 200 characters.
5. Stratify to include broad-scatter and long-tail queries. If there are more than 500, choose max-min diverse queries in embedding space after seeding probes.
6. Embed every query with the same app path used for TopicFinder search and model family `voyage-context-4`. Record the exact embedding model, dimensions, normalization behavior, and code path in `run_manifest.json`.

If fewer than 200 real queries exist, use all available real queries, keep the probes, set `query_count_warning=true`, and do not claim the spike fully representative.

## Exact Ground Truth

Export the full servable corpus once:

```sql
copy (
  select chunk_uid, video_id, chunk_id, chunk_text, embedding::vector as embedding
  from spike_eval_chunks
  order by chunk_uid
) to stdout with csv header;
```

Write `corpus.parquet` and `corpus_vectors.float32.npy`.

Compute exact cosine locally, not through HNSW:

```python
vectors = load_float32_matrix("corpus_vectors.float32.npy")  # shape [82178, 1024]
vectors = vectors / np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-12)
q = q.astype("float32")
q = q / max(np.linalg.norm(q), 1e-12)
scores = vectors @ q
idx2000 = np.argpartition(-scores, 2000)[:2000]
idx2000 = idx2000[np.argsort(-scores[idx2000])]
```

For each query write `ground_truth.jsonl`:

```json
{
  "query_id":"...",
  "exact_top1000_chunk_uids":["..."],
  "exact_top2000_chunk_uids":["..."],
  "exact_top1000_video_ids":["deduped by best chunk order"],
  "exact_top2000_video_ids":["deduped by best chunk order"]
}
```

Cross-check the first 5 queries against Postgres exact seq scan:

```sql
begin;
set local enable_indexscan = off;
set local enable_bitmapscan = off;
set local enable_seqscan = on;
select chunk_uid, embedding <=> $1::halfvec(1024) as dist
from spike_eval_chunks
order by embedding <=> $1::halfvec(1024)
limit 20;
commit;
```

The local exact top 20 must match the Postgres exact top 20 for all 5 cross-checks, aside from ties within `1e-6` cosine distance.

## Turbopuffer Namespace

Use one namespace only:

```bash
export TURBOPUFFER_REGION=gcp-us-central1
export TURBOPUFFER_NAMESPACE="topicfinder-servable-recall-${SPIKE_ID}"
```

Schema:

```python
schema = {
    "vector": {"type": "[1024]f16", "ann": True},
    "video_id": {"type": "string", "filterable": False},
    "chunk_id": {"type": "string", "filterable": False},
    "servable": {"type": "bool", "filterable": False},
    "model": {"type": "string", "filterable": False},
}
```

Use `distance_metric="cosine_distance"` to match pgvector `<=>`.

Use column-oriented writes in batches of 500 to 2000 rows:

```python
tpuf = turbopuffer.Turbopuffer(api_key=os.environ["TURBOPUFFER_API_KEY"], region="gcp-us-central1")
ns = tpuf.namespace(os.environ["TURBOPUFFER_NAMESPACE"])
ns.write(
    upsert_columns={
        "id": chunk_uids,
        "vector": vectors_as_float_lists_or_base64_f32,
        "video_id": video_ids,
        "chunk_id": chunk_ids,
        "servable": [True] * len(chunk_uids),
        "model": ["voyage-context-4/ctx512-o0-d1024-v1"] * len(chunk_uids),
    },
    distance_metric="cosine_distance",
    schema=schema,
)
```

Note: Turbopuffer accepts `[N]f16` vector columns when declared in schema, but API base64 vector encoding is little-endian float32 regardless of storage type. Record whether the runner used JSON arrays or base64 f32. Prefer base64 f32 if JSON upload is slow.

After ingest, poll namespace metadata until `unindexed_bytes == 0` or equivalent metadata shows indexing complete. Record:

- total upload wall time
- rows acknowledged
- batches and retries
- server write `performance.server_total_ms` when present
- `approx_row_count`
- `approx_logical_bytes`

Run Turbopuffer built-in recall as a sanity check:

```python
print(ns.recall(num=50, top_k=1000))
```

If the SDK supports `rank_by` in `ns.recall`, run 20 real query vectors with `top_k=1000` one by one. This is not the primary denominator.

## Approximate Queries

For every query, retrieve `limit=1000` and `limit=2000` from both systems.

### Turbopuffer ANN

No filters.

```python
response = ns.query(
    rank_by=("vector", "ANN", query_embedding_float_list),
    limit=1000,
    include_attributes=["video_id", "chunk_id"],
)
```

Also run `limit=2000`. Capture client wall time and response `performance.server_total_ms` if present.

### Neon pgvector HNSW

No filters. Use the child branch only.

```sql
begin;
set local hnsw.ef_search = 400;
select chunk_uid, video_id, chunk_id, embedding <=> $1::halfvec(1024) as dist
from spike_eval_chunks
order by embedding <=> $1::halfvec(1024)
limit 1000;
commit;
```

Also run `limit=2000`.

For 10 representative queries, capture:

```sql
explain (analyze, buffers, format json)
select chunk_uid, video_id, chunk_id, embedding <=> $1::halfvec(1024) as dist
from spike_eval_chunks
order by embedding <=> $1::halfvec(1024)
limit 1000;
```

The plan must use the HNSW index. If not, stop and fix before collecting recall.

Write `system_results.jsonl`:

```json
{
  "query_id":"...",
  "system":"turbopuffer",
  "k":1000,
  "chunk_uids":["..."],
  "video_ids":["deduped by best chunk order"],
  "client_ms":123.4,
  "server_ms":98.7,
  "phase":"recall"
}
```

## Recall Metrics

For each query, system, and K in `{1000, 2000}`:

```python
chunk_recall_at_k = len(set(system_top_k_chunks) & set(exact_top_k_chunks)) / k
video_recall_at_k = len(set(system_top_k_videos) & set(exact_top_k_videos)) / max(1, len(set(exact_top_k_videos)))
```

Primary measured metric is `chunk_recall@1000`.
Primary verdict is relative: compare Turbopuffer against Neon HNSW `ef_search=400` on the same query ids.
Exact brute-force truth is the shared denominator for both recall numbers, not the control itself.

Secondary metrics:

- `chunk_recall@2000`
- `video_recall@1000`
- `video_recall@2000`
- broad-scatter subset recall
- worst-query recall and query text

Aggregate with mean, median, p05, p01, min, and count below thresholds `0.90`, `0.95`, `0.98`, `0.99`.
Also compute `turbopuffer_minus_neon` for every aggregate metric.

## Reranker-Pass Survival

Use Voyage `rerank-2.5-lite`, cutoff `0.5`, exactly matching production cutoff. The Voyage reranker accepts at most 1000 documents per call, so only rerank top1000 candidate sets.

For each query:

1. Rerank exact top1000 chunk texts.
2. Define `exact_pass_chunk_uids = chunks with rerank_score >= 0.5`.
3. Define `exact_page1_video_ids = first 24 unique video_ids among exact passers sorted by rerank score descending`.
4. For each system, compute:
   - `pass_survival = |exact_pass_chunk_uids intersect system_top1000_chunk_uids| / max(1, |exact_pass_chunk_uids|)`
   - `missed_exact_passers = exact_pass_chunk_uids - system_top1000_chunk_uids`
5. Also rerank the system top1000 and define `system_page1_video_ids` the same way.
6. Compute:
   - `page1_video_loss = |exact_page1_video_ids - system_page1_video_ids| / max(1, |exact_page1_video_ids|)`
   - `page1_missing_video_ids`

Write `rerank_survival.jsonl`:

```json
{
  "query_id":"...",
  "system":"turbopuffer",
  "exact_pass_count":17,
  "pass_survival":1.0,
  "missed_exact_passers":[],
  "page1_exact_count":12,
  "page1_video_loss":0.0,
  "page1_missing_video_ids":[]
}
```

If `VOYAGE_API_KEY` is unavailable, still run recall and latency, but mark adjudication blocked because reranker-pass survival is mandatory.

## Latency Protocol

Measure from the same runner and same query set for both systems. Use `limit=1000`.

Latency phases:

1. `initial_cold`: first query after branch or namespace setup, before any warm-up query.
2. `warm_repeat`: same 20 queries repeated 5 times immediately after `initial_cold`.
3. `warm_diverse`: 100 different queries back to back.
4. `idle_1h`: no calls to that system for 60 minutes, then first 50 diverse queries.
5. `idle_overnight`: no calls to that system for at least 10 hours, then first 50 diverse queries.
6. `tpuf_hint_warm`: Turbopuffer only, call `ns.hint_cache_warm()`, wait 60 seconds, then first 50 diverse queries.

Neon cold induction:

```bash
curl -fsS -X POST \
  -H "Authorization: Bearer $NEON_API_KEY" \
  "https://console.neon.tech/api/v2/projects/${NEON_PROJECT_ID}/endpoints/${NEON_CHILD_ENDPOINT_ID}/restart"
```

After restart operations finish, run the first top1000 query and tag it `neon_restart_cold`. For storage-cold behavior, rely on `initial_cold`, `idle_1h`, and `idle_overnight`; restart may clear compute cache but cannot guarantee remote page eviction.

Turbopuffer cold induction:

- Do not call `hint_cache_warm` before `initial_cold`, `idle_1h`, or `idle_overnight`.
- The only valid forced-cold proxy is a brand-new namespace loaded from the same corpus and queried once after indexing. If used, tag phase `tpuf_fresh_namespace_cold`.

Write `latency_samples.jsonl`:

```json
{
  "system":"turbopuffer",
  "phase":"idle_1h",
  "query_id":"...",
  "k":1000,
  "client_ms":812.4,
  "server_ms":701.0,
  "result_count":1000,
  "runner_region":"us-central1",
  "estimated":false
}
```

Summarize p50, p95, p99, min, max by `system`, `phase`, and `k`.

## Output Tables

The final report must contain these exact tables.

### Corpus And Ingest

| metric | neon_child | turbopuffer |
| --- | ---: | ---: |
| chunks_indexed |  |  |
| videos_indexed |  |  |
| vector_dims | 1024 | 1024 |
| vector_storage_type | halfvec(1024) | [1024]f16 |
| distance_metric | cosine | cosine |
| hnsw_index_build_s |  | n/a |
| upload_wall_s | n/a |  |
| indexing_wait_s | n/a |  |
| namespace_logical_bytes | n/a |  |

### Recall

| system | k | mean_chunk_recall | median_chunk_recall | p05_chunk_recall | min_chunk_recall | queries_below_0_95 | worst_query_id | worst_query_text |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| neon_hnsw_ef400 | 1000 |  |  |  |  |  |  |  |
| turbopuffer | 1000 |  |  |  |  |  |  |  |
| neon_hnsw_ef400 | 2000 |  |  |  |  |  |  |  |
| turbopuffer | 2000 |  |  |  |  |  |  |  |

### Broad-Scatter Recall

| system | k | query_count | mean_chunk_recall | p05_chunk_recall | min_chunk_recall | worst_query_text |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| neon_hnsw_ef400 | 1000 |  |  |  |  |  |
| turbopuffer | 1000 |  |  |  |  |  |

### Reranker Survival

| system | mean_pass_survival | p05_pass_survival | min_pass_survival | queries_with_page1_loss | max_page1_video_loss | worst_query_text | page1_missing_video_ids |
| --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| neon_hnsw_ef400 |  |  |  |  |  |  |  |
| turbopuffer |  |  |  |  |  |  |  |

### Latency

| system | phase | query_count | client_p50_ms | client_p95_ms | client_p99_ms | server_p50_ms | server_p95_ms | estimated | notes |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| neon_hnsw_ef400 | initial_cold |  |  |  |  |  |  |  |  |
| neon_hnsw_ef400 | warm_repeat |  |  |  |  |  |  |  |  |
| neon_hnsw_ef400 | idle_1h |  |  |  |  |  |  |  |  |
| neon_hnsw_ef400 | idle_overnight |  |  |  |  |  |  |  |  |
| turbopuffer | initial_cold |  |  |  |  |  |  |  |  |
| turbopuffer | warm_repeat |  |  |  |  |  |  |  |  |
| turbopuffer | warm_diverse |  |  |  |  |  |  |  |  |
| turbopuffer | idle_1h |  |  |  |  |  |  |  |  |
| turbopuffer | idle_overnight |  |  |  |  |  |  |  |  |
| turbopuffer | tpuf_hint_warm |  |  |  |  |  |  |  |  |

### Neon Control Deltas

Positive recall and survival deltas favor Turbopuffer.
Negative latency and page1-loss deltas favor Turbopuffer.

| gate | neon_control | turbopuffer | delta_tpuf_minus_neon | winner | pass |
| --- | ---: | ---: | ---: | --- | --- |
| mean_chunk_recall_at_1000 |  |  |  |  |  |
| p05_chunk_recall_at_1000 |  |  |  |  |  |
| min_chunk_recall_at_1000 |  |  |  |  |  |
| broad_scatter_mean_chunk_recall_at_1000 |  |  |  |  |  |
| mean_chunk_recall_at_2000 |  |  |  |  |  |
| mean_pass_survival |  |  |  |  |  |
| p05_pass_survival |  |  |  |  |  |
| queries_with_page1_loss |  |  |  |  |  |
| cold_client_p95_ms |  |  |  |  |  |
| warm_client_p95_ms |  |  |  |  |  |

## Pass Bar

Turbopuffer wins only if all are true:

1. Corpus parity: both systems index the same `chunk_uid` set, with zero missing or extra ids.
2. Primary recall gate: Turbopuffer `chunk_recall@1000 >= neon_hnsw_ef400 chunk_recall@1000` on the same query set.
   - Compare mean, median, p05, min, and broad-scatter subset.
   - A single broad-scatter regression must be inspected. A user-visible lost result fails the spike even if aggregate recall ties.
   - Absolute `0.95` to `0.99` recall is diagnostic context only, not the primary gate.
3. Secondary depth check: Turbopuffer `chunk_recall@2000 >= neon_hnsw_ef400 chunk_recall@2000` on the same query set. This catches a deeper tail collapse without changing the primary `@1000` gate.
4. Reranker-pass survival gate: Turbopuffer must match or beat Neon on exact-passer survival.
   - `mean_pass_survival >= neon mean_pass_survival`
   - `p05_pass_survival >= neon p05_pass_survival`
   - `queries_with_page1_loss <= neon queries_with_page1_loss`
   - zero queries where Turbopuffer misses a page-1 exact passer that Neon keeps
5. Latency gate: Turbopuffer must beat Neon on cold and warm top1000 latency, and should meet the product target.
   - Turbopuffer cold p95 must be lower than Neon cold p95 on this rerun. Existing Neon context is cold `2.5s` to `16s`.
   - Turbopuffer warm p95 must be lower than Neon warm p95 on this rerun. Existing Neon context is warm `7ms` to `77ms`.
   - Turbopuffer `initial_cold` or `idle_1h` client p95 should be `<= 2000 ms` from a `us-central1` runner, or server p95 `<= 2000 ms` with credible co-located network adjustment.
6. Operational shape is acceptable:
   - ingest completes without manual support intervention
   - built-in recall endpoint at `top_k=1000` is recorded as a sanity check
   - no unexplained result counts below K

## Decision Rules

Commit to Turbopuffer if it matches or beats the Neon control on primary recall, matches or beats Neon on reranker-pass survival, beats Neon on cold and warm latency, and worst-query inspection shows no meaningful lost TopicFinder page-1 result. Cost is already decided in Turbopuffer's favor and is not a deciding gate in this spike.

Fall back if any of these occur:

- Turbopuffer `chunk_recall@1000` drops below the Neon control number on the same queries.
- Turbopuffer reranker-pass survival drops below the Neon control number.
- Broad-scatter queries such as `"high fat high protein"` lose exact reranker passers that Neon keeps.
- Page-1 video loss is worse than Neon or visible to a user, even if aggregate recall looks high.
- Turbopuffer does not beat Neon cold and warm latency, or cold p95 misses the 2s target from a co-located runner and `hint_cache_warm` is required to meet baseline UX.
- Turbopuffer result counts are inconsistent, indexing cannot converge, or the SDK/API lacks a stable way to load/query the corpus.

If Turbopuffer fails recall against the Neon control but Neon still fails cold latency, do not commit to Neon serverless as-is. The conclusion is: Turbopuffer is not safe for recall-sensitive launch; use resident pgvector/Qdrant as the next fallback benchmark.

## Sources To Recheck Before Running

- Turbopuffer API auth and async operations: https://turbopuffer.com/docs/api-overview
- Turbopuffer writes, f16 schema, column writes: https://turbopuffer.com/docs/write
- Turbopuffer query `ANN`, `top_k`, filters, limit: https://turbopuffer.com/docs/query
- Turbopuffer recall endpoint: https://turbopuffer.com/docs/recall
- Turbopuffer warm cache: https://turbopuffer.com/docs/warm-cache
- Neon create branch: https://api-docs.neon.tech/reference/createprojectbranch.md
- Neon connection URI: https://api-docs.neon.tech/reference/getconnectionuri.md
- Neon restart/suspend/start endpoint APIs: https://api-docs.neon.tech/reference/restartprojectendpoint
- pgvector HNSW and exact-scan behavior: https://github.com/pgvector/pgvector
- Voyage reranker limits: https://docs.voyageai.com/docs/reranker
