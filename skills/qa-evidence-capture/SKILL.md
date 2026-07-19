---
name: qa-evidence-capture
description: Capture durable browser QA evidence for web app review requests. Use when the user asks for QA evidence, browser proof, screenshots, video recordings, human-QA artifacts, or asks to show what an implemented slice does in a browser.
---

# QA evidence capture

## Communication Style

Be extremely concise. Sacrifice grammar for the sake of concision.
No em-dashes or en-dashes. Ever.

Canonical rules live in `spec/domains/operating-model.spec.html`, section "QA
and evidence". This skill is the qa-capture pass procedure only.

## Plan before capture

Record a small per-criterion evidence plan naming the minimum honest proof set
before capturing anything. Bind it to the exact reviewed HEAD.

## Choose the proof format

- Screenshots are the default proof for stable states. One image or a concise
  ordered group may prove a state or sequence when each has a distinct purpose.
- Video only when motion, sequence, timing, media playback, or interaction
  cannot be proved honestly with still images.
- Never capture both formats for the same criterion unless each proves a
  distinct criterion or risk.
- Backend-only work skips browser capture, screenshots, video, and app boot
  entirely unless the contract itself requires them; assemble the nonvisual
  packet instead.

## Capture

1. Confirm the exact HEAD matches the clear code-review verdict.
2. Exercise the declared user flow in the actual review environment at the
   required viewports.
3. Name each artifact by observed state, not by step number.
4. Write one evidence manifest: app identity, runtime, HEAD, viewports,
   fixtures, artifacts, and per-criterion rationale.
5. Read back every artifact and the manifest from their saved or served
   location before reporting done. An unreadable artifact is not evidence.

## Backend-only packet

Assemble the clear code-review verdict, exact HEAD, affected story IDs, spec
criteria, real unskipped validation output, and contract-check output into one
nonvisual packet. Do not boot a browser or fabricate a screenshot.

## Never

Decide product acceptance, hide a broken state, substitute logs for pixels,
capture a stale HEAD, or record video by habit.
