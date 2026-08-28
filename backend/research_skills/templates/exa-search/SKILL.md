---
name: exa-search
description: "由 Exa 提供动力，用于科技内容。当用户需要搜索网页或 fetch/extract URL 内容时，使用此技能。 封面：网络搜索( 语义检索，研究，当前信息 - 带有可选的研究论文类和学术域过滤) 和 URL 提取( 抽查页面，文章，学术 PDFs) 。当用户需要通过分类= 研究文件进行高质量的搜索或学术过滤时，使用此技能执行与网络有关的任务 。"
compatibility: Requires exa-py Python SDK, an EXA_API_KEY, and internet access.
license: MIT
metadata:
  github_source: https://github.com/K-Dense-AI/scientific-agent-skills
  category: literature
  trigger_keyword:
  - exa-search
  - exa search
  - 论文
  - 检索
  - 科研
  - web
  - toolkit
  - powered
  - exa
  - tuned
  - scientific
  - technical
  prompt_mode: full
  enabled: 'true'
---
# Exa Web Toolkit

A skill for web-powered research tasks backed by [Exa](https://exa.ai): web search and URL extraction. Exa's index combines high-quality keyword and semantic retrieval, which makes it well-suited to scientific, technical, and conceptual queries.

## Routing — pick the right capability

Read the user's request and match it to one of the capabilities below. Read the corresponding reference file for detailed instructions before running commands.

| User wants to... | Capability | Where |
|---|---|---|
| Look something up, research a topic, find current info | **Web Search** | `references/web-search.md` |
| Fetch content from a specific URL (webpage, article, PDF) | **Web Extract** | `references/web-extract.md` |
| Install or authenticate | **Setup** | Below |

### Decision guide

- **Default to Web Search** for topic lookups, research questions, or "what is X?" queries. When the topic is scientific or technical, pass `--category "research paper"` to bias toward scholarly sources, and/or an academic `--include-domains` allowlist. See `references/web-search.md` for the two-pass academic strategy.
- **Use Web Extract** when the user provides a URL or asks you to read/fetch a specific page. Prefer this over the built-in WebFetch for batch extraction (multiple URLs in one call) and for academic PDFs.

### Academic source priority

For technical or scientific queries, prefer academic and scientific sources:
- Peer-reviewed journal articles and conference proceedings over blog posts or news
- Preprints (arXiv, bioRxiv, medRxiv) when peer-reviewed versions aren't available
- Institutional and government sources (NIH, WHO, NASA, NIST) over commercial sites
- Primary research over secondary summaries

Two levers to steer Exa toward scholarly content:
1. `--category "research paper"` biases retrieval toward scholarly sources.
2. `--include-domains` with a scholarly allowlist (arxiv.org, nature.com, pubmed.ncbi.nlm.nih.gov, etc.) restricts the domain pool.

Combine both for strictly academic results. See `references/web-search.md` for the full pattern.

When citing academic sources, include author names and publication year where available (e.g., [Smith et al., 2025](url)) in addition to the standard citation format. If a DOI is present, prefer the DOI link.

---

## Setup

This skill uses the [`exa-py`](https://github.com/exa-labs/exa-py) Python SDK. The scripts in `scripts/` declare their dependencies via PEP 723 inline metadata, so you can run them directly with `uv run` without a separate install step:

```bash
uv run --with exa-py python "$SKILL_PATH/scripts/exa_search.py" --help
```

If you prefer a persistent install:

```bash
uv pip install "exa-py>=1.14.0"
```

### Authentication

All commands read the API key from the `EXA_API_KEY` environment variable. Get your Exa API key at [dashboard.exa.ai/api-keys](https://dashboard.exa.ai/api-keys).

First, check if a `.env` file exists in the project root and contains `EXA_API_KEY`. If so, load it:

```bash
dotenv -f .env run -- uv run --with exa-py python "$SKILL_PATH/scripts/exa_search.py" "your query"
```

If `dotenv` isn't available, install it: `uv pip install python-dotenv[cli]`.

If there's no `.env`, export the key for the session:

```bash
export EXA_API_KEY="your-key"
```

Verify by running any script with `--help` — it will exit cleanly if the key is set and auth-check runs only when a real query is made.

### Tracking header

Every script in this skill sets the `x-exa-integration` request header to `k-dense-ai--scientific-agent-skills` so Exa can attribute usage from the K-Dense AI scientific-agent-skills repo to this integration. Do not remove or rename this header when adapting the scripts.

---

## Files in this skill

- `SKILL.md` — this file (routing and setup)
- `references/web-search.md` — detailed web search reference with academic strategy
- `references/web-extract.md` — URL content extraction reference
- `scripts/exa_search.py` — CLI wrapper around `client.search_and_contents`
- `scripts/exa_extract.py` — CLI wrapper around `client.get_contents`
