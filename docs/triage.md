# Issue & PR triage system

This document describes how IngeTrazo triages incoming issues and pull
requests, who does what, and how work flows from "someone opened an issue"
to "it shipped". It's the reference for the roles, labels, and Projects
boards introduced alongside it.

## Roles

### Reviewer
Triages new issues as they arrive: checks for duplicates, splits
multi-feature issues into sub-issues, links related issues, and cleans up
low-quality reports in place (fixes formatting, fills in missing fields,
asks for repro steps). A Reviewer does **not** set priority or decide
whether something gets worked on — that's the Project Lead's call.

Granted via **GitHub Projects' own "Write" access** on the Triage project,
which is independent of repository role — see GitHub's docs on [project
permissions vs. repository permissions]. This lets trusted
non-collaborators triage without being given write access to the repo
itself. A Reviewer who also needs to edit issue titles/bodies directly (not
just move cards and add labels) additionally needs the repo's **Triage**
role, GitHub's lightweight built-in role for exactly this.

### Project Lead (the maintainer today)
Sets **Priority**, decides the **disposition** (Close / Main Development /
Extension), and assigns developers to issues once a developer has requested
assignment. The Lead is the only role that moves an issue out of the Triage
project and into Main Development or Extension.

### Developers (including non-collaborators)
Anyone can request to work on an issue by commenting **"I'd like to work on
this"** (or similar). The Lead then assigns them — GitHub allows assigning
any user who has commented on a public-repo issue, even if they have no
repo role at all, so no write access is needed just to pick up work.

## Label taxonomy

Labels are defined in [`.github/labels.yml`](../.github/labels.yml) and
kept in sync with the repo by `.github/workflows/sync-labels.yml`. Edit
that file and open a PR rather than editing labels in the GitHub UI.

- **Status** — where an issue sits in the triage pipeline:
  - `status: needs-triage` — new issue, not yet looked at (applied
    automatically by the issue templates).
  - `status: reviewed` — a Reviewer has triaged it (deduped, split if
    needed); awaiting the Lead's priority/disposition call.
  - `status: blocked` — blocked on another issue, a decision, or an
    external dependency.
  - `needs-info` / `needs-decision` (pre-existing default labels) also
    belong conceptually to this group: waiting on the reporter, or waiting
    on a maintainer decision, respectively.
- **Priority** — set by the Project Lead once an issue is reviewed:
  `priority: critical`, `priority: high`, `priority: medium`,
  `priority: low`.
- **Area** — which module the issue touches, matching the breakdown in
  [`docs/architecture.md`](architecture.md): `area: core`, `area: views`,
  `area: tools`, `area: plugins`, `area: georef`, `area: formats`,
  `area: i18n`.
- Existing default labels (`bug`, `documentation`, `duplicate`,
  `enhancement`, `good first issue`, `help wanted`, `invalid`,
  `question`, `wontfix`) keep their current meaning and are used alongside
  the groups above.

## The three Projects

Three GitHub Projects (v2) boards drive the workflow. Each has its own
**Status** field with values specific to what happens on that board.

| Project | Purpose | Status values |
|---|---|---|
| **Triage** | Every new issue lands here first. | New → In Review → Reviewed → (Duplicate / Invalid / Needs-Info) |
| **Main Development** | Issues the Lead has prioritized for the core roadmap. | Backlog → Planned → In Progress → In Review → Done |
| **Extension** | Lower-priority / nice-to-have work, plugins, experiments. | Backlog → Planned → In Progress → In Review → Done |

New issues are added to **Triage** automatically by
`.github/workflows/add-to-triage-project.yml`. Moving an issue from Triage
into Main Development or Extension (and setting its initial Backlog status
there) is a manual step the Lead takes when setting priority/disposition.

> **Setup note:** the Triage project URL and the Main Development/Extension
> project URLs are placeholders (`REPLACE_ME`) until the maintainer creates
> the boards. See the "Follow-ups" note in the PR that introduced this
> system.

## Handling issues that bundle multiple features

If an issue describes more than one distinct feature or fix, a Reviewer
splits it into **GitHub sub-issues** — one sub-issue per discrete piece of
work — and keeps the original issue open as the **parent/tracker**. The
parent issue's body should link to each sub-issue (GitHub renders a
progress checklist automatically for linked sub-issues). Each sub-issue
gets its own area/priority labels and can be assigned independently.

## Handling related, duplicate, and blocked issues

- **True duplicates**: apply the `duplicate` label and close the issue with
  a comment linking the canonical issue (e.g. "Duplicate of #123").
- **Dependencies**: use GitHub's native **"Blocked by #X"** issue link
  (and/or the `status: blocked` label) when an issue literally cannot be
  started until another is resolved.
- **Loose relations**: mention **"Relates to #X"** in the issue body or a
  comment when two issues are related but neither blocks the other — this
  keeps a reference without implying a hard dependency.

## How developers request assignment

1. A developer comments on an open issue, e.g. *"I'd like to work on
   this."*
2. The Project Lead reviews the comment and assigns the issue to them
   (GitHub permits this for any user who has commented, even without repo
   access).
3. The Lead moves the issue's Status to **In Progress** on its project
   board.

Issues labeled `good first issue` are the best entry point for first-time
contributors — see [CONTRIBUTING.md](../CONTRIBUTING.md).

## End-to-end flow

1. **New issue** opened (via a template) → labeled `status: needs-triage`
   and `bug`/`enhancement` automatically → added to the **Triage** project
   with Status **New**.
2. A **Reviewer** picks it up → Status moves to **In Review** → they check
   for duplicates, split multi-feature issues into sub-issues, link related
   issues, and clean up the report.
3. Reviewer finishes → Status moves to **Reviewed**, label
   `status: reviewed` applied (or the issue is closed as
   Duplicate/Invalid, or marked `needs-info`/`needs-decision`).
4. The **Project Lead** sets a `priority:*` label and decides disposition:
   Close, or add to **Main Development**, or add to **Extension**.
5. The issue is added to the chosen project with Status **Backlog**.
6. A **developer** comments interest → the Lead **assigns** them → Status
   moves to **Planned** then **In Progress** as work starts.
7. A PR is opened and linked → Status moves to **In Review**.
8. PR merges → Status moves to **Done**.

[project permissions vs. repository permissions]: https://docs.github.com/en/issues/planning-and-tracking-with-projects/managing-your-project/managing-access-to-your-projects
