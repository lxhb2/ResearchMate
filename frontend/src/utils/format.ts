/**
 * 把可能包含「对比结果」的内容格式化为可直接交给 ReactMarkdown 渲染的 Markdown 文本。
 *
 * 后端「文献对比」工具（llm_compare）会返回结构化对象 {table, summary}：
 * - table   ：一张 Markdown 表格字符串
 * - summary ：对比总结文本
 *
 * 在 Mock / 部分链路上该对象会被序列化成 JSON 字符串（如
 * `{"table": "...", "summary": "..."}`）作为回答返回，直接渲染会显示成原始 JSON。
 * 这里负责识别并还原成 Markdown（表格 + 总结），其余内容原样返回。
 */
export function formatMarkdownContent(content: unknown): string {
  // 字符串：尝试解析为对比结果 JSON
  if (typeof content === 'string') {
    const trimmed = content.trim()
    if (trimmed.startsWith('{')) {
      try {
        const obj = JSON.parse(trimmed)
        if (isCompareResult(obj)) {
          return buildCompareMarkdown(obj)
        }
      } catch {
        /* 非法 JSON，原样返回 */
      }
    }
    return content
  }
  // 对象：直接读取 table / summary
  if (isCompareResult(content)) {
    return buildCompareMarkdown(content)
  }
  return content == null ? '' : String(content)
}

interface CompareResult {
  table: string
  summary: string
}

function isCompareResult(v: unknown): v is CompareResult {
  return (
    !!v &&
    typeof v === 'object' &&
    typeof (v as Record<string, unknown>).table === 'string' &&
    typeof (v as Record<string, unknown>).summary === 'string'
  )
}

function buildCompareMarkdown(r: CompareResult): string {
  return `${r.table}\n\n${r.summary}`
}