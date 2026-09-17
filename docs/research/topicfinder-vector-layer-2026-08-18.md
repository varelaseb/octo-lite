# TopicFinder Vector Layer Research - 2026-08-18

Question: choose a vector layer for TopicFinder semantic search at about 1M videos, about 2M `1024`-dimension `halfvec` chunks, about 5GB logical index, low-QPS diverse cold queries, high recall at about `top_k=1000`, mutable servable filtering around 29-43%, Cloud Run in `us-central1`.

Sources are primary/current vendor docs, pricing pages, source repos, and cloud docs only.

## Short Verdict

Turbopuffer is the best fit to test first for this workload.
It has an official `gcp-us-central1` region, object-storage-first storage with memory/NVMe caching, first-query and cached latency claims for 1M documents, explicit recall-aware filtering, and usage pricing whose low-QPS cost is storage plus bytes queried rather than a resident node floor.

Qdrant is the strongest conventional alternative if we want an open-source engine, richer operational control, and self-host/BYOC portability.
The trade is resident resource sizing: Qdrant Cloud bills CPU/RAM/disk hourly, and self-hosting means we own memory tiers, disk, backups, upgrades, and recall/latency tuning.

Pinecone serverless is viable in `gcp us-central1`, but official docs say query cost is based on namespace size and metadata filtering in one large namespace still scans/pays for the whole namespace.
That is an awkward match for mutable servable filters unless TopicFinder can shard into namespaces that match the filter boundary.
Pods are legacy/unavailable to new customers after 2025-08-18; Dedicated Read Nodes replace the high-throughput resident-cache story.

Resident pgvector is attractive for SQL locality and very low ops surface if we already run Postgres, but it is the highest-risk recall/latency choice for high `top_k` plus post-filtered ANN.
pgvector's own docs say approximate-index filtering is applied after index scan and needs iterative scans, partial indexes, or partitioning to avoid under-returning filtered rows.

## Workload Sizing Notes

- Raw vector payload: `2M * 1024 * 2 bytes = 4.096GB` for `halfvec`, before ids, metadata, filter indexes, ANN graph or cluster structures, write amplification, and replication.
- Qdrant's public RAM sizing formula for full `float32` vectors is `vectors * dimension * 4 bytes * 1.5`; for 1M `1024`-d vectors it estimates about 5.72GiB. That implies `2M` full-float vectors are about 11.4GiB before payloads and replicas; half precision or quantization changes this, but Qdrant's formula is a useful resident-engine upper bound. Source: <https://qdrant.tech/documentation/capacity-planning/>.
- For Pinecone and Turbopuffer pricing, the important billable unit is not raw vectors alone. Pinecone serverless query cost tracks namespace scanned/read units; Turbopuffer tracks logical storage, writes, and queried data, with a per-query minimum.

## Turbopuffer

### Placement

- Supports `gcp-us-central1` directly. The regions page lists `gcp-us-central1` as Iowa, US. Source: <https://turbopuffer.com/docs/regions>.
- Supports private networking to GCP regions through Private Service Connect on enterprise plans. Source: <https://turbopuffer.com/docs/private-networking>.
- BYOC can deploy into customer Kubernetes on AWS, GCP, or Azure, with Turbopuffer on call for the cluster. Source: <https://turbopuffer.com/docs/byoc>.

### Architecture, Latency, Cold Behavior

- Architecture is object-storage-first. The API routes to Rust binaries that access object storage; data is cached in memory/NVMe SSD after access. Source: <https://turbopuffer.com/docs/architecture>.
- Official cold/warm claim: first query to a namespace reads object storage and is slow, `p50=874ms` for 1M documents; subsequent cached queries to that node are `p50=14ms` for 1M documents. Source: <https://turbopuffer.com/docs/architecture>.
- Architecture docs also say ANN and BM25 indexes are optimized for object storage, with good cold latency around `~500ms` on 1M documents, and exact indexes for metadata filtering. Source: <https://turbopuffer.com/docs/architecture>.
- Namespace pinning reserves compute and NVMe cache, keeps data hot, and switches billing from per-query queried bytes to GB-hours. It is usually worth evaluating above a large namespace over 16GB and sustained above 10 QPS; TopicFinder's low-QPS shape likely favors unpinned multi-tenant unless cold latency is unacceptable. Source: <https://turbopuffer.com/docs/pinning>.

### Filtering

