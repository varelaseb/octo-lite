---
name: repo-health
description: Run the repo health pass, fired by hand, that files a repo's real architecture and cleanliness issues as ranked health tickets; and hold the one filing rule for review notes and findings.
---

# Repo Health

Be extremely concise. Sacrifice grammar for the sake of concision.
No em-dashes or en-dashes. Ever.

Spec: octo-lite `spec/domains/octo-lite.spec.html#health`.
The tracker is the only store of health issues: no file, report, or table holds them.

## Health ticket

One tracker ticket per real issue:

- Title: the issue. Body: the issue, its consequence, where it lives at the
  main commit checked, and each source that raised it (PR link, or
  `health pass at <main sha>`).
- Label: one category label of the `Health` group: `architecture`,
  `cleanliness`, `naming`, `duplication`, `test`, `docs`.
- Priority from rank, by consequence: high `-p 2` (will cause wrong behavior
  or block a change), medium `-p 3` (makes the next change there cost more:
  a duplicate, a dead store, a misleading name), low `-p 4` (costs only
  reading time).
- Unassigned, no parent, not started: no `-a`, `--parent`, `--state`, or
  `--start`, so it lands in the team's default state.

A consequence is what the issue will cost or break, named concretely, such as
"the next change to acceptance must edit four copies".

## Tracker

Write tickets, comments, and states only as
[consent](../octo-lite-github/SKILL.md#consent) `issues` allows; without it,
file nothing and name that as the blocker in your report.
Before any call: `set -a; . ~/.config/workbench/project.env; set +a`
(missing file: stop, report a blocker).

```sh
tid=$(linear api 'query($t:String!){team(id:$t){id}}' --variable t="$LINEAR_TEAM_ID" | jq -r .data.team.id)
# open health tickets
linear api 'query($t:ID!){issues(first:250,filter:{team:{id:{eq:$t}},labels:{some:{parent:{name:{eq:"Health"}}}},state:{type:{nin:["completed","canceled","duplicate"]}}}){nodes{identifier title description url}}}' --variable t="$tid"
# first use only, when the team has no Health label:
# linear api 'query($t:String!){team(id:$t){labels(filter:{name:{eq:"Health"}}){nodes{id}}}}' --variable t="$tid"
g=$(linear api 'mutation($t:String!){issueLabelCreate(input:{name:"Health",isGroup:true,teamId:$t}){issueLabel{id}}}' --variable t="$tid" | jq -r .data.issueLabelCreate.issueLabel.id)
for c in architecture cleanliness naming duplication test docs; do
  linear api 'mutation($t:String!,$g:String!,$n:String!){issueLabelCreate(input:{name:$n,parentId:$g,teamId:$t}){issueLabel{id}}}' --variable t="$tid" --variable g="$g" --variable n="$c" --silent
done
# file, comment, close
linear issue create --no-interactive -t <title> -l <category> -p <2|3|4> --description-file <f>
linear issue comment add <key> --body-file <f>
linear issue update <key> --state completed
```

## Filing rule

One rule for every filing: one PR's notes at lane close, many PRs' notes in
one batch, and a health pass's findings. Notes come tagged from each PR body
(`gh pr view <pr> --json url,body`), as the reviewer gave them.

1. Read every open health ticket, and main: `git fetch origin`; main is
   `origin/main`, checked at `git rev-parse --short origin/main`.
2. An open health ticket you find gone from main: comment naming that main
   commit and why the issue is gone, then close it as done.
3. Give each note or finding the first disposition that fits:

| The note or finding | Disposition |
| --- | --- |
| Names no consequence | Stays history; nothing is filed. |
| Names an issue main no longer has | Nothing is filed. |
| Names the same issue as an open health ticket | Comment on that ticket naming the new source; no second ticket. |
| Names the same issue as another note or finding in the batch | One new ticket for all of them, naming every source. |
| Any other | One new health ticket. |

Two notes name the same issue when one fix would remove both, whatever their
wording. One ticket per real issue, however many notes, PRs, or passes raise it.

## Pass

Fired by hand by the fleet operator, at its own call or when the human asks,
never on a timer: one fresh agent per pass, on the target's main checkout,
loading this skill. The fleet operator relays the pass's ticket keys to the
human who asked.

The pass agent changes no repository file (no pull, checkout, or commit) and
writes only health tickets. Read main in the checkout when its `HEAD` is
`origin/main`, else through `git show` and `git grep` at `origin/main`.

1. Read the target's instructions (`AGENTS.md`), its specs' modular
   boundaries, the open health tickets, and the code.
2. Look across the whole repository for architecture, cleanliness,
   best-practice, and trimming issues, a deletion first wherever one would do.
   Each finding names its category, consequence, where, and rank.
3. Check every open health ticket against main, closing each one main fixed
   (Filing rule step 2).
4. File findings by the Filing rule, source `health pass at <main sha>`: at
   most five new tickets per pass, highest rank first; the rest wait for a
   later pass that still finds them.
5. Result is the tickets, never a report: send the fleet operator one
   `herdr-say` message naming each ticket filed, commented on, or closed, by
   key, and no finding outside them. Then stop.
