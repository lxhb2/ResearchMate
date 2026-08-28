---
name: nature-response
description: "草稿，审计，或修改自然风格的修改函包：逐点审查者分开的回复函，反驳函，修订封面信，LaTeX cover/response模板，以及红色标记的修订手稿节录. 保持相互盲目审查者隔离，因此没有审查者与提交答复会揭示另一个审查者的评论，编号，建议，或作者的回应。"
metadata:
  github_source: https://github.com/Yuan1z0825/nature-skills
  category: paper_writing
  trigger_keyword:
  - nature-response
  - nature response
  - 起草
  - 稿件
  - 修改
  - 评审
  - 审稿
  - 答辩
  - 回复审稿
  - draft
  - audit
  - revise
  prompt_mode: full
  enabled: 'true'
---
# Nature Reviewer Response — Router

This skill is split into two layers:

- A **static layer** under `static/` that holds versioned, reusable content fragments (the default stance and red lines, and the response workflow with output format).
- A **dynamic layer** (this file plus `manifest.yaml`) that loads the core every time and reaches for the deeper response references or templates only when a step needs them.

Do not try to apply the response logic from memory or from this router. Always load fragments from disk as described below.

## Routing protocol

Follow these four steps every time the skill is invoked.

### 1. Load the manifest and the core layer

Read [manifest.yaml](manifest.yaml). Then read every file listed under `always_load`:

- `static/core/stance.md` — the editor-facing purpose, the default stance, the red lines, and the source hierarchy that apply to every response job.
- `static/core/workflow.md` — accepted inputs, the revision correspondence workflow, and the output package format.

### 2. No content axis — identify mode and language inline

Unlike nature-writing or nature-figure, nature-response has no fragment axis. Its variation is identified at runtime, not by loading different content bodies:

- **task mode** — `draft` / `audit` / `revise` / `triage-only` / `cover-letter` / `revision-package` / `latex-template` / `appeal-like`.
- **decision type** — minor revision, major revision, revise-and-resubmit, transfer after review, or unclear.
- **user language** — if the user writes Chinese, also produce the 中文核对 block.

Decision type is a required intake gate for normal revision work. First extract it from an
editor decision letter when available. If it is still unclear, ask the user whether this is a
`Major Revision` or `Minor Revision` before drafting a response strategy or response prose. Do
not infer the decision from the number, tone, or apparent difficulty of reviewer comments.

Use `references/intake-and-routing.md` to fix the task mode, minimum inputs, and readiness state before drafting. Route appeal-like cases separately; do not draft an appeal as the default path.

### 3. Run the workflow

Follow the workflow in `core/workflow.md`: if the user pasted a journal email, first parse manuscript metadata, decision type, editor instructions, reviewer reports, required files, deadlines, and reviewer-visibility rules from the email; identify mode and pass the decision-type gate; apply the Major- or Minor-Revision strategy without downgrading the severity of individual comments; extract editor instructions (IDs `E.1`) then reviewer comments (`R1.1`, `R2.1`) when present; classify each item by response action and independently verified work status; build an internal/editor master strategy and tracker; draft a standalone privacy-filtered response for each mutually blind reviewer; when a reviewer missed material already present in the manuscript, treat that as a clarity signal and revise the presentation instead of replying that the point was already stated; draft a revision cover letter when required; map every claimed change to a manuscript location or explicit placeholder; mark changed manuscript text in red on a backed-up copy when editing; format quoted revised manuscript text in the response letter in italics; flag missing author input; run QA; and derive package readiness from the per-item statuses and blocking state.

Whenever a response proposes or performs a manuscript main-text edit, also load
`../nature-shared/core/main-text-discipline.md`. Answer the reviewer completely
in the letter, but keep the manuscript change to the shortest text needed for
the reader. Prefer replacement or compression over appending, and route
non-central robustness or reconciliation detail to SI unless it changes the
central interpretation.

Never invent experiments, citations, line numbers, figure panels, supplementary items, editor instructions, or manuscript changes. Mark anything the author must supply as `AUTHOR_INPUT_NEEDED`.

### 4. Reach for references only when needed

The files under `references/` and `templates/` are deep resources, not defaults. Open them on demand per the `references.on_demand` table in the manifest — for example `references/comment-taxonomy.md` to classify comments, `references/action-mapping.md` for tracker fields, `references/tone-and-stance.md` for disagreement wording, `references/difficult-cases.md` for impossible experiments / conflicting reviewers / appeal-like cases, `references/chinese-author-alignment.md` for Chinese author notes, `references/latex-templates.md` for `.tex` cover/response/redline outputs, `../nature-shared/core/main-text-discipline.md` for reviewer-driven manuscript additions and evidence relocation, `references/package-consistency-audit.md` whenever the manuscript is edited alongside the letter or the package is about to be compiled and delivered, and `references/qa-checklist.md` before finalizing.

`qa-checklist.md` and `package-consistency-audit.md` are complementary and both apply to a final package: the first asks whether the response is complete, honest, and well-toned; the second asks whether the marked manuscript, the clean manuscript, and the letter actually agree with each other after editing. For a LaTeX package, run `scripts/check_package_consistency.py` after the first complete draft, after every manuscript edit, and immediately before delivery. Any manuscript edit invalidates the letter's verbatim quotes and page references, so re-run the audit rather than treating it as a one-time final check.

## Why this split

- The static layer is versioned and reviewable; the core stays small for a normal response.
- The dynamic layer keeps each invocation cheap: the difficult-case, taxonomy, and QA depth load only when a step needs them.
- The router itself is short on purpose. Update fragments and references, not this file, when adding scope.
- This structure mirrors `nature-writing`, `nature-polishing`, `nature-reader`, `nature-paper2ppt`, `nature-figure`, and `nature-citation`.
