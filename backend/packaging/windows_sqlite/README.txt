ResearchMate 科研助手 - 免 Python 便携包（SQLite 版）
=============================================

这是一个「无需任何编程环境」的便携版。用户不用装 Python / Node / 数据库，
解压后双击 ResearchMate.vbs 即可使用，全程无任何黑色命令行窗口。

【普通用户怎么用】
1. 解压整个 ResearchMate 文件夹
2. 双击 ResearchMate.vbs（推荐，完全无黑窗口）
   - 也可以双击 start.bat（启动时会短暂显示一个命令行窗口，之后自动关闭）
3. 首次启动约 5-10 秒，之后会自动弹出一个独立的「应用窗口」
   （基于 Edge/Chrome 的应用模式，没有地址栏和标签页，看起来像正常桌面应用）
4. 数据（数据库、PDF、笔记）都保存在本文件夹内，删除文件夹即清空
5. 用完后双击 stop.bat 可完全退出后台服务

【目录结构】
ResearchMate/
  ResearchMate.vbs     一键启动（推荐双击这个，完全隐藏无黑窗）
  start.bat            一键启动（备用，会短暂显示命令行窗口）
  stop.bat             一键退出（停止后台服务）
  backend/
    ResearchMate.exe   程序本体（已内嵌前端，免 Python，无控制台窗口）
  README.txt           本说明
  说明：数据库 researchmate.db、storage/、researchmate.log
        会在首次运行时自动生成

【如何获得这个包（构建方才需要）】
这个包由「有 Python 的电脑」构建一次：
1. 克隆源码，安装 Python 3.10+ 和 Node.js 18+
2. 进入 backend/packaging/windows_sqlite
3. 运行  build_windows.bat
4. 构建完成后，输出在 _build/ResearchMate
5. 把该文件夹压缩成 zip 分发给普通用户即可

【配置】（可选，普通用户通常不用管）
- 大模型：打开应用后，在「设置」页填写接口地址 / Key / 模型
  （支持 OpenAI、DeepSeek、通义、本地 Ollama 等兼容接口）
- 不配置也能用：自动降级为离线占位 + 关键词检索

【FAQ】
- 没有窗口弹开？等 10 秒后手动访问 http://localhost:8000/
- 想完全停掉：双击 stop.bat（或任务管理器结束 ResearchMate.exe）
- 端口被占用：改 start.bat 里的 PORT= 后重开
- 运行日志：本文件夹下的 researchmate.log
