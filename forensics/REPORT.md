# gh#31 forensic report: herdr transport first-fire stall

Status: FORENSICS COMPLETE. Root cause proven. NO fix applied (report-first
mandate). Reproduction harness green (13/13).

## One-line root cause

The transport confirmation has NO signal correlated to *this message's*
submission. Both confirmation heuristics in `prompt_confirmed` are wrong, so a
send into any active pane is misjudged in BOTH directions depending on the
target's incidental status activity.

## The confirmation core (herdr-say + herdr-drain, identical `prompt_confirmed`)

After `herdr agent prompt <pane> <body> --wait --timeout 15000`, delivery is
"confirmed" iff EITHER:
1. matched-state: stdout matches `"state":"(idle|done|blocked)"`, OR
2. seq-advance: `state_change_seq` read via `herdr agent get` AFTER > the value
   read BEFORE the prompt.

Both are defective.

## RC1 - dead matched-state matcher (schema-proven; harness S3)

herdr 0.7.5 `agent_prompted` / `agent get` results carry the status in field
`agent_status` (enum idle|working|blocked|done|unknown). There is NO `state`
field (verified against `herdr api schema` -> AgentInfo props; confirmed on live
`agent get`). The wrapper greps for `"state":"..."`, which herdr never emits.
=> matched-state path is DEAD. Confirmation degrades to seq-advance alone.

## RC2 - seq-advance FALSE NEGATIVE on busy targets (harness S1)

`state_change_seq` increments only on an agent_status CHANGE. A target that is
continuously "working" across the whole 15s window (operator Fable mid-turn, an
orchestrator mid-turn) emits no status change -> seq unchanged -> reported
UNCONFIRMED even though the prompt WAS submitted. Result: rc 75, message stays
pending+deferred with its inbox item, and herdr-drain RE-FIRES a message that
already delivered => DUPLICATE. This is the dominant driver of:
- "near-every first fire exits 75", transport_attempts=2/3 corpus (140 at 2,
  34 at 3 in live messages),
- 13 messages stalled at cap (3 unconfirmed re-deliveries then stall),
- multi-hour / cross-day redelivery floods and "8 concurrently pending inbound"
  into the operator, especially orchestrator->operator (operator addendum),
  because Fable is usually working.

## RC3 - seq-advance FALSE POSITIVE, message stuck in composer (harness S2)