- Query filters support exact predicates over attributes and ids, including `Eq`, `NotEq`, `In`, `ContainsAny`, and nested `And`/`Or`/`Not`. Filters are evaluated against an inverted index. Source: <https://turbopuffer.com/docs/query>.
- Turbopuffer explicitly claims filtering is recall-aware for vector queries. Source: <https://turbopuffer.com/docs/query>.
- Permissions docs recommend implementing document access through filters and say the filterable-attribute inverted index supports efficiently filtering tens of thousands of permission ids without performance degradation. Source: <https://turbopuffer.com/docs/permissions>.
- For TopicFinder's mutable `servable` filter at 29-43%, this is the cleanest hosted semantic fit: a boolean/integer attribute can be filterable, and the vendor claims vector recall accounts for filters instead of post-filtering an ANN candidate set.

### ANN, Recall Knobs

- Vector search uses an incrementally indexed SPFresh vector index, supports filtering, and writes appear in search results immediately. Source: <https://turbopuffer.com/docs/vector>.
- Turbopuffer says the vector index is automatically tuned for 90-100% recall and production recall is automatically monitored. Source: <https://turbopuffer.com/docs/vector>.
- Concepts docs say recall is measured on 1% of live query traffic and targets 90-95% recall@10 for all queries, including filtered queries; a recall endpoint can evaluate a namespace. Source: <https://turbopuffer.com/docs/concepts> and <https://turbopuffer.com/docs/recall>.
- Risk: the official recall claims are mostly `recall@10`. TopicFinder cares about high recall around `top_k=1000`, so we still need a direct benchmark with `top_k=1000`, `include_vectors=false`, real filters, and cold diverse queries.

### Cost Dimensions

- Plan minimums: Launch `$16/month`, Scale `$256/month`, Enterprise `>= $4,096/month` plus 35% usage premium. Source: <https://turbopuffer.com/pricing>.
- Query pricing changelog says base queried-data rate is `$1/PB`, with 80% marginal discount for 32-128GB per query, 96% marginal discount above 128GB, and minimum billable data per query of 1.28GB. Source: <https://turbopuffer.com/docs/pricing-log>.
- Pinning is billed by `namespace size GB * replicas * hours pinned`, with 64GB and 10-minute billing floors; pinned queries are not subject to TB/PB queried usage pricing. Source: <https://turbopuffer.com/docs/pinning>.
- At 1M videos / 2M chunks / about 5GB logical, low QPS likely lands near the Launch minimum plus storage/query bytes. At 10M videos / 20M chunks / about 50GB logical, low QPS still likely stays object-storage-economic, but per-query minimum and scanned bytes dominate if query count rises.

### Ops

- Hosted multi-tenant default; enterprise can use single-tenancy or BYOC. Source: <https://turbopuffer.com/docs/architecture> and <https://turbopuffer.com/docs/byoc>.
- Low operator burden for Cloud Run. Main operational tasks: schema/filter design, load/warm strategy, recall test, export/backups, and deciding whether cold latency is product-acceptable.

## Qdrant

### Placement

- Qdrant Cloud supports AWS, GCP, and Azure across multiple regions; exact region is selected in the console/pricing flow. Source: <https://qdrant.tech/cloud/>.
- Cloud page shows Terraform examples with explicit `cloud_provider` and `cloud_region`, and states Cloud uses the same open-source Rust engine as self-hosted. Source: <https://qdrant.tech/cloud/>.
- GCP has an official tutorial for deploying Qdrant on GKE. Source: <https://docs.cloud.google.com/kubernetes-engine/docs/tutorials/deploy-qdrant>.

### Architecture, Latency, Cold Behavior

- Qdrant is a resident vector DB with configurable memory/disk placement. By default vectors are stored in RAM for performance; large collections can offload vectors to disk, with memory-mapped files and OS page cache for cold memory tiers. Source: <https://qdrant.tech/documentation/overview/> and <https://qdrant.tech/documentation/capacity-planning/>.
- Capacity docs state if only half as many vectors are in RAM, search latency will roughly double, and disk speed is crucial. Source: <https://qdrant.tech/documentation/capacity-planning/>.
- Qdrant Cloud claims a typical 10M-vector 768-d collection with moderate filtering has single-digit millisecond P50 and under 50ms P99, with results depending on dimension, recall target, filters, and cluster size. Source: <https://qdrant.tech/cloud/>.
- Risk: low-QPS diverse cold queries can miss OS cache and expose disk behavior. Unlike Turbopuffer, Qdrant's public docs do not present a cold-object-storage query path with explicit first-query latency numbers for this workload.

