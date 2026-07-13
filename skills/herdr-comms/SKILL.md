---
name: herdr-comms
description: Modal-safe herdr messaging and clean session spawning. Use whenever sending a message to another herdr agent or pane (use herdr-say, never raw agent send / pane run), spawning an orchestrator session in a new tab (use herdr-spawn), or reading another session's pane.
---

# herdr comms protocol

Operator-mandated (2026-07-13) after real incidents: raw message injection
submitted half-typed text and pressed Enter into open question modals —
selecting answers on the human's behalf; spawned tabs came up split in half;
fresh sessions stalled silently on the folder-trust dialog until a human
pressed trust manually. These rules bind every agent that talks through
herdr — meta-operators, stream orchestrators, and ad-hoc sessions alike.

## Install

The helpers ship in this skill's `assets/` directory and must be on PATH:

    install -m 0755 <this-skill-dir>/assets/herdr-say  ~/.local/bin/herdr-say
    install -m 0755 <this-skill-dir>/assets/herdr-spawn ~/.local/bin/herdr-spawn

## Messaging: ALWAYS `herdr-say`, never raw send/run

    herdr-say <agent-name|pane-id> "<one-line message>"

- `herdr agent send` pastes text but does NOT submit to an idle REPL, and
  `herdr pane run <pane> ""` presses Enter. In the wrong order the text sits
  unsubmitted; while the target shows a question/permission/trust dialog,
  the Enter SELECTS AN OPTION ON THE HUMAN'S BEHALF. Never hand-roll this.
- `herdr-say` enforces paste → settle → Enter, refuses to inject while a
  dialog is visible (retries up to 2 min), then queues the message to
  `~/.local/state/herdr-inbox/<target>/` and exits 75.
- Exit 75 = QUEUED, not failed — do not retry-spam; the recipient reads its
  inbox on its next wake. Exit 0 = delivered.
- Message discipline: ONE line, no single quotes, no multi-line blobs.
  Details live in durable artifacts (tracker issue, PR, brief files).
- On every wake, check `~/.local/state/herdr-inbox/<your-agent-name>/`;
  process each file then delete it.

## Spawning a session in a new tab: ALWAYS `herdr-spawn`

    herdr-spawn --workspace <ws> --name <agent-name> [--label "<tab label>"] \
                [--cwd <dir>] -- <argv...>

Fixes three spawn bugs at once — never hand-roll the sequence:

- SPLIT TAB: `herdr tab create` ships a root shell pane and
  `herdr agent start --tab` adds a second one; the script closes the root
  pane so the tab ends single-pane.
- TRUST STALL: fresh sessions sit silently on the folder-trust dialog
  ("Quick safety check … Yes, I trust this folder") until a human presses
  Enter. The script watches the pane for up to 60s and auto-accepts it.
- WRONG CWD: `herdr agent start` does NOT inherit the tab's cwd; the script
  passes `--cwd` explicitly.

Exit 0 with `startup=running` = REPL confirmed. Exit 2 with
`startup=unverified` = read the pane yourself; do not assume it started.

## Tab naming

Work tabs: `<ISSUE-KEY>(<PR#>) topic` once issue/PR exist; keep labels in
sync via `herdr tab rename` as they attach. Non-issue tabs stay descriptive.

## Gotchas the scripts encode (for anyone editing them)

- `herdr pane read` outputs RAW TEXT; `herdr agent read` outputs JSON.
  Piping pane read into jq silently breaks dialog detection.
- The trust prompt's text is "Quick safety check" / "trust this folder" —
  older "Do you trust" greps miss it.
- A bare Enter (`herdr pane run <pane> ""`) selects the trust dialog's
  default ("Yes, I trust this folder").
