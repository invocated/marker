# Beads issue-tracker mapping

Beads (`bd`) in external Dolt server mode is the only work tracker in this
repository. The commands below are this repo's implementation of
Wayfinder's tracker contract. GitHub Issues are frozen as of 2026-09-12:
readable forever, never written again; anything still relevant re-enters as
a proposed bead.

Every command goes through `mise exec -- bd ...`, in every shell. Mise owns
the pinned Beads and Dolt binaries; a bare `bd` is whatever that machine
happens to have, and on a new machine it is nothing at all. Mutating commands
pass a stable actor with `--actor <stable-agent-id>` when the surrounding
agent environment does not already provide one.

## First clone on a machine

A clone arrives with the tracked configuration and no database. `bd prime`
exits 0 on such a clone without saying so, so run this sequence and read its
output rather than trusting the exit codes:

```text
mise install
chmod 700 .beads
mise exec -- bd dolt start
mise exec -- bd bootstrap --yes
mise exec -- bd doctor --server --json
mise exec -- bd config list | grep issue_prefix
mise exec -- bd stats
```

`bd bootstrap` reconstructs the database from `refs/dolt/data` on the git
remote; it is non-destructive and never deletes issues. Three things have to
be true before the clone is usable:

- `bd doctor` reports `overall_ok` true, with `Database Exists` ok.
- `bd config list` shows an `issue_prefix`. Without it every write fails with
  `database not initialized: issue_prefix config is missing`, however healthy
  the reads look. The prefix reaches a clone only if the publishing machine
  committed and pushed it, so a missing prefix is a defect on that machine,
  not here — repair it there (`setup-work-graph`, Section 9).
- `bd stats` reports the issue count this repo actually has, not zero.

Then prove a write, locally, and remove it again:

```text
mise exec -- bd create --type task --title "clone write check"
mise exec -- bd delete <new-id> --force
```

Run `bd init` on a clone only when it has no database at all. Once anything
has started the clone's server — `bd prime` does, so the first agent session
does — `bd init` refuses for good, and `bd bootstrap` is the only way in.

## Every session after that

```text
mise exec -- bd dolt pull      # when you sit down at a machine
mise exec -- bd prime
mise exec -- bd dolt push      # when you finish; human-authorized
```

Sync is machine-local server plus git remote, and both directions are
human-authorized. Claims are atomic per machine only.

## Wayfinding operations

### Create a map

Human/planner operation:

```text
mise exec -- bd create --type epic --title <destination> --labels wayfinder:map --description <destination-notes-fog-and-out-of-scope>
```

The map description is an initial framing record. Workers do not
concurrently rewrite it. Resolved child decisions are appended to the map
as comments, keeping the shared update path append-only.

### Create a committed child

Human/planner operation:

```text
mise exec -- bd create --parent <map-id> --type task --title <bounded-question-or-task> --labels wayfinder:research
```

Choose one role label: `wayfinder:research`, `wayfinder:prototype`,
`wayfinder:grilling`, or `wayfinder:task`. Use Beads `decision` type when
the child exists to record a durable decision.

### Create worker-discovered proposed work

Worker operation:

```text
mise exec -- bd create --parent <map-id> --type task --title <possible-work> --labels proposed --labels wayfinder:task --defer 9999-12-31 --deps discovered-from:<source-id>
```

Both controls are mandatory: the future defer date excludes the item from
bare `bd ready`, and the label permits audit and defense-in-depth
exclusion. A worker must not remove either control.

### Promote proposed work

Human-only operation:

```text
mise exec -- bd --actor human-<name> update <id> --defer= --remove-label proposed --append-notes <promotion-reason>
```

Use the single token `--defer=` so every supported shell passes the empty
value to Beads consistently.

### Add blocking structure

```text
mise exec -- bd dep add <blocked-child-id> <prerequisite-id> --type blocks
```

Use `discovered-from` only for provenance; it does not block readiness.

### Query the executable frontier

```text
mise exec -- bd ready --parent <map-id> --unassigned --exclude-label proposed --exclude-type epic
```

The explicit label exclusion is defense in depth. A correctly formed
proposal is already omitted because it is deferred.

### Claim

```text
mise exec -- bd update <child-id> --claim
```

Claim is the first write. If it fails because another actor won, do not
edit the item; refresh the frontier. Only the assignee changes ordinary
fields on an in-progress item.

### Record progress and evidence

```text
mise exec -- bd comments add <child-id> <progress-or-artifact-reference>
```

Comments are the approved concurrent progress channel. Link authoritative
files or external artifacts; do not paste their entire content into Beads.

### Release owned work

The current assignee may release routine work without human review after
recording why:

```text
mise exec -- bd comments add <child-id> <release-reason-and-resume-context>
mise exec -- bd update <child-id> --status open --assignee=
```

Use the single-token `--assignee=` form in every shell. Releasing another
actor's claim is abandoned-claim recovery and remains human-only.

### Record a blocker

The claimant may connect an existing prerequisite, record context, and
return its item to the dependency-controlled frontier:

```text
mise exec -- bd comments add <child-id> <blocker-and-evidence>
mise exec -- bd dep add <child-id> <prerequisite-id> --type blocks
mise exec -- bd update <child-id> --status open --assignee=
```

Do not create a committed prerequisite merely to satisfy this sequence.
Newly discovered prerequisite scope is proposed first and requires
promotion before it can become committed blocking work.

### Mark ready for review

The claimant keeps ownership and uses a conventional label plus comment:

```text
mise exec -- bd comments add <child-id> <review-scope-and-artifact-reference>
mise exec -- bd update <child-id> --add-label ready-for-review
```

Reviewers query `bd list --status in_progress --label ready-for-review`
and add comments. The claimant or authorized reviewer removes the label
and closes or resumes the item according to its acceptance criteria.

### Resolve

```text
mise exec -- bd comments add <child-id> <answer-decision-and-evidence-pointer>
mise exec -- bd comments add <map-id> <low-resolution-child-result-and-pointer>
mise exec -- bd close <child-id> --reason <completion-summary>
mise exec -- bd ready --parent <map-id> --unassigned --exclude-label proposed --exclude-type epic
```

The child comment and linked artifact carry the detailed resolution. The
append-only map comment is the low-resolution decisions-so-far index.
Closing a prerequisite is what unblocks its dependents.

### Resume

```text
mise exec -- bd show <map-id>
mise exec -- bd list --parent <map-id> --status in_progress
mise exec -- bd ready --parent <map-id> --unassigned --exclude-label proposed --exclude-type epic
mise exec -- bd list --parent <map-id> --status deferred --label proposed
```

The graph is the resumable state. Do not synthesize an authoritative
`PROJECT_STATE.md`.

## Repository

This mapping applies to invocated/marker. The issue prefix is marker. GitHub Issues are disabled on this fork. The upstream datalab-to/marker issue tracker is outside this policy.

On Windows, replace chmod with an owner-only directory ACL and use Select-String issue_prefix instead of grep. An empty database is expected at initial setup.
