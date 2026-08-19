#!/usr/bin/env python3
"""ResearchMate 统一 CLI 入口（科研 Skill 集成 + 插件化情报采集）。

用法示例：
  python main.py --research "文献综述：一人公司商业模型，结合OPC概念"
  python main.py --research "..." --skill deep-research --review
  python main.py --feed        # 情报采集：走 feed-digest 插件的 rss_fetch 工具
  python main.py --list-skills
  python main.py --rebuild-registry

说明：RSS 情报采集由预装的 feed-digest 插件提供（plugins/feed-digest/，
运行目录 storage/agent/plugins/feed-digest/）。停用插件后 --feed 自动降级为提示。
"""
import argparse
import sys

# 支持从 backend 目录直接运行：把 backend 加入 sys.path
sys.path.insert(0, __file__ and __file__.rsplit("/", 1)[0] or ".")


def feed_handler() -> int:
    """情报采集模式：调用 feed-digest 插件的 rss_fetch 工具抓取 RSS 并落盘简报。

    能力完全由插件提供；插件被停用/卸载时降级为提示信息，不影响其他功能。
    """
    try:
        from app.agent.plugin_manager import get_plugin_manager
        from app.agent import tools as tools_mod

        get_plugin_manager().load_all()
        tool = tools_mod.get_tool("rss_fetch")
        if tool is None:
            raise RuntimeError("feed-digest 插件未启用")
        out = tool.run(tools_mod.ToolContext(), {"limit": 12})
    except Exception as e:  # noqa: BLE001
        print(f"Feed 模式：情报采集插件不可用（{e}）")
        print("提示：在应用「设置 → 插件」启用 feed-digest 插件即可恢复 RSS 情报采集。")
        return 0

    import os
    import time

    lines = [f"# 科研情报简报 · {time.strftime('%Y-%m-%d')}", ""]
    for feed in out.get("feeds", []):
        if not feed.get("ok"):
            lines.append(f"- ⚠️ 抓取失败：{feed.get('url')}（{feed.get('error', '')[:80]}）")
            continue
        lines.append(f"## {feed.get('url')}")
        for item in feed.get("items", []):
            link = f" — {item['link']}" if item.get("link") else ""
            lines.append(f"- {item.get('title', '')}{link}")
        lines.append("")

    text = "\n".join(lines)
    print(text)
    outdir = "output/feed"
    os.makedirs(outdir, exist_ok=True)
    path = os.path.join(outdir, time.strftime("%Y%m%d") + "-feed.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text + "\n")
    print(f"\n情报简报已写入 ./{path}（共 {out.get('total', 0)} 条）")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ResearchMate CLI")
    parser.add_argument("--research", type=str, default="", help="科研任务指令，如：文献综述：...")
    parser.add_argument("--feed", action="store_true", help="原有情报采集模式")
    parser.add_argument("--skill", type=str, default="", help="指定执行某个 skill（如 deep-research）")
    parser.add_argument("--review", action="store_true", help="执行后调用 Supervisor 评审")
    parser.add_argument("--project", type=str, default="", help="科研项目名，用于持久记忆分目录")
    parser.add_argument("--provider", type=str, default="", help="llm 提供方：ollama|openai|mock|auto")
    parser.add_argument("--list-skills", action="store_true", help="列出已注册的科研 skill")
    parser.add_argument("--rebuild-registry", action="store_true", help="从 templates/ 重建注册表")
    args = parser.parse_args(argv)

    from research_skills import config
    from research_skills.registry import get_registry
    from research_skills.scheduler import dispatch

    if args.provider:
        import os

        os.environ["RESEARCH_LLM_PROVIDER"] = args.provider

    if args.rebuild_registry:
        get_registry().load(rebuild=True)
        print(f"已重建注册表：{config.REGISTRY_PATH}")

    if args.list_skills:
        skills = get_registry().all()
        print(f"已注册科研 Skill（{len(skills)}）：\n")
        for s in skills:
            flags = ""
            if not s.get("enabled", True):
                flags = " [disabled]"
            print(f"  - {s['name']:<22} [{s.get('category','')}]{flags} {s.get('description','')[:40]}")
        print(f"\n分类：{', '.join(config.__dict__.get('CATEGORIES', []))}")
        return 0

    if args.feed and not args.research:
        return feed_handler()

    if args.research:
        opts = {"skill": args.skill, "project": args.project}
        result = dispatch(args.research, opts)
        if result.get("intent") == "feed":
            print(result.get("note", "非科研任务，走原情报链路。"))
            return 0
        print(f"意图：{result.get('intent')} | Skill：{result.get('skill')}")
        print(f"产物：{result.get('output_file')}")
        if args.review:
            from research_skills.supervisor import review

            r = review(result, opts=opts)
            print(f"评审：{r.get('output_file')}")
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())