### Filtering

- Qdrant supports payload and id filters, with `must`, `should`, and `must_not` clauses that can be recursively nested. Source: <https://qdrant.tech/documentation/search/filtering/>.
- Qdrant recommends payload indexes for fields used in filters, and says payload indexes are used for quick point requests and cardinality estimation so query planning can choose a search strategy. Source: <https://qdrant.tech/documentation/manage-data/indexing/>.
- Qdrant Cloud disables filtering and updating by non-indexed payload attributes by default and restricts payload indexes to 100. Source: <https://qdrant.tech/documentation/overview/>.
- For a mutable `servable` filter at 29-43%, Qdrant should be fine if the field is indexed. The recall/latency behavior should be benchmarked because filter selectivity and recall target materially affect search.

### ANN, Recall Knobs

- Qdrant uses HNSW vector indexes and payload indexes. HNSW parameters and optimizer behavior are collection-level concerns. Source: <https://qdrant.tech/documentation/manage-data/indexing/>.
- Qdrant has quantization options; Cloud FAQ claims scalar quantization typically loses 1-2% recall and cuts RAM by 4x, TurboQuant offers higher compression, and binary with rescoring can keep recall close to full precision for compatible models. Source: <https://qdrant.tech/cloud/>.
- Qdrant Cloud page claims CPU indexing can handle tens of thousands of vectors/sec per node depending on dimension and HNSW parameters, with GPU-accelerated HNSW indexing up to 4x faster on AWS today. Source: <https://qdrant.tech/cloud/>.

### Cost Dimensions

- Qdrant Cloud bills based on CPU, memory, and disk storage usage. Source: <https://qdrant.tech/documentation/cloud-pricing-payments/>.
- Free tier is one node with 0.5 vCPU, 1GB RAM, 4GB disk; Cloud page says that fits roughly 1M 768-d vectors, but free clusters suspend after one week of inactivity and delete after four weeks if not reactivated. Source: <https://qdrant.tech/cloud/>.
- Standard clusters add dedicated resources, backup/disaster recovery, multi-node HA, and scaling. Source: <https://qdrant.tech/documentation/cloud/create-cluster/>.
- At 1M/2M chunks, resident Qdrant likely needs a small paid cluster if full-precision vectors/indexes and payload indexes exceed free RAM/disk. At 10M/20M chunks, cost scales with resident RAM/disk and replicas, not with query count; that is good for high QPS but less efficient than object-storage-first for low QPS.

### Ops

- Hosted Qdrant Cloud handles upgrades, scaling, sharding, backups, and monitoring. Source: <https://qdrant.tech/cloud/>.
- Self-hosted Qdrant gives portability and no license cost, but requires sizing, memory tiers, backup/snapshot discipline, rolling upgrades, shard/replica management, and alerting.

## Pinecone Serverless, Dedicated Read Nodes, Pods

### Placement

- Serverless supports `gcp us-central1` on Builder, Standard, and Enterprise plans. Source: <https://docs.pinecone.io/guides/index-data/create-an-index>.
- The cloud and region cannot be changed after a serverless index is created. Source: <https://docs.pinecone.io/guides/index-data/create-an-index>.
- BYOC is public preview on AWS, GCP, and Azure; data plane runs in customer cloud/VPC using object storage, while Pinecone runs the control plane. Source: <https://docs.pinecone.io/guides/production/bring-your-own-cloud>.

### Architecture, Latency, Cold Behavior

- Pinecone serverless docs emphasize usage pricing where idle indexes cost nothing; official public docs do not expose the ANN/index algorithm or cold-query cache architecture in the same concrete way as Turbopuffer. Source: <https://docs.pinecone.io/guides/manage-cost/understanding-cost>.
- Dedicated Read Nodes add resident compute/cache. `b1` caches vector index in memory; `t1` caches vector index plus vector projections, with about 4x compute/memory and about 3x cost versus `b1`. Each shard has 250GB storage. Source: <https://docs.pinecone.io/guides/index-data/dedicated-read-nodes>.
- Serverless data freshness is eventually consistent. Source: <https://docs.pinecone.io/guides/search/search-overview>.

### Filtering

