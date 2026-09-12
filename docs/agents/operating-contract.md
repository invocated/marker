# Agent operating contract

## Startup

1. Read `AGENTS.md` or the native instruction file for the current agent.
2. On the first clone on this machine, run the first-clone sequence in
   `docs/agents/issue-tracker.md` — it installs the toolchain, starts the
   clone-local server, rebuilds the database from the git remote, and checks
   that reads and writes both work. `bd prime` alone exits 0 on a clone that
   has no database, so it proves nothing on its own.
3. In every later session, `mise exec -- bd dolt pull` then
   `mise exec -- bd prime`.
4. Read `docs/agents/domain.md` and `docs/agents/issue-tracker.md` before
   changing the graph.
5. Use one stable, unique actor ID per independent worker process.

## Authority

- Beads owns work graph state only.
- Files and external artifacts own produced content.
- ADRs and research records own durable decisions and evidence.
- Any orientation summary is derived.
- Never create `PROJECT_STATE.md` as an authority.

## Concurrency discipline

Atomic claims are proven; ordinary issue fields use silent last-writer-wins
behavior.

- Claim before changing status, title, description, design, notes,
  assignee, or dependencies on executable work.
- After a failed claim, refresh and choose another item.
- Only the current assignee mutates ordinary fields on that item.
- Use comments for routine concurrent progress, evidence links, review
  notes, and map decision-index entries.
- Treat Dolt history as recovery evidence, not as conflict prevention.
- Human review owns proposal promotion, map destination changes,
  abandoned-claim release, schema migration, and destructive recovery.

These rules reduce the exposed stale-write surface; they do not turn
general fields into compare-and-swap operations.

Claims are atomic per machine only. Cross-machine consistency is eventual,
via human-authorized `bd dolt push` / `bd dolt pull` through the git
remote: pull when you sit down at a machine, push when you finish.

## Scope discovery

A worker may record newly surfaced work only as a deferred `proposed`
child linked by `discovered-from`. Recording a proposal is not approval to
execute it. Human promotion must clear both the defer date and label.

## Abandoned claims

Beads has no claim lease or automatic expiration. `bd stale` accepts a
minimum threshold of one day.

1. Inspect `bd stale --status in_progress --days 1` and the item's
   comments/artifacts.
2. Confirm the original worker is no longer active.
3. A human records the recovery reason and runs:

```text
mise exec -- bd --actor human-<name> update <id> --status open --assignee= --append-notes <recovery-reason>
```

4. Confirm the item reappears in the executable frontier.

For a suspected crash less than one day old, inspect
`bd list --status in_progress` manually. Never assume process exit
automatically released the claim.

## Session handoff

- Add comments containing concise progress and artifact pointers.
- Close only work whose acceptance criteria are met.
- Leave blocked or unfinished work in Beads with enough context to resume.
- Commit, push, and synchronize Dolt remotes as ordinary work; the repo owner
  reads the result rather than gating each step. Work lands on `main`, often,
  and the repo's tests are what gate it — never merge red.
- Promoting proposed work and recovering an abandoned claim still belong to a
  human, as does anything that rewrites published history or deletes data.

## Naming an issue in prose written for a person

Inside the tracker the key is the address. Issue titles, comments, and commit
trailers (`Closes <id>`) are correct as keys alone.

In prose written for a person — chat, a handoff, a pull-request body, the body
of a commit message — state the problem and what it costs this system, then
carry the key as a reference:

```text
the batch's payload check is skipped whenever the batch runs in rehearsal
mode, so the rehearsal that exists to prove the check works never exercises
it (<id>)

CLAUDE.md and docs/agents/domain.md both tell agents the glossary and the
decision records do not exist, so an agent skips domain documents that are
now there (<id>)
```

Never the key on its own, and never a list of bare keys. A key names an issue
to the tool; it does not describe one to a reader.

A short name for the issue is not a description either. "The dry-run gate
hole" and "two documents that claim CONTEXT.md does not exist" fail the same
way the bare key does: the reader cannot use either without opening something
else. Write the sentence a reader who has never seen the tracker could act on.

- First mention carries the problem statement; later mentions in the same
  passage may use the key alone.
- Where this repo's glossary defines a term, that term is available, with the
  glossary as its source.
- Beads keys carry no link. Where this repo also reports on an external
  tracker that has browse URLs, its own output conventions govern those keys.

This is the tracker-specific case of the plain-language instructions each
agent already loads (`~/.claude/output-styles/speak-plainly.md`,
`~/.codex/AGENTS.md`); it does not restate them.