`state_change_seq` is a GLOBAL per-agent counter, uncorrelated to this prompt.
If a busy target's status flips for an UNRELATED reason during the ~15s window
(its own turn ends, etc.), seq advances and the wrapper declares CONFIRMED
`direct`, transitions the message, and REMOVES the inbox item -> no retry. If
the prompt did NOT actually submit (residual composer text, the soak "A1"
swallow herdr's own doc warns about), the message is now LOST in the composer
and the operator must hand-submit it. This exactly matches the live specimen
`20260727T203323-2368806-11866` (target forwarding-gap): `delivery_path=direct`,
`transport_attempts=1` -- transport claimed clean first-fire delivery, yet the
operator found it unsent in the box. A "confirmed" first-fire that is actually
unsubmitted can only be RC3.

## Not the bug (ruled out)

- `--timeout` unit: value 15000 with `--timeout <MS>` = 15s, correct.
- The 5000ms non-working state-change floor: an idle-target true swallow
  correctly returns `agent_prompt_stalled`, which the wrapper treats as
  unconfirmed. Handled.
- Locks / id creation / atomic publish: sound; no evidence of corruption.

## Contributing / secondary symptoms

- ACK-WAIT backlog: non-info messages stay `pending` after real delivery until
  an explicit herdr-ack (21 live delivered-`direct`-but-unacked). By design, but
  RC2 duplicate deliveries inflate the visible inbound pile.
- herdr-ack "illegal transition completed -> acknowledged": an info message
  auto-completes on confirm; when RC2 later REDELIVERS the same info as a dup and
  the recipient tries to ack it, the state is already `completed` -> illegal
  transition noise. Symptom of RC2 dups, not a distinct fault.
- `stale_retry_removed=1` on long-acked messages: an inbox item is cleared only
  on the NEXT drain for that target, so it outlives the ack; a drain landing in
  the window between delivery and ack can also re-fire (another dup path).

## Reproduction harness

`forensics/harness/` : a stub `herdr` faithfully implementing the 0.7.5 contract
(agent_status field, global state_change_seq, prompt --wait outcomes) that
DECOUPLES real submission from the confirmation signal. `run-repro.sh` drives the
UNMODIFIED `herdr-say`/`herdr-drain` under a private XDG_STATE_HOME and asserts:
S1 false-negative + duplicate, S2 false-positive + item loss, S3 dead matcher,
S4 control success. 13/13 green. No live state touched.

## Fix directions (NOT applied; require operator disclosure + accept)

Any change here alters delivery semantics for RUNNING lanes -> DISCLOSE loudly,
act-then-notify with rollback, TDD by promoting this harness into the octo-lite
suite, merge on operator accept only. Candidate directions to validate, not yet
chosen:
1. Confirm on a SUBMISSION-CORRELATED signal, not global seq: e.g. treat the
   `agent_prompted` success result (rc 0, type=agent_prompted) as submit-accepted
   and add a distinct residual-text / composer-empty guard for the A1 swallow.
2. Fix the matcher field to `agent_status` AND stop using a bare global-seq
   advance as proof (neither necessary nor sufficient).
3. Turn-tracked wait (`herdr agent wait` on a fresh turn) instead of a raw seq
   delta, to distinguish this prompt's turn from incidental status churn.

## Post-review remediation (operator rulings + lean frame)

Applied (code + TDD, tests/test_herdr.py 101 green):
- Cap-reached stalls BEFORE the eligibility gate (stalls regardless of busy).
- Starvation bound: one AGE bound off the existing `created_at` (a defer older
  than `OCTO_TRANSPORT_DEFER_MAX_AGE_S`, default 900s = one sweep cycle, stalls
  LOUD); reprocessed by `herdr-drain` (herdr-say never ages a fresh send).
- `herdr-drain --all`: target-independent drain so a neutral caller delivers to
  every idle target on its behalf (resolves the self-defer starvation).
- Structured confirmation: parse the herdr result (`error.code`, `result.type`,
  `agent_status`) instead of grepping combined text, so an error payload
  (agent_not_running / client_disconnected) carrying "timed out"/"working"
  tokens is never misread as delivered; a `timeout` confirms only above the
  5000ms floor.
- Canonical spec amended: `operator-control.spec.html` anchors
  `message-eligibility-gate`, `message-observed-confirmation`,
  `message-starvation-bound` (through the spec-chat review loop; code does not
  merge before the amended spec lands).

Recorded, NOT implemented (lean frame - beyond the minimum):
- The operator's "5 defers" faster tripwire (in addition to the 15m age bound).
  The single age bound already delivers the stated guarantee (nothing waits
  unseen past one sweep cycle); a defer counter would add a per-message schema
  field and counting machinery for a faster-trip refinement. Recorded here for a
  future pass if rapid-redeferral latency ever matters.
- TOCTOU between the gate read and the prompt / no per-target lock (codex HIGH-4):
  the structured confirm already fails closed (a target that flips to working
  mid-fire yields a non-confirming outcome), so this cannot cause a false
  positive, only an occasional honest retry. A per-target lock is recorded as a
  future hardening, not built now.

## Iteration 3 (second codex verdict + operator rulings: cadence 15m, cleanest)

Closed both surviving blockers:
- STARVATION (all edge paths): the age bound now lives in ONE place, the
  operator-sweep, which each cycle first runs `herdr-drain --all` (delivers every
  target's deferred inbox on its behalf) then ages any still-retryable message
  older than OCTO_TRANSPORT_DEFER_MAX_AGE_S (default 900s) to stalled under the
  message lock, independent of target liveness / modal / self-working. The timer
  cadence default is now 15m (= 900s), so "one sweep cycle" is exact. herdr-drain
  no longer ages (deleted). This closes codex's aged-modal / aged-unresolved /
  cap-behind-modal / no-periodic-drainer reproductions.
- TOCTOU (now IMPLEMENTED, not deferred): a non-blocking per-target flock
  (locks/target-<target>.lock, acquired after the message lock, dropped from the
  fired subprocess so a crash cannot strand it) serializes gate-through-fire, so
  two concurrent sends to one target cannot both fire into the same idle window.
  The pane-form gate bypass is removed (all targets gated), so the confirmation
  precondition always holds. My earlier "fails closed" claim was wrong; this is
  the real close.

Spec reconciled: message-eligibility-gate (no pane exception), message-
starvation-bound (sweep central drive+age, 900s=one cycle), message-lock-law
(per-target lock), message-retry-cap (+ sweep backstop), message-info-best-
effort / message-state-before-transport ("confirmed" wording).

Tests: tests/test_herdr.py 103/103 (+ pane-form-gated, per-target-lock
serialization, sweep-aging incl modal). Pre-existing 8 operator_control sweep
errors remain out of scope (git/linear fixtures, identical at base d5a07f7).
Lean frame: single age bound retained; 5-defers counter still recorded-not-
implemented. No remaining recorded-not-implemented holes from the review.