- Metadata is flat JSON; nested objects are not supported. Source: <https://docs.pinecone.io/guides/index-data/data-modeling>.
- Filters support operators such as `$eq`, `$in`, `$gt`, `$and`, etc. Source: <https://docs.pinecone.io/guides/search/filter-by-metadata>.
- Important cost/perf semantic: Pinecone says query cost is based on namespace size. With 100 tenants of 1GB each, querying one tenant namespace costs 1 RU; using metadata filtering in one 100GB namespace costs 100 RUs because it scans all data even though the filter narrows results. Source: <https://docs.pinecone.io/guides/index-data/data-modeling>.
- Pinecone warns against high-cardinality ID filters: `$in`/`$nin` has a 10,000 value limit, large filters increase latency, and filtering a shared namespace means paying to scan the whole namespace. Source: <https://docs.pinecone.io/guides/index-data/data-modeling>.
- For TopicFinder, a single mutable `servable` boolean at 29-43% is much simpler than ACL lists, but the namespace-size billing semantics still mean filtering does not reduce scanned-cost unless the data model shards by namespace.

### ANN, Recall Knobs

- Public docs expose high-level index types and similarity metrics, not detailed HNSW/IVF/ScaNN knobs. Source: <https://docs.pinecone.io/guides/index-data/create-an-index>.
- Search supports `top_k` up to 10,000, with a 4MB result-size limit; high `top_k=1000` should avoid returning vectors and bulky metadata. Source: <https://docs.pinecone.io/guides/search/search-overview>.

### Cost Dimensions

- Serverless cost dimensions are read units, write units, storage, and egress. Source: <https://docs.pinecone.io/guides/manage-cost/understanding-cost>.
- Plan floors: Builder `$20/month` flat, Standard `$50/month` minimum usage, Enterprise `$500/month` minimum usage. Source: <https://www.pinecone.io/pricing/>.
- Pricing page shows write units on Standard at `$4-$4.50 per million` and Enterprise at `$6-$6.75 per million`, varying by cloud/region; current storage/read rates are surfaced through the pricing UI/calculator rather than clean static text in the crawled page. Source: <https://www.pinecone.io/pricing/>.
- Serverless has per-namespace 100 QPS limits for query/upsert/delete/update across plans unless raised; Dedicated Read Nodes are not subject to read-unit limits for query/fetch/list. Source: <https://docs.pinecone.io/reference/api/database-limits>.
- Pods are legacy: customers signing up for Standard or Enterprise on or after 2025-08-18 cannot create pod-based indexes; Pinecone directs new customers to serverless and Dedicated Read Nodes. Source: <https://docs.pinecone.io/guides/indexes/pods/understanding-pod-based-indexes>.

### Ops

- Serverless is lowest Pinecone ops; Dedicated Read Nodes introduce shard/node sizing. BYOC increases cloud-account integration but keeps Pinecone managed operations.
- Main fit issue is cost semantics under metadata filtering and opaque recall knobs for `top_k=1000`.

## Resident pgvector on RDS or Self-Hosted NVMe+RAM

### Placement

- Runs wherever PostgreSQL runs: RDS PostgreSQL/Aurora, Cloud SQL, AlloyDB, GCE, GKE, EC2, bare metal.
- AWS RDS PostgreSQL pricing is based on DB instance hours, storage, provisioned IOPS if used, backup storage, and data transfer. Source: <https://aws.amazon.com/rds/postgresql/pricing/>.
- RDS has managed backups/failover but no local NVMe control; self-hosted NVMe+RAM has lower latency control and lower software cost but full DB ops ownership.

### Architecture, Latency, Cold Behavior

- pgvector is a Postgres extension, so it inherits Postgres buffer cache, storage engine, WAL, vacuum/autovacuum, and planner behavior.
- pgvector supports exact search and approximate HNSW/IVFFlat indexes. Source: <https://github.com/pgvector/pgvector>.
- With resident RAM and a small 5GB vector body, pgvector can be very cheap if the same Postgres instance already exists. With cold NVMe/EBS and high `top_k`, latency variance and recall tuning need direct measurement.

### Filtering

- Critical caveat: pgvector docs state filtering is applied after the approximate index is scanned. If a condition matches 10% of rows and default `hnsw.ef_search=40`, only about 4 rows match on average; use iterative index scans for more rows. Source: <https://github.com/pgvector/pgvector>.
- Iterative scans were added in 0.8.0 and can continue scanning until enough filtered rows are found or `hnsw.max_scan_tuples` / `ivfflat.max_probes` is reached. Source: <https://github.com/pgvector/pgvector> and <https://www.postgresql.org/about/news/pgvector-080-released-2952/>.
- pgvector recommends partial indexes for few distinct filter values and partitioning for many different values. Source: <https://github.com/pgvector/pgvector>.
- For TopicFinder's `servable` 29-43% filter, post-filtered ANN is less severe than a 1% ACL filter but still relevant for `top_k=1000`: at 29%, candidate count needs to be much larger than 1000 to reliably return 1000 filtered hits.

