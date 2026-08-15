#!/usr/bin/env python3
"""ResearchMate 统一 CLI 入口（科研 Skill 集成 + 原情报模式占位）。

用法示例：
  python main.py --research "文献综述：一人公司商业模型，结合OPC概念"
  python main.py --research "..." --skill deep-research --review
  python main.py --feed        # 原有情报采集模式（本项目未内置 RSS 采集，见下）
  python main.py --list-skills
  python main.py --rebuild-registry

说明：当前 /workspace 后端为 ResearchMate 学术助手，未包含 RSS 情报采集链路。
--feed 保留原采集模式的入口契约；若后续接入情报采集，只需在 feed_handler 中
调用原有逻辑，不影响本模块。
"""
import argparse
import sys

# 支持从 backend 目录直接运行：把 backend 加入 sys.path
sys.path.insert(0, __file__ and __file__.rsplit("/", 1)[0] or ".")


def feed_handler():
    """原有情报采集模式入口（占位）。

    非科研任务继续走原有情报处理链路；本模块严格隔离，不改动原有逻辑。
    若项目已包含 RSS 采集，在此调用原采集函数并输出到 ./output/feed/。
    """
    print("Feed 模式：未检测到已内置的 RSS 情报采集链路。")
    print("提示：科研 Skill 模块已隔离到 ./research_skills/，不影响原采集逻辑。")
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