"""轻量实验代码沙箱。

以受限子进程执行用户/LLM 生成的绘图分析代码，超时自动终止，避免阻塞主服务。
仅暴露标准库与常用科学计算库，防止直接访问网络与文件系统敏感区。
"""
from dataclasses import dataclass
import os
import subprocess
import sys
import tempfile


@dataclass
class SandboxResult:
    output: str      # print 捕获的输出
    chart: str | None = None  # 生成的图表文件路径


def run_python(code: str, timeout: int = 20) -> SandboxResult:
    """在受限子进程中执行 Python 代码，返回输出与图表路径。"""
    # 注入 matplotlib 无界面后端；重定向 print 以捕获输出；画布保存为本地 PNG
    chart_path = None
    wrapper_lines = [
        "import sys",
        "try:",
        '    import matplotlib',
        '    matplotlib.use("Agg")',
        "    import matplotlib.pyplot as plt",
        "    _HAS_MPL = True",
        "except Exception:",
        "    _HAS_MPL = False",
        "    plt = None",
        "_out = []",
        "_orig_print = print",
        "def print(*a, **k):",
        '    _out.append(" ".join(str(x) for x in a))',
        "exec(_CODE_)",
        "if _HAS_MPL:",
        "    for _fn in list(plt.get_fignums()):",
        "        plt.figure(_fn).savefig(_CHART_PATH_ + str(_fn) + '.png', dpi=100, bbox_inches='tight')",
        "    plt.close('all')",
        "sys.stdout.write(chr(10).join(_out))",
    ]
    wrapper = "\n".join(wrapper_lines)

    with tempfile.TemporaryDirectory(prefix="sci_sandbox_") as tmp:
        chart_path = os.path.join(tmp, "out")
        full_code = (
            f"_CODE_ = {code!r}\n"
            f"_CHART_PATH_ = {chart_path!r}\n"
            + wrapper
            + "\n"
        )
        try:
            proc = subprocess.run(
                [sys.executable, "-c", full_code],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=tmp,
                env={**os.environ, "MPLBACKEND": "Agg"},
            )
        except subprocess.TimeoutExpired:
            return SandboxResult(output=f"[错误] 代码执行超时（>{timeout}s），已终止")

        stderr = (proc.stderr or "").strip()
        if proc.returncode != 0:
            return SandboxResult(output=f"[程序退出码 {proc.returncode}]\n{stderr or '无输出'}")
        if stderr:
            stderr = "\n[警告] " + stderr

        chart = None
        if chart_path and os.path.exists(chart_path + "1.png"):
            chart = chart_path + "1.png"
        return SandboxResult(output=(proc.stdout or "（无输出）") + stderr, chart=chart)