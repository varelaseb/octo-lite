---
name: repo-health
description: Run the repo health pass, fired by hand, that files a repo's real architecture and cleanliness issues as ranked health tickets; and file review notes and findings by the one filing rule.
---

# Repo Health

Be extremely concise. Sacrifice grammar for the sake of concision.
No em-dashes or en-dashes. Ever.

Spec: octo-lite [`spec/domains/octo-lite.spec.html#health`](https://github.com/varelaseb/octo-lite/blob/main/spec/domains/octo-lite.spec.html#health).
The tracker is the only store of health issues: no file, report, or table holds them.

## Health ticket

One tracker ticket per real issue:

- Title: the issue. Body: the issue, its consequence, where it lives at the
  main commit checked, and each source that raised it (PR link, or
  `health pass at <main sha>`).
- Label: one category label of the `Health` group: `architecture`,
  `cleanliness`, `naming`, `duplication`, `test`, `docs`.
- Priority from rank, by consequence: high `2` (will cause wrong behavior
  or block a change), medium `3` (makes the next change there cost more:
  a duplicate, a dead store, a misleading name), low `4` (costs only
  reading time).
- Unassigned, no parent, not started: no `assigneeId`, `parentId`, or
  `stateId`, so it lands in the team's default state.

A consequence is what the issue will cost or break, named concretely, such as
"the next change to acceptance must edit four copies".

## Tracker

Write tickets, comments, and states only as
[consent](../octo-lite-github/SKILL.md#consent) `issues` allows; without it,
file nothing and name that as the blocker in your report.

```sh
tid=$(linear api 'query($t:String!){team(id:$t){id}}' --variable t="$(linear team id)" | jq -r .data.team.id)
# open health tickets
linear api 'query($t:ID!){issues(first:250,filter:{team:{id:{eq:$t}},labels:{some:{parent:{name:{eq:"Health"}}}},state:{type:{nin:["completed","canceled","duplicate"]}}}){nodes{identifier title description url}}}' --variable t="$tid"
# Health label group, created only when the team has none
if [ -z "$(linear api 'query($t:String!){team(id:$t){labels(filter:{name:{eq:"Health"}}){nodes{id}}}}' --variable t="$tid" | jq -r '.data.team.labels.nodes[0].id // empty')" ]; then
  g=$(linear api 'mutation($t:String!){issueLabelCreate(input:{name:"Health",isGroup:true,teamId:$t}){issueLabel{id}}}' --variable t="$tid" | jq -r .data.issueLabelCreate.issueLabel.id)
  for c in architecture cleanliness naming duplication test docs; do
    linear api 'mutation($t:String!,$g:String!,$n:String!){issueLabelCreate(input:{name:$n,parentId:$g,teamId:$t}){issueLabel{id}}}' --variable t="$tid" --variable g="$g" --variable n="$c" --silent
  done
fi
# file: the category label resolved inside the Health group, never by bare
# name, which can pick a workspace or team `docs` or `test` label instead
l=$(linear api 'query($t:String!,$n:String!){team(id:$t){labels(filter:{name:{eq:$n},parent:{name:{eq:"Health"}}}){nodes{id}}}}' --variable t="$tid" --variable n=<category> | jq -r '.data.team.labels.nodes[0].id')
linear api 'mutation($t:String!,$l:String!,$ti:String!,$p:Int!,$d:String!){issueCreate(input:{teamId:$t,labelIds:[$l],title:$ti,priority:$p,description:$d}){issue{identifier url}}}' --variable t="$tid" --variable l="$l" --variable ti=<title> --variable p=<2|3|4> --variable d=@<f>
# comment, close
linear issue comment add <key> --body-file <f>
linear issue update <key> --state completed
```

## Filing rule

The rule is spec [`#health-filing`](https://github.com/varelaseb/octo-lite/blob/main/spec/domains/octo-lite.spec.html#health-filing): what each note or finding gets, and what a
filing checks against main. This skill holds only how:

1. Read each PR's notes, tagged as given, under `## Review notes` in its body:
   `gh pr view <pr> --json url,body`.
2. Read the open health tickets (Tracker), and main: `git fetch origin`; main
   is `origin/main`, checked at `git rev-parse --short origin/main`.
3. File, or comment naming the new source, with the Tracker commands. Each
   source, one PR or one pass, files at most 5 new tickets, highest rank
   first; the rest stay history.

## Pass

The pass is spec [`#health-pass`](https://github.com/varelaseb/octo-lite/blob/main/spec/domains/octo-lite.spec.html#health-pass): who fires it, what it reads, looks for,
checks, and files, and its one message. This skill holds only how:

- Read main without changing a repository file (no pull, checkout, or
  commit): in the checkout when its `HEAD` is `origin/main`, else through
  `git show` and `git grep` at `origin/main`.
- Close each open health ticket main fixed with the Tracker comment and
  close commands.
- File findings by the Filing rule, source `health pass at <main sha>`.
- Send the fleet operator the one message with `herdr-say`: each ticket key
  filed, commented on, or closed. Then stop.
