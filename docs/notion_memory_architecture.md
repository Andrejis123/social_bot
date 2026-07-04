# Notion + memory architecture

Working draft. Once finalized, copy into the Notion "Architecture Document" page
(`391f3868-b444-8003-9e79-c44b300b7a5d`) so it is visible from any account.

## Purpose

A cross-account, multi-project workflow. Goal: a global morning-brief skill that
reminds me where I left off on each project (some untouched for a week), plus
per-project hub pages I can open to see everything for one project in one place.

## Core model

- DBs hold the data. Pages are the human view. A per-project page embeds linked
  views of the DBs, filtered to that project.
- Three GLOBAL databases, each filtered by a `Project` property: Todo List,
  Quick Questions, Journals.
- Skills read the DBs via API, never the pages. Pages are hand-built dashboards;
  a skill must not depend on page layout.

## The three databases

### Todo List (existing)
Global task list. Filter by Project / Priority / Due / Status. Lives under the
"To Do List" page. ID `31ff3868-b444-8054-aa56-e3f8db6d8720`.

### Quick Questions (existing)
Open questions per project, answered at session start. Todo-like, so it can stay
alongside Todo List. ID `38cf3868-b444-8171-98b7-fb79d538b7e2`.

### Journals (new)
Boiled-down mirror of each project's in-repo session journal. One row appended
per session (full history). Sits in the Private section.
ID `391f3868-b444-8123-be92-ddadd5dcf015`.

Properties: Entry (title), Project (select), Date, Session # (number),
Status (select), Summary (rich_text, 2000-char cap).

Status values: Ongoing / Finished / Postponed / Dormant. The morning brief reads
each project's LATEST row; its Status decides whether to show the project and how
to label it (skip Finished, show "Postponed until Y", etc.). No separate Projects
DB is needed.

The in-repo journal file stays for fast local context (last 4 sessions, FIFO).
Notion Journals is the portable long archive.

## Per-project page (human hub)

One page per project, in Private. Holds: description, repo pointer if any (not
every project is a repo, e.g. personal / work placement), and linked views of
Journals + Todo List + Quick Questions, each filtered to that project.

Build one template page in the UI, then duplicate it per project and change the
filters. Linked views also support write-back: a todo can be added straight from
the project page and it lands in the global Todo List tagged to that project.

## Who updates what

- session-handoff writes: in-repo project memory, Notion todos, and one new
  Journals row. These must be atomic so the local journal and Notion do not drift.
- morning-brief reads: current todos plus the latest Journals row per project.
  Projects are discovered from distinct `Project` values in the DBs; no registry
  needed.

## Notion API constraints (learned)

- The API cannot create linked views; they are UI-only. Add them by hand, or
  duplicate a template page.
- The API cannot move a database between parents. Move DBs by dragging in the
  sidebar. Pages can be moved via API or drag.
- A linked view works across the whole workspace regardless of where its source
  DB lives, so placement is cosmetic for function (tidiness only).

## Build state (2026-07-02)

- Journals DB `391f3868-b444-8123-be92-ddadd5dcf015` (move into Private).
- Social Bot per-project page `391f3868-b444-816a-8153-d9d9703735c4` (in Private;
  linked views tested, work plus write-back confirmed).
- Seed Journals row s17 kept; ad-hoc UI test row deleted.

## Next

1. Wire the session-handoff skill to append a Journals row per session.
2. Later: global project-initialisation document plus session-start /
   session-handoff skill templates, so a new project can create its hub page and
   orient itself in this architecture.
