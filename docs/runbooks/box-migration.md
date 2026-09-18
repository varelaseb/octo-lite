# Standing up a fresh operator box

Surveyed from the live box 2026-09-17. Versions are what was actually running,
not minimums.

## Access

New key for this migration, segregated from the existing `id_ed25519`
(`codex-hardening-2026-08-19`, minted for something else):

```
/root/.ssh/id_ed25519_migration        # private, 0600
/root/.ssh/id_ed25519_migration.pub    # add to the new box's authorized_keys
SHA256:R8ETe8BBL1MP9LT4lHleLchPoRli1CdwdHfYgAyj1QQ
```

## Install

| Thing | Version here | Note |
|---|---|---|
| herdr | 0.9.0 | `~/.local/bin/herdr`. Config and sessions in `~/.config/herdr` |
| moshi-hook | 0.3.25 | Also provides `moshi`. Needs `pair` then `install` then `serve` |
| codex CLI | 0.154.0 | |
| claude (Claude Code) | 2.1.274 | |
| linear CLI | 2.0.0 | `~/.local/bin/linear` |
| gh | 2.95.0 | needs `gh auth login`, scopes: repo, workflow, read:org, gist |
| gcloud SDK | 574.0.0 | daily user auth for ad-hoc; privileged automation stays on WIF |
| node | 20.19.2 | npm 9.2.0 |
| python3 | 3.13.5 | |
| ffmpeg | 7.1.5 | evidence video posters need it |
| jq | 1.7 | review-spool emitters prefer it, fall back to python3 |
| cloudflared | 2026.7.1 | ad-hoc tunnels only, nothing standing |
| psql | 18.4 | present but hangs against prod; use node `pg` for prod reads |

**Missing here and worth deciding on rather than copying:**

- `skillfile` is **not on PATH**, yet octo-lite's `Skillfile` and `Skillfile.lock`
  depend on it to materialize `agents/skills`. Skills currently only stay current
  because someone re-materializes by hand. Install it from
  `github.com/eljulians/skillfile` on the new box.
- `pnpm` is absent even though Turbo declares it. It is presumably reached
  through corepack or npx; confirm before assuming a global install.

## Model defaults

octo-lite's role contracts pin no model. Each CLI's own default therefore runs
every spawned role, so these two settings are the fleet's model choice
(operator, 2026-09-18):

| CLI | Setting | Value |
|---|---|---|
| Claude Code | `~/.claude/settings.json` `model` | `opus[1m]` |
| Claude Code | `~/.claude/settings.json` `effortLevel` | `xhigh` |
| Codex | `~/.codex/config.toml` `model` | `gpt-6-astra` |
| Codex | `~/.codex/config.toml` `model_reasoning_effort` | `xhigh` |
| Codex | `~/.codex/config.toml` `service_tier` | `fast` |

`gpt-6-astra` supersedes the `gpt-5.6-luna` / `gpt-5.6-sol` worker split from the
pinned-model era; that split no longer exists.

A `modelSettings` entry pinning `claude-fable-5-1` to `high` effort is
deliberate and unrelated to roles. It applies only when Fable is selected by
hand for operator or adversarial shaping work.

## Configure, do not install

**cliproxyapi is a remote gateway, not a local service.** Nothing to run. Codex
reaches it through `~/.codex/config.toml`:

```
model_provider = "cliproxyapi"
[model_providers.cliproxyapi]
base_url = "https://cliproxy.topicfinder.ai/v1"
env_key  = "CLIPROXYAPI_API_KEY"
wire_api = "responses"
```

`CLIPROXYAPI_API_KEY` is referenced from `~/.bashrc`, `~/.codex/.env`, and four
files under `~/.config/cliproxyapi/` (`client.env`, `systemd.env`, `client.sh`,
`claude-api-key-helper`). Carry that directory; never rotate the gateway from a
box.

## Carry

- `~/.ssh/` keys and `config`
- `~/.codex/` - `auth.json` (the ChatGPT account remote control follows),
  `config.toml`, `.env`
- `~/.claude/` - `CLAUDE.md`, `settings`, `plugins`, and
  `projects/-root/memory/` if the new box should remember anything
- `~/.config/cliproxyapi/`
- `~/.config/herdr/` - sessions, `plugins.json`
- `~/.config/moshi/host-pairings.json`
- `/root/.linear.env` (Turbo, TUR) **and** `/root/.linear-aa.env`
  (AnnotateAnything, ANN). Two workspaces, not interchangeable; the ambient
  `LINEAR_API_KEY` is Turbo's
- `/root/codex-uploads/.evidence-review-token`
- `/root/octo-lite`, then run `scripts/install-octo-lite` to re-link skills into
  `~/.claude` and `~/.codex`, and `--check` to verify the mirror invariant
- `/root/herdr-plugins/tabherd` (0.4.1) plus its entry in `plugins.json`

## Box shape

- **Swap.** The 8 GB box OOMs under headless-Chrome QA. This box carries ~11 GB
  of swap. Re-add it and verify; a rebuild loses it silently and the failure
  looks like random agent deaths.
- Local Postgres is running here on 5433 and other ports. Confirm whether
  anything still needs it before reprovisioning.

## Do not carry

Around 500 Turbo-Outreach worktrees and review checkouts under `/root`, plus
`/root/bb-upstream` (329 MB reference clone). All re-derivable from their
remotes. Clone fresh and let worktrees regenerate.
