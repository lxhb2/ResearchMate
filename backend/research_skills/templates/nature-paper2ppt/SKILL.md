---
name: nature-paper2ppt
description: "从科学论文，预印本，PDF,文章文本，图例传说，或读注中构建完整的自然式中国PPTX演示，用于期刊俱乐部，集体会议，论文研讨会，论文分享，会议或防御甲板，以及QQPTQPTQPPT等中文请求。"
metadata:
  github_source: https://github.com/Yuan1z0825/nature-skills
  category: literature
  trigger_keyword:
  - nature-paper2ppt
  - nature paper2ppt
  - 论文
  - 写作
  - 阅读
  - 图表
  - 绘图
  - 幻灯片
  - 演示
  - build
  - complete
  - nature-style
  prompt_mode: full
  enabled: 'true'
---
# Paper-to-PPTX — Router

This skill is split into two layers:

- A **static layer** under `static/` that holds versioned, reusable content fragments (core principles, toolchain policy, the 9-step workflow, output/quality rules, and per-paper-type presentation arcs).
- A **dynamic layer** (this file plus `manifest.yaml`) that detects the paper type and loads only the fragments needed for the current job. Deep design, figure, and self-review material lives in on-demand references.

Do not try to apply the deck-building logic from memory or from this router. Always load fragments from disk as described below.

## Routing protocol

Follow these five steps every time the skill is invoked.

### 1. Load the manifest and the core layer

Read [manifest.yaml](manifest.yaml). It declares the `paper_type` axis, the allowed values, and the file paths each value maps to.

Also read every file listed under `always_load`. These hold the purpose and core principle, the lean operating mode and toolchain policy, the 9-step workflow spine, and the output/quality rules that apply to every deck, plus the shared Terminology Ledger used to keep technical terms consistent across slides.

### 2. Classify the paper type

Decide the `paper_type` value using the manifest's `detect:` hint and the source:

- `discovery` — discovery / mechanism papers (question-to-evidence arc). Default.
- `methods` — methods / AI / tool / algorithm papers (problem-to-solution arc).
- `resource` — resource / dataset / atlas / omics / benchmark papers (workflow-to-validation arc).
- `clinical` — clinical / population / intervention studies (design-to-inference arc).
- `materials` — materials / chemistry / physics / engineering papers (property-to-mechanism / design-to-performance arc).
- `review` — reviews / perspectives / commentaries / meta-analyses (evidence-map arc).

State the detected value in one short line to the user before designing slides, so they can correct you cheaply.

### 3. Load the matching fragment

Read the file mapped for the detected `paper_type`. It gives the presentation arc and how to adapt the default slide structure for this type. Do **not** read every fragment in `static/`.

### 4. Build the deck using the loaded material

Apply the loaded fragments in this priority order:

1. Core principles (`core/principles.md`) — the argument is the spine; lean operating mode; accepted inputs; Chinese-by-default language rule.
2. Toolchain policy and fast path (`core/toolchain.md`) — cross-platform Python-first stack, default fast path.
3. Paper-type arc (the loaded `paper_type` fragment) — narrative order and slide structure for this paper.
4. Workflow (`core/workflow.md`) — run the 9 steps end to end.
5. Output and quality rules (`core/output-and-quality.md`) — deliverables, quality gates, fallbacks.

Build the Terminology Ledger (`../nature-shared/core/terminology-ledger.md`) while reading the source, so model names, gene/protein names, datasets, metrics, and abbreviations stay identical across every slide and speaker note.

The end product is a real `.pptx` deck, not an outline or script. Do not fabricate results, numbers, or figure details.

### 5. Reach for references only when needed

The files under `references/` are deep references, not defaults. Open them on demand per the `references.on_demand` table in the manifest:

- composing/auditing slide layout, visual rhythm, typography, anti-template design, archetypes, on-slide text budget → `references/design-and-layout.md`.
- selecting, extracting, cropping, and quality-checking figure/table assets → `references/figure-assets.md`.
- running the self-review/corrective revision loop, severity grading, programmatic PPTX checks, rendered-preview policy, and final verification → `references/self-review.md`.

When a real PPTX has been generated, run `scripts/audit_pptx_quality.py` unless the file is unavailable. Treat high-severity findings as blockers, revise the deck, then re-run the audit and record the final result in `output/qa_report.md`.

## Why this split

- The static layer is versioned and reviewable. Adding a new paper-type arc is one new fragment plus one manifest line.
- The dynamic layer keeps each invocation cheap: only the arc for this paper enters context up front; heavy design and QA material loads only when that step runs.
- The router itself is short on purpose. Update fragments, not this file, when adding scope.
- This structure mirrors `nature-writing`, `nature-polishing`, and `nature-reader` so shared content lives in `nature-shared/`.
