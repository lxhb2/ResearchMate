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


def _sandbox_env() -> dict[str, str]:
    """构造受限子进程环境：只保留运行必需变量，剔除密钥与代理。"""
    allowed = {
        "PATH", "SystemRoot", "WINDIR", "TEMP", "TMP",
        "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "COMPUTERNAME",
    }
    env = {k: v for k, v in os.environ.items() if k in allowed}
    # 显式兜底：任何疑似密钥/令牌的变量都不传入
    for k in list(env):
        upper = k.upper()
        if any(s in upper for s in ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")):
            env.pop(k, None)
    env["MPLBACKEND"] = "Agg"
    env["PYTHONIOENCODING"] = "utf-8"
    env["NO_PROXY"] = "*"
    env["no_proxy"] = "*"
    return env


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
                # -I：隔离模式，忽略用户 site、PYTHONPATH 与环境变量影响
                [sys.executable, "-I", "-S", "-E", "-c", full_code],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=tmp,
                env=_sandbox_env(),
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
