---
name: slack-gif-creator
description: "Knowledge and utilities for creating animated GIFs optimized for Slack. Provides constraints, validation tools, and animation concepts. Use when users request animated GIFs for Slack like \"make me a GIF of X doing Y for Slack.\""
metadata:
  version: ""
  github_source: "https://github.com/anthropics/skills"
  category: research_closed_loop
  trigger_keyword:
    - slack-gif-creator
    - slack gif creator
    - knowledge
    - utilities
    - creating
    - animated
    - gifs
    - optimized
  enabled: "true"
---

## Trigger Keywords
slack-gif-creator, slack gif creator, knowledge, utilities, creating, animated, gifs, optimized

## System Prompt
```python
from core.gif_builder import GIFBuilder
from PIL import Image, ImageDraw
