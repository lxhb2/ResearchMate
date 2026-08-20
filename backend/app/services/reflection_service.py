"""任务反思沉淀：长任务结束后把执行结论与待办写入长期记忆。"""
from typing import Optional

from app.agent import memory as memory_mod


def save_reflection(
    user_id: str,
    title: str,
    task: str,
    result_summary: str,
    status: str,
    llm=None,
) -> dict:
    """生成并保存一条反思记录到 notes.md。"""
    content = f"任务：{task}\n状态：{status}\n结果：{result_summary[:2000]}"
    if llm is not None and getattr(llm, "provider", "") != "mock":
        try:
            prompt = (
                "请把以下科研任务执行记录压缩成 2-3 句反思摘要，包含：完成内容、关键结论、下一步建议。"
                "只输出摘要。\n\n" + content
            )
            summary = llm.chat(
                [
                    {"role": "system", "content": "你是科研助手的自我反思模块，只输出反思摘要。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                max_tokens=300,
            ).strip()
            if summary:
                content = summary
        except Exception:  # noqa: BLE001
            pass
    memory_mod.write_memory(str(user_id), "notes.md", f"## {title}\n\n{content}", append=True)
    return {"ok": True, "title": title}
