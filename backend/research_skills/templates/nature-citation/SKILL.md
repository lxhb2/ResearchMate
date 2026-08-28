---
name: nature-citation
description: "在手稿文本中加入严格的Nature/CNS引用，方法是将长段分解为可读部分，只搜索来自Nature Portfolio,AAAS Sciences家族和Cell Press的已接受旗舰和子期刊标题，通过出版时间范围过滤，并默认输出一个可供参考的管理员输出。"
metadata:
  github_source: https://github.com/Yuan1z0825/nature-skills
  category: literature
  trigger_keyword:
  - nature-citation
  - nature citation
  - 论文
  - 写作
  - 稿件
  - 文献
  - 检索
  - 引用
  - 参考文献
  - 阅读
  - add
  - strict
  prompt_mode: full
  enabled: 'true'
---
# Nature Citation — Router

This skill is split into two layers:

- A **static layer** under `static/` that holds versioned, reusable content fragments (core principles and scope, the Chinese-user operating mode, and the citation workflow).
- A **dynamic layer** (this file plus `manifest.yaml`) that loads the core every time and reaches for heavier material only when a step needs it.

Do not try to apply the citation logic from memory or from this router. Always load fragments from disk as described below.

## Routing protocol

Follow these four steps every time the skill is invoked.

### 1. Load the manifest and the core layer

Read [manifest.yaml](manifest.yaml). Then read every file listed under `always_load`:

- `static/core/principles.md` — what the skill produces, the strict journal scope, the source hierarchy, and the search-quality rules.
- `static/core/chinese-mode.md` — how to operate when the user writes in Chinese or asks for `Nature系列`/`CNS及子刊` style support.
- `static/core/workflow.md` — the seven-step workflow and the final report format.

### 2. No content axis — confirm scope and language inline

Unlike the other nature-* skills, nature-citation has no fragment axis. Its variation is runtime parameters, not different content bodies:

- **journal scope** — `Nature系列` / `CNS` / `CNS及子刊` / flagship-only. Read it from the user's wording (see `core/principles.md`) and pass it to the script as `--scope`.
- **user language** — if the user writes Chinese, follow `core/chinese-mode.md` (Chinese notes, English search queries).
- **input length** — if there are more than ~10 segments, switch to the batched long-article strategy in `references/script-usage.md`.

State the detected scope and date limits in one short line before searching.

### 3. Run the workflow

Follow the seven steps in `core/workflow.md`: segment, parse, search, evaluate support conservatively, validate complete structured author metadata, export one reference-manager file, generate review artifacts when useful, and report with the HTML browser path first. Prefer `scripts/nature_citation.py` for the search/export when internet access is available; open `references/script-usage.md` for its full flag list and the long-article batch strategy. When DOI metadata lacks given names, refetch the record by PMID or verify it against the publisher rather than exporting surname-only `AU` fields.

Never present a paper as support merely because its title is related, and never cite a metadata-only candidate without checking the abstract or publisher page. Do not invent missing bibliographic fields.

### 4. Reach for references only when needed

The files under `references/` are deep references, not defaults. Open them on demand per the `references.on_demand` table in the manifest:

- running the script, full flags, long-article batching → `references/script-usage.md`.
- turning a claim into search queries and support grades → `references/search-strategy.md`.
- the exact Nature/CNS journal-family boundary → `references/journal-scope.md`.
- RIS / EndNote / Zotero RDF export details → `references/ris-endnote.md`.

## Why this split

- The static layer is versioned and reviewable; the core stays small for a normal short run.
- The dynamic layer keeps each invocation cheap: the script flag dump and long-article strategy load only when actually running a search.
- The router itself is short on purpose. Update fragments and references, not this file, when adding scope.
- This structure mirrors `nature-writing`, `nature-polishing`, `nature-reader`, `nature-paper2ppt`, and `nature-figure`.