### ANN, Recall Knobs

- HNSW index options include `m` and `ef_construction`; query-time `hnsw.ef_search` controls search breadth. Source: <https://github.com/pgvector/pgvector>.
- IVFFlat query-time `ivfflat.probes` controls probes; setting probes to number of lists makes search exact but planner will not use the index. Source: <https://github.com/pgvector/pgvector>.
- `halfvec` supports up to 4,000 dimensions, so TopicFinder's 1024-d half vectors fit. Source: <https://github.com/pgvector/pgvector>.

### Cost Dimensions

- RDS/Aurora: resident instance-hours plus storage, IOPS, backups, and cross-AZ/egress. Good if piggybacking on an existing DB; bad if sizing a dedicated resident DB only for low-QPS vector search.
- Self-hosted GCE/GKE/EC2: compute instance plus persistent/local SSD plus backup/snapshot storage plus ops time. Local NVMe can make pgvector or Qdrant fast, but node loss and backup/restore become application concerns.
- At 1M/2M chunks, a single RAM-heavy instance can hold the vector body and indexes; at 10M/20M chunks, HNSW graph/index memory and filter/metadata indexes likely force larger RAM or partitioning/quantization strategy.

### Ops

- Lowest new vendor surface; highest performance-engineering burden.
- Needs vacuum/index maintenance, extension upgrades, query-plan testing, failover/restore drills, and recall regression tests after data distribution changes.

## Notable Alternatives

### Google Vertex AI Vector Search

- Fully managed Google vector search based on ScaNN. Source: <https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/vector-search/overview>.
- Strong GCP-native placement and scale story, but its endpoint/index deployment model is more ML-platform-like than app-database-like. Evaluate if the team wants a managed Google service and can accept its index update/deploy workflow.
- Cost is tied to deployed indexes/nodes and data size rather than purely low-QPS usage; use Google pricing calculator for current quotes. Source: <https://cloud.google.com/products/gemini-enterprise-agent-platform/pricing>.

### AlloyDB AI / ScaNN for PostgreSQL

- AlloyDB AI provides PostgreSQL-compatible vector search and supports ScaNN, HNSW, and IVFFlat strategy choices. Source: <https://docs.cloud.google.com/alloydb/docs/ai/choose-index-strategy>.
- Google claims ScaNN for AlloyDB has better behavior when indexes do not fit in main memory than HNSW because HNSW can incur expensive random I/O. Source: <https://cloud.google.com/blog/products/databases/how-scann-for-alloydb-vector-search-compares-to-pgvector-hnsw>.
- Good candidate if TopicFinder wants SQL-native filtering and GCP-managed Postgres semantics, but it is still a resident database cost/ops model.

### Milvus / Zilliz

- Milvus supports many index types and has DISKANN, which combines a disk-based Vamana graph with product quantization. Source: <https://milvus.io/docs/diskann.md>.
- Milvus also supports mmap-enabled storage to reduce RAM pressure. Source: <https://milvus.io/docs/mmap.md>.
- Strong for large self-hosted/distributed vector infra, but likely more ops machinery than this low-QPS 5GB starting point needs unless the 10M path is primary.

### Weaviate

- Open-source vector DB with managed cloud; pricing page says vector dimension pricing varies by index type, compression, and region, with exact running costs in the Cloud console. Source: <https://weaviate.io/pricing>.
- Google has an official GKE deployment tutorial. Source: <https://docs.cloud.google.com/kubernetes-engine/docs/tutorials/deploy-weaviate>.
- Worth including in benchmark only if hybrid/schema features matter. Otherwise Qdrant is the cleaner open-source comparison target for this decision.

### LanceDB

- Columnar/table-oriented vector store is attractive for local/object-store workflows, but hosted/servable filtering and low-latency query guarantees need a separate current source pass before serious selection.

## Decision Matrix

