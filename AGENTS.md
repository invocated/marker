# Agent instructions for Marker

## Agent skills

Beads is the sole tracker of record for invocated/marker. The permanent issue prefix is `marker`. Run Beads commands through `mise exec -- bd` using the versions in `mise.toml`.

- Read `docs/agents/issue-tracker.md` for issue operations and first-clone setup.
- Read `docs/agents/operating-contract.md` for ownership, proposals, and session handoff.
- Read `docs/agents/domain.md` for domain documentation conventions. Marker contains one Python package; use root domain documentation when present.
- Read `docs/agents/triage-labels.md` for triage label meanings.

Complete the first-clone checks before working on issues. For an initialized checkout, run `mise exec -- bd prime` to load Beads context.

The first database publication and the commit of these setup files require user approval under the setup-work-graph skill. User instructions take precedence over generated Beads guidance.

Beads stores issues in a local Dolt server and synchronizes through `refs/dolt/data` on the fork's Git remote. See the [Beads sync documentation](https://github.com/gastownhall/beads/blob/main/docs/core-concepts/sync-concepts.md).
