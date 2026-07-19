# Evidence Builder Performance Incident

Status: historical incident evidence, resolved. The canonical operating-model
spec's `qa-publication-performance` anchor and Decision 17 own current SLA law.

## Outcome

On 2026-07-17 the TopicFinder evidence index had successful rebuilds taking
404–1,538 seconds, with additional builds terminated by signals 9 and 15. A
test-driven live hotfix reduced a normal full-page rebuild to **20.079 seconds**
while preserving all 140 rendered cards. `TUR-437` subsequently rendered with
its merged PR and 8/8 backend verdict.

## Root cause

The builder called `linear issue view` serially for every discovered evidence
issue on every run—about 139 remote detail calls—even when neither its story nor
references changed. It then refreshed GitHub PRs and fetched evidence-light PR
packet comments serially. Runtime therefore grew with the entire archive rather
than the changed issue.

The coalescing lock limited process count but did not reduce the cost of a build.
New evidence could wait behind one running full-corpus build and one queued
full-corpus build.

## Red/green evidence

Focused tests live at `/root/codex-uploads/test_build_evidence_index.py`.

- Red: unchanged cached issue still called `_issue_view`; changed-detail result
  had no revision marker.
- Green: unchanged details are reused; changed `Awaiting Accept` details refresh;
  state churn outside the review queue does not trigger a detail fetch.
- Red: no concurrent keyed packet-fetch contract existed.
- Green: independent GitHub packet reads rendezvous concurrently and return by
  issue key.

Validation:

```text
python3 -m unittest -v /root/codex-uploads/test_build_evidence_index.py
4 tests passed

python3 -m py_compile /root/codex-uploads/build-evidence-index.py
passed

full benchmark
BENCHMARK elapsed=20.079 user=7.346 sys=2.134
wrote index.html: 140 cards (6 PR groups pending / 124 accepted), 1 packet, 24 archived
```

## Hotfix mechanics

- Cache Linear detail parsing by issue revision.
- On cache migration, seed revision markers from the last successful complete
  detail cache rather than forcing another archive-wide cold fetch.
- Refresh changed details only while an issue is entering `Awaiting Accept`.
- Run independent GitHub PR and packet-comment reads concurrently with bounded
  fan-out.
- Preserve atomic page replacement and existing offline fallbacks.

## Remaining structural work

The hotfixed generator and its focused tests live under `/root/codex-uploads`,
not a versioned repo. That is not an acceptable durable source. Because the
gallery, paths, Linear team, and TopicFinder presentation are target-specific,
the canonical generator belongs in Turbo-Outreach—not in generic octo-lite.
The installed live entrypoint should be a symlink or built artifact from that
tracked source, with a drift check.

The longer-term design should stop rebuilding the archive at all for routine
acceptance: write one immutable per-issue card/manifest, update a small queue
index atomically, and reserve a full rebuild for repair or explicit archive
maintenance.

Operator ruling: routine per-issue publication has a **≤5-second SLA**. An
explicit full-archive repair build has a **≤60-second SLA**. The current
20.079-second cached full build is an interim hotfix and does not satisfy the
routine publication target.
