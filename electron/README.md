# ResearchMate Desktop

Electron 壳负责：

1. 启动内置 `backend/ResearchMate.exe`（PyInstaller 单文件，内嵌前端）。
2. 等待后端就绪后打开桌面窗口。
3. 通过 GitHub Releases 检查版本、下载更新并安装。

## 本地构建

```powershell
cd frontend
npm install
npm run build

cd ../backend/packaging/windows_sqlite
build_windows.bat

cd ../../electron
npm install
npm run build
```

构建产物在 `release/`，其中 NSIS 安装包和 ZIP 都可上传到 GitHub Releases。
