---
name: slack-gif-creator
description: "创建动画GIFs的知识和公用事业优化了Slack。提供了限制、验证工具和动画概念。当用户为Slack请求动画GIFs时使用，如“让我为Slack做一个GIF的X doing Y ” 。"
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