| Option | Fit for current shape | Main strength | Main risk |
| --- | --- | --- | --- |
| Turbopuffer | Best first test | `gcp-us-central1`, cold/warm object-storage architecture, recall-aware filters, low-QPS economics | Need benchmark for `top_k=1000` and 29-43% filters; cold p50 may be too high |
| Qdrant Cloud | Strong fallback | Open-source engine, rich filters, managed ops, resident low latency | Hourly resident resource cost; cold disk/cache behavior under diverse queries |
| Pinecone serverless | Plausible but weaker | `gcp us-central1`, serverless ops, high `top_k` limit | Metadata filters still scan/pay whole namespace; opaque ANN knobs |
| Pinecone DRN | Overkill now | Resident cache and predictable throughput | Designed for sustained/larger workloads; node cost floor |
| Pinecone pods | Not a new-customer option | Legacy resident Pinecone model | New customers cannot create pods after 2025-08-18 |
| pgvector RDS/self-host | Good if SQL locality dominates | No new vector vendor, exact SQL filters, low raw data size | Post-filtered ANN recall, planner/index tuning, ops burden |
| AlloyDB AI | Good GCP SQL-native alternative | ScaNN with PostgreSQL compatibility | Resident DB cost and AlloyDB-specific ops |
| Vertex AI Vector Search | GCP-native managed scale | ScaNN, managed large-scale serving | Endpoint/index workflow and pricing may be heavy for low QPS |
| Milvus/Zilliz | Scale-oriented alternative | DiskANN/mmap, distributed open source | Ops complexity |

## Recommended Evaluation

1. Benchmark Turbopuffer in `gcp-us-central1` with the real embedding distribution, `top_k=1000`, `include_vectors=false`, and mutable `servable` filters at 29%, 43%, and unfiltered.
2. Record cold namespace p50/p90/p99, warm p50/p90/p99, recall against exact search for at least a representative sample, and cost at expected daily query counts.
3. Run Qdrant as the resident baseline with payload index on `servable`, both RAM and disk/memory-tier configurations, and target recall tuned upward until `top_k=1000` is stable.
4. Test pgvector only if SQL locality or avoiding a new vendor is a hard requirement; include `hnsw.iterative_scan=relaxed_order`, larger `hnsw.ef_search`, and a partial index or partition for `servable=true`.
5. Do not spend time on Pinecone pods. For Pinecone, test only serverless and maybe Dedicated Read Nodes if QPS grows enough to justify resident cache.

## Citation Index

- Turbopuffer architecture: <https://turbopuffer.com/docs/architecture>
- Turbopuffer regions: <https://turbopuffer.com/docs/regions>
- Turbopuffer query/filtering: <https://turbopuffer.com/docs/query>
- Turbopuffer permissions filters: <https://turbopuffer.com/docs/permissions>
- Turbopuffer vector search: <https://turbopuffer.com/docs/vector>
- Turbopuffer recall: <https://turbopuffer.com/docs/concepts>, <https://turbopuffer.com/docs/recall>
- Turbopuffer pricing and pinning: <https://turbopuffer.com/pricing>, <https://turbopuffer.com/docs/pricing-log>, <https://turbopuffer.com/docs/pinning>
- Qdrant Cloud: <https://qdrant.tech/cloud/>
- Qdrant filtering: <https://qdrant.tech/documentation/search/filtering/>
- Qdrant indexing: <https://qdrant.tech/documentation/manage-data/indexing/>
- Qdrant capacity/billing: <https://qdrant.tech/documentation/capacity-planning/>, <https://qdrant.tech/documentation/cloud-pricing-payments/>
- Pinecone pricing/cost/regions/DRN/filtering: <https://www.pinecone.io/pricing/>, <https://docs.pinecone.io/guides/manage-cost/understanding-cost>, <https://docs.pinecone.io/guides/index-data/create-an-index>, <https://docs.pinecone.io/guides/index-data/dedicated-read-nodes>, <https://docs.pinecone.io/guides/index-data/data-modeling>, <https://docs.pinecone.io/guides/search/search-overview>
- pgvector: <https://github.com/pgvector/pgvector>, <https://www.postgresql.org/about/news/pgvector-080-released-2952/>
- AWS RDS PostgreSQL pricing: <https://aws.amazon.com/rds/postgresql/pricing/>
- Google Vertex AI Vector Search: <https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/vector-search/overview>
- AlloyDB AI vector search: <https://docs.cloud.google.com/alloydb/docs/ai/choose-index-strategy>, <https://cloud.google.com/blog/products/databases/how-scann-for-alloydb-vector-search-compares-to-pgvector-hnsw>
- Milvus DiskANN/mmap: <https://milvus.io/docs/diskann.md>, <https://milvus.io/docs/mmap.md>
- Weaviate pricing/GKE: <https://weaviate.io/pricing>, <https://docs.cloud.google.com/kubernetes-engine/docs/tutorials/deploy-weaviate>
