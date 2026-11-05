# PlanCheckBox（Python 桌面版）

把原来的单文件 HTML 任务追踪器（PlanCheckBox）改造成 Windows 桌面程序：界面沿用原 HTML 前端，
数据读写改由 Python 直接操作本地 JSON，勾选立即写回原文件。

- 界面：pywebview + 系统自带 WebView2（不引入 Qt / Electron / Node）
- 数据：只读写你选择的 `*_checkbox_use.json`，只改 `done` / `doneAt` / `history`，键序与缩进保持原样
- 分发：PyInstaller 单文件 exe，目标机器不需要安装 Python

## 快速开始

| 场景 | 做法 |
| --- | --- |
| 已打包 | 双击仓库根目录的 `PlanCheckBox.exe` |
| 开发态（已装 Python 3.10+ 与依赖） | 双击 `launch.cmd`，或 `python launch.py` |
| 无界面自检 | `PlanCheckBox.exe --selftest` / `python launch.py --selftest` |
| 启动界面并回读 DOM 指标 | `PlanCheckBox.exe --diag`（6 秒后自动关窗，用于打包后验证） |
| 查看版本 | `PlanCheckBox.exe --version` |
| 运行单元测试 | `python -m unittest discover -s tests -t .` |

示例数据在 `sample_data/`（真实契约文件的前两个月，可直接用来跑通四页）。

> `PlanCheckBox.exe` 由 `build/build.ps1` 在本机生成（仓库内的 `.venv` 只用于打包，已被 `.gitignore` 忽略）。

## 目录结构

```
PlanCheckBox-python/
├─ PlanCheckBox.exe          # 打包后的双击入口（由 build/build.ps1 生成）
├─ launch.cmd / launch.py    # 开发态入口
├─ app/
│  ├─ main.py                # 入口：参数解析、WebView2 探测、创建窗口
│  ├─ bridge.py              # JS ↔ Python 桥接（选文件、导入导出、动作分发）
│  ├─ version_info.txt       # exe 版本信息
│  └─ core/
│     ├─ parser.py           # JSON → 组模型（白名单字段，未知字段容忍）
│     ├─ model.py            # 排序、进度、预测、热力图分档、板块月份汇总
│     ├─ jsonio.py           # 缩进/换行/键序保真写回、原子写入
│     ├─ service.py          # 状态机 + 四页视图数据
│     ├─ store.py            # 数据目录探测 / config.json / 会话记录（见「数据目录」）
│     └─ dates.py            # 日期与中文字格式化
├─ ui/
│  ├─ index.html             # 复用原 HTML 的样式与结构
│  └─ app.js                 # 渲染层（只消费 Python 下发的视图数据）
├─ sample_data/              # 5 组示例 JSON（只含前两个月）
├─ tests/                    # 70 个单元测试（不依赖 GUI）
└─ build/
   ├─ PlanCheckBox.spec      # PyInstaller 配置
   ├─ build.ps1              # 一键重建：建 .venv → 装依赖 → 跑测试 → 打包 → 复制 exe
   ├─ requirements-build.txt
   └─ make_icon.py           # 由原始 PNG 生成 256px png + 多尺寸 ico
```

## 一键重建 exe

```powershell
powershell -ExecutionPolicy Bypass -File build\build.ps1
# 或者改成目录形态（启动更快、WebView2 资源更好打进去）
powershell -ExecutionPolicy Bypass -File build\build.ps1 -Onedir
```

脚本只在仓库内创建 `.venv`，不会改动系统 Python 或环境变量。

### onefile 与 onedir

| 形态 | 优点 | 缺点 |
| --- | --- | --- |
| `--onefile`（默认） | 单个 exe，最好分发 | 每次启动要把内置资源解压到临时目录，首次启动 1–3 秒；杀毒软件偶尔误报 |
| `--onedir` | 启动快，排错方便 | 产物是一个目录，需整体压缩分发 |

### 每次改代码都要重新打包吗？

**结论：用 exe 运行就必须重新打包；开发调试不需要。**

