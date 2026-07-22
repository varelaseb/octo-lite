# Runbook: herdr binary update with live handoff

Operator-gated. Binary + rewritten helpers must land TOGETHER when a release
breaks CLI grammar (protocol bump). Verified live 2026-07-22 (0.7.1 -> 0.7.5,
proto 14 -> 17, TUR-505 C4).

1. Preflight: rollback binary staged + sha-verified; helper branch FF-able onto
   the live branch; live worktree clean; operator window open.
2. Land helpers: git merge --ff-only <branch> && git push (seconds).
3. Update binary IMMEDIATELY after. GUARD: `herdr update --handoff` REFUSES to
   run from inside a herdr session ("run outside herdr after detaching").
   PERMANENT WORKAROUND (do not env-strip; use a genuinely detached process):
     systemd-run --user --wait --collect --unit herdr-update-window \
       --property=Type=oneshot --setenv="PATH=/usr/local/bin:/usr/bin:/bin" \
       /usr/local/bin/herdr update --handoff
4. Verify: herdr --version; herdr agent list (socket+proto); one multi-line
   herdr-say round-trip; one sweep cycle on the new code; timer alive.
5. Mixed window (helpers != binary) is degrade-safe by design (transports leave
   pending, drain retries) but keep it to seconds.
6. Rollback: restore staged binary, git revert helper commits, kill server so
   the old binary respawns it, re-verify (staged copy: /root/octo-lite-rollback/ROLLBACK.md).
7. Soak: rollback stays staged 24h post-handoff; any transport anomaly =
   report immediately + one-command rollback.
