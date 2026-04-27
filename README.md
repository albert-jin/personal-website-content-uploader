# Windows Content Uploader

这是一个用于 `albert-evans.github.io` 的半自动可视化桌面工具，支持新增 `_publications`、`_news`、`_talks` 内容并执行 Git 推送。

## 主要功能

- 首次登录配置本地仓库绝对路径。
- 路径可手输绝对路径，也可点“浏览”用文件管理器选择目录。
- 保存路径时会自动校验 `.git` 文件夹；若缺失会报错并要求重选。
- 顶部“当前项目路径”里的“未设置”文本可点击，随时重新选择项目目录。
- 新建 md 且未手填 `slug` 时，文件名规则为：
  - 日期前缀保持不变
  - 标题清洗后取前 20 个字符
  - 再拼接随机数字后缀（例如 `2026-04-27-my-title-123456.md`）
- 可视化表单录入 `_publications` / `_news` / `_talks`。
- 自动在目标仓库写入对应 `md` 文件。
- `_talks` 支持选择本地图片并自动复制到：
  - `assets/image-albert-evans/image-continue-added`
- 自动生成 talk 图片的 Markdown 引用（`relative_url`）。
- 本地待提交计数（`app_state.json`），关闭时若有未提交会提醒。
- 一键打开 Git 终端执行：
  - `git add .`
  - `git commit -m "..."`
  - `git push https://albert-jin@github.com/albert-jin/albert-evans.github.io.git`
- 新增“检测并拉取远端”按钮：
  - 自动执行 `git fetch origin`
  - 自动检测本地与远端差异
  - 如远端领先则执行 `git pull --no-rebase origin <当前分支>` 做 merge
- 点击“提交到远端”并弹出“已启动推送”提示框后，会立即把待提交修改数清零。

## 直接运行（不打包）

在 `windows-content-uploader` 目录下运行：

```powershell
python .\main.py
```

或双击 `run.bat`。

## 打包成 EXE（双击脚本）

本目录已提供一键打包脚本：`build_exe.bat`。

### 前置条件

- Windows 系统
- 本机可用 Python 3（`py -3` 或 `python`）
- 首次打包需要联网安装 `pyinstaller`

### 打包步骤

1. 双击 `build_exe.bat`。
2. 脚本会自动执行：
   - 自动检测 Python 启动命令
   - 安装/升级 `pyinstaller`
   - 自动结束正在运行的 `windows-content-uploader.exe`（若存在）
   - 删除旧的 `deployed` 文件夹
   - 重新打包并把所有产物输出到 `deployed`
3. 打包完成后，运行：
   - `deployed\windows-content-uploader.exe`

## 产物目录说明

- 每次打包都会强制覆盖 `deployed`。
- EXE 及相关构建文件都会放在 `windows-content-uploader\deployed` 下。

## 备注

- `windows-content-uploader/` 已在仓库根 `.gitignore` 中忽略。
- 因此该工具代码和打包产物不会被你的网站仓库提交上传。