- **onefile exe 是快照**：PyInstaller 把 `app/`、`ui/`、Python 解释器和依赖一起压进单个 exe。启动时先解压到 `%TEMP%\_MEIxxxx` 再从那里运行，**不会读取仓库里的 `app/`、`ui/`**。所以改完源码不打包，双击旧 exe 跑的还是旧代码——改代码 ≠ 改 exe。
- **开发态直跑源码**：`launch.cmd` / `python launch.py` 直接从仓库加载 `app/` 和 `ui/`，改完保存、重开脚本即生效，完全不需要打包，也没有解压开销。
- **`--onedir` 介于两者之间**：产物是同目录的 exe + `_internal/`，内部是解包后的文件；理论上替换对应文件可生效，但依赖清单/路径容易错，仍建议重新打包。
- **配置与数据不受影响**：重新打包只覆盖 exe，`data\`、`docs\`、`config.json`、`session.json` 都会保留（打包不删除这些文件）。

建议发版流程：改代码 → `python -m unittest discover -s tests -t .` → `build\build.ps1`（脚本会先跑单测再打包并复制 exe）→ `PlanCheckBox.exe --version` / `--selftest` → `--diag` 看 DOM 指标 → 分发 exe（便携场景再附 `data\`）。

## 数据目录（便携）

程序不写死任何盘符。每次启动按以下顺序决定「数据目录」（会话记录 `session.json` 放在这里）：

| 优先级 | 来源 | 说明 |
| --- | --- | --- |
| ① | 环境变量 `PLANCHECKBOX_DATA_DIR` | 临时覆盖，优先级最高（自动化/多套数据时用） |
| ② | 配置文件 `config.json` 的 `dataDir` | 界面「数据目录」按钮选择后写入，重启仍生效 |
| ③ | exe 同级 `data\` | **便携优先**：把 exe 和 `data\` 一起拷给别人，数据跟着走 |
| ④ | exe 同级 `docs\` | 兼容既有目录结构（同级存在 `docs\` 时直接用它） |
| ⑤ | `%LOCALAPPDATA%\PlanCheckBox` | 前三项都不存在时的兜底 |

- 配置文件 `config.json` 优先写在 exe 同级（目录可写时）；exe 位于只读位置（如 `Program Files`、只读光盘/U 盘）时，自动改写到 `%LOCALAPPDATA%\PlanCheckBox\config.json`。
- 顶栏「数据目录」按钮会弹出系统选目录框，选择后立即生效并记住。
- 源码态（`launch.py`）下「exe 同级」即仓库根目录，因此便携探测看的是仓库根下的 `data\` / `docs\`。
- 分发给别人时最省事的做法：新建一个文件夹，放入 `PlanCheckBox.exe`，再建 `data\` 并把 `*_checkbox_use.json` 放进去。

## WebView2 运行时

程序使用系统自带的 Microsoft Edge WebView2 Runtime。Windows 10/11 一般已内置；
若启动时提示「未检测到 WebView2 Runtime」，请到 Microsoft 官网下载 **Evergreen Bootstrapper** 安装后重开。
本程序不会自动联网下载或安装任何组件；缺失时只会弹出可读提示，不会崩溃。

## 数据契约

以 5 个真实 `*_checkbox_use.json` 为例（结构如下）：

```
{ meta: {groupName, subject, kind, priority, examDate, planStart, generatedAt, version},
  months: [ {id, label, weeks: [ {id, index, label, start, end,
             days: [ {date, type, tasks: [ {id, title, priority, kind, topic,
                                              minutes, slot, done, doneAt, history[]} ]} ]} ]} ]}
```

- `doneAt`：最近一次「勾选完成」的本地时间（带时区偏移，如 `2026-11-05T09:10:00+08:00`）
- 取消勾选：`done=false`，`doneAt` 保留最近一次完成时间，`history` 追加一条 `undone`
- 重新勾选：`doneAt` 更新为本次时间，`history` 继续累积
- 未知字段（如 `day.note`、任务自定义字段）原样保留；缺 `meta`、`months` 为空、任务全部缺标题等情况会报错

## 界面四页

1. **选择任务**：多选 / 追加 / 移除 / 清空；显示名取 `meta.groupName`，缺失回退文件名；按任务数从高到低排列
2. **总览**：整年热力图（周一起始，0 / 1–2 / 3–5 / 6+ 四档，按 `doneAt` 本地日期、按任务 id 去重）、
   全部科目月历、每任务一条横条（组名 + 确定性配色 + 板块月份 + 进度 + 预计完成）
3. **月度**：只显示本组类型的一条进度条、42 格月历（P0→P1→P2、已完成下沉、健身绿色、当日总分钟）、月份卡片（完成月沉底）
4. **周度**：本周一条或两条进度条（学习组显示学习 + 健身）、周卡原地展开、勾选即时写回

预计完成时间：近 14 天加权速率（近 7 天权重 2），无近期记录退回 `planStart` 整体均值，速率过低显示「数据不足」。

## 已知限制

- 界面依赖 WebView2；极小概率在无 Edge 的环境需要手动安装运行时
- GUI 已用 `--diag`（回读 DOM）+ 窗口标题变化验证可启动、能渲染；无交互桌面时无法做像素级截图
- 导入进度只更新内存状态（与 HTML 版一致），重新勾选即写回；不批量回写磁盘
- `history` 不设上限，长期使用后单任务记录会变长
- 同级 `data\` / `docs\` 的优先级高于 `%LOCALAPPDATA%`：把 exe 放进含 `docs\` 的目录会自动沿用该目录，属预期行为；想固定到别处可用顶栏「数据目录」或 `PLANCHECKBOX_DATA_DIR`
- 分发给别人时只需要 exe（+ 可选 `data\`）；把 exe 单独拷到空目录也能启动，此时数据目录回退到 `%LOCALAPPDATA%\PlanCheckBox`
