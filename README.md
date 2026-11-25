# PlanCheckBox（Python 桌面版）

把原来的单文件 HTML 任务追踪器（PlanCheckBox）改造成 Windows 桌面程序：界面沿用原 HTML 前端，
数据读写改由 Python 直接操作本地 JSON。

- 界面：pywebview + 系统自带 WebView2（不引入 Qt / Electron / Node）
- 数据：题库 `*_checkbox_use.json` 只读；完成状态写在数据目录 `progress\` 下的 `<题库名>_progress.json`，题库永不被改写
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

## 怎么用（普通用户）

> 你手上不会有现成的「题库文件」。第一件事是照下面的「让 AI 生成题库」做一份，再回来看这一节。

**1. 打开程序**

1. 把 `PlanCheckBox.exe` 放到一个文件夹里（例如桌面上的 `PlanCheckBox` 文件夹）。
2. 双击 `PlanCheckBox.exe`。第一次打开要解压，等 2–5 秒属正常。
3. 如果弹窗说「未检测到 WebView2 Runtime」，按提示去 Microsoft 官网装一次，再重新双击。

**2. 选择任务文件**

1. 第一页点 **「选择文件」**，在文件框里选中一个或多个 `*_checkbox_use.json`（按住 Ctrl 可多选）。
2. 分几次加也可以：再点一次「选择文件」，会追加到列表里。
3. 列表里每一行右侧有 **「移除」**，点它就只从本次使用中去掉（不会删磁盘上的文件）。
4. 全部不要就点 **「清空」**。
5. 列表里有可用文件后，点右下角 **「进入总览」**。

**3. 总览页看什么**

1. 最上面是 **年度完成热力图**：一格一天，颜色越深代表当天完成的任务越多；鼠标停在格子上会显示日期和数量；点格子可看当天任务。
2. 中间是 **月历**：每格显示当天各科目「已完成 / 总数」，点日期弹出当天全部任务；上方可切换上个月 / 下个月。
3. 下面是每个题库一条 **横条**：组名、科目、板块与月份、任务完成进度条、预计完成日期。

**4. 进月度页、周度页**

1. 在总览页点某一条横条 → 进入该组的 **月度页**。
2. 月度页里每个方块是一个月，点方块右下角的 **「进入周度 →」** → 进入 **周度页**。
3. 周度页左边是周列表，点某一周会原地展开该周的任务。
4. 想回上一层，点页面左上角的 **「← 返回月度」/「← 返回总览」**，或用顶栏的面包屑。

**5. 勾选任务**

1. 在周度页（或月历弹窗）里点任务前的方框即可勾选。
2. **完成时间记在哪里**：立刻写入数据目录 `progress\` 下的同名进度文件（`math2_checkbox_use.json` → `%LOCALAPPDATA%\PlanCheckBox\progress\math2_checkbox_use_progress.json`）——该任务的 `done` 变 `true`、`doneAt` 变成当前本地时间（带时区，例如 `2026-11-06T09:10:00+08:00`）、`history` 追加一条 `{"action":"done","at":...}`。
3. 取消勾选：`done` 变 `false`，但 `doneAt` 保留最后一次完成时间，`history` 追加一条 `undone`（所以「之前完成过」不会丢）。
4. **题库文件本身不会被改动**：进度全在 `_progress.json` 里，所以题库可以随时被 AI 重新生成、覆盖、换机器，都不会破坏你的勾选记录。

**6. 进度条和「预计完成」怎么来的**

1. 进度条 = 已完成任务数 ÷ 总任务数（同组内按任务 `id` 去重，重复 id 只算一次）。
2. 预计完成日 = 用你最近 14 天的完成速度往前推：最近 7 天权重 2、再往前 7 天权重 1，算出「平均每天完成几项」，再除剩余任务数。
3. 最近 14 天没有完成记录时，退回用 `meta.planStart` 到今天的整体平均速度。
4. 速度太低或数据太少时，只显示「数据不足」，不会硬编一个日期。

**7. 热力图和月历怎么看**

1. 热力图按「完成那一刻的本地日期」统计，不看任务原定日期；同一天完成 0 / 1–2 / 3–5 / 6+ 项对应四档颜色。
2. 有多年的数据时，热力图右上角可切换年份。
3. 月历每格最多并列显示 3 个科目，超出显示「+N 科」；点日期看当天所有科目的任务和完成状态。

**8. 数据目录在哪**

1. 程序自身只在这里存两个小文件：`config.json`（记住你的选择）和 `session.json`（记住上次打开的文件与页面）。
2. 顺序：`data\`（exe 同级，便携）→ `docs\`（exe 同级）→ `%LOCALAPPDATA%\PlanCheckBox`。
3. 想换位置：点顶栏 **「数据目录」**，选一个文件夹，立即生效并且下次启动还记得。
4. 你的题库 JSON 不会被搬走，仍在你自己选的位置。

**9. 出问题怎么办**

| 现象 | 怎么办 |
| --- | --- |
| 双击后没反应 / 很久才出窗口 | 首次启动要解压，等 5–10 秒；仍不行看是否被杀软拦截，或改用 `-Onedir` 目录版 |
| 提示「未检测到 WebView2 Runtime」 | 安装 Microsoft Edge WebView2 Runtime 后重开 |
| 顶部黄条说「上次设置的数据目录不可用」 | 点顶栏「数据目录」重新选一个可写文件夹；原文件没被改动 |
| 提示「没有解析到任何任务」 | JSON 结构不对，回到「让 AI 生成题库」重新生成 |
| 勾选后没保存 | 检查该 JSON 是否只读、是否被 Excel/网盘占用；程序会提示写盘失败 |
| 列表里文件名是 `math2` 之类 | 该文件缺 `meta.groupName`，按文件名回退显示，不影响使用 |


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
│     ├─ service.py          # 状态机 + 四页视图数据（勾选只写进度文件）
│     ├─ progress.py         # 题库指纹 / _progress.json 读写 / 跨题库迁移
│     ├─ store.py            # 数据目录探测 / config.json / 会话记录（见「数据目录」）
│     └─ dates.py            # 日期与中文字格式化
├─ ui/
│  ├─ index.html             # 复用原 HTML 的样式与结构
│  └─ app.js                 # 渲染层（只消费 Python 下发的视图数据）
├─ sample_data/              # 5 组示例 JSON（只含前两个月）
├─ tests/                    # 104 个单元测试（不依赖 GUI）
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
| `--onefile`（默认） | 单个 exe，最好分发 | 每次启动要把内置资源解压到 `%TEMP%\_MEI*`，首次启动 1–3 秒；被强杀时可能留下解压目录 |
| `--onedir` | 启动快、没有解包残留、排错方便 | 产物是一个目录（exe + `_internal/`），需整体压缩分发 |

两种形态都由 `build\build.ps1` 产出（`-Onedir` 会设置 `PCB_ONEDIR=1`，让 spec 走 `COLLECT`）。

### 临时目录残留（`_MEI*`）

onefile 启动时解压到 `%TEMP%\_MEI<十六进制>`，正常退出时 PyInstaller 自己删除；被强杀/断电/杀软拦截才会残留。
程序启动时会顺手清扫一次，判定顺序如下（任何一步不满足就跳过）：

1. 只处理名字匹配 `_MEI` + 十六进制串（含上次清理改名后的 `.__orphan__` 形态）；`%TEMP%` 下其它内容一律不碰。
2. 跳过当前进程自己的解包目录（`sys._MEIPASS`），绝不删正在使用的目录。
3. 跳过 30 分钟内还在变化的目录（启动中的实例保护）。
4. 枚举所有进程已加载的模块，只要有一个落在该目录内就判定「使用中」并跳过。
5. 先改名成 `_MEI*.__orphan__*` 再删除；改名失败说明仍被锁定，直接跳过。
6. 单次最多删 20 个 / 2 GB，避免误伤。

- 之所以是「下次启动时清扫」而不是「退出时清扫」：进程退出前无法删除自己正在使用的目录，退出后才删又没有人执行；把清扫放在启动阶段最可靠。
- 手动触发并看明细：`PlanCheckBox.exe --clean-temp`（打印 removed / skipped 及原因）。
- 临时关闭：设置环境变量 `PLANCHECKBOX_NO_TEMP_CLEAN=1`。

**是否值得改用 onedir 根治？** 值得作为可选形态，但不必设为默认：

- onedir 不再解包，启动更快，也不会产生 `_MEI*` 残留，是「根治」方案；
- 代价是分发物从 1 个 exe 变成整个目录（至少 exe + `_internal/`），拷给别人或做单文件传输更麻烦，且目录结构被破坏就无法启动；
- 结论：**默认仍用 onefile（分发体验优先），把 `build\build.ps1 -Onedir` 作为内网/固定机器部署的可选形态**；onefile 的残留由上面的启动清扫兜住，两者不冲突。

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
| ⑤ | `%LOCALAPPDATA%\PlanCheckBox` | 上面都没有时的系统默认目录 |
| ⑥ | exe 同级 `PlanCheckBox-data\` | ⑤ 不可写时的降级（只读安装目录常见） |
| ⑦ | `Path.home()\PlanCheckBox` | ⑥ 也不可用时 |
| ⑧ | `%TEMP%\PlanCheckBox` | 最后兜底，会明确警告「关机可能丢失」 |

**某一层不可用时不会静默降级**：

- 配置里记住的目录失效（被删、换盘符、U 盘拔掉、无权限）→ 不改动原文件，临时换用下一个可用目录，并在界面顶部挂一条黄色提示，写明原路径和「请点顶栏『数据目录』重新选择」。
- `%LOCALAPPDATA%` 不存在/被组策略锁定/不可写 → 自动降级到 ⑥⑦⑧，同样给出提示；系统默认目录本身不可写时不会反复报错，也不会中断启动。
- 八层全部不可写（磁盘满、权限全锁）→ 弹出可读提示「找不到可写的数据目录」并列出尝试过的路径，**直接停止启动**，避免看起来能用但实际存不下数据。
- 目录可用但配置文件写不进去 → 明确报「配置文件写入失败」，不会假装已记住。
- 配置文件 `config.json` 优先写在 exe 同级（目录可写时）；exe 位于只读位置（如 `Program Files`、只读光盘/U 盘）时，自动改写到 `%LOCALAPPDATA%\PlanCheckBox\config.json`。
- 顶栏「数据目录」按钮会弹出系统选目录框，选择后立即生效并记住。
- 源码态（`launch.py`）下「exe 同级」即仓库根目录，因此便携探测看的是仓库根下的 `data\` / `docs\`。
- 分发给别人时最省事的做法：新建一个文件夹，放入 `PlanCheckBox.exe`，再建 `data\` 并把 `*_checkbox_use.json` 放进去。

## WebView2 运行时

程序使用系统自带的 Microsoft Edge WebView2 Runtime。Windows 10/11 一般已内置；
若启动时提示「未检测到 WebView2 Runtime」，请到 Microsoft 官网下载 **Evergreen Bootstrapper** 安装后重开。
本程序不会自动联网下载或安装任何组件；缺失时只会弹出可读提示，不会崩溃。

## 数据契约

### 题库文件（只读）

你选择的 `*_checkbox_use.json` 只提供「这份计划是什么」与任务树：

```
{ meta: {groupName, subject, kind, priority, examDate, planStart, generatedAt, version},
  months: [ {id, label, weeks: [ {id, index, label, start, end,
             days: [ {date, type, tasks: [ {id, title, priority, kind, topic,
                                              minutes, slot} ]} ]} ]} ]}
```

- 新格式的任务里**不需要** `done` / `doneAt` / `history`；即使写了也会被忽略（进度以进度文件为准）
- 未知字段（如 `day.note`、任务自定义字段）原样保留，程序绝不重写题库
- 缺 `meta`、`months` 为空、任务全部缺标题等情况会报错

### 进度文件（程序唯一会写的数据）

位置：**数据目录下的 `progress\` 子目录**，文件名为 `<题库名>_progress.json`（保留 `_checkbox_use`）：

```
<数据根>\progress\math2_checkbox_use_progress.json
```

- 题库放在 `<数据根>\banks\` 下或直接放在数据根下都一样，进度统一进 `<数据根>\progress\`
- `progress\` 不存在时首次勾选自动创建；创建失败会降级到题库同目录并在界面说明原因，勾选不受影响
- 旧版本写在题库同目录的进度文件仍会被读取；找到后自动迁移到 `progress\`（旧文件保留不动）

```
{ "format": "plancheckbox-progress",
  "version": 1,
  "source": { "hash": "<64 位 sha256>", "taskCount": 412,
              "generatedAt": "2026-11-04T16:00:00+08:00",
              "formatVersion": 1, "file": "math2_checkbox_use.json" },
  "updatedAt": "2026-11-06T09:10:00+08:00",
  "tasks": { "<taskId>": { "title": "…", "done": true,
                           "doneAt": "2026-11-06T09:10:00+08:00",
                           "history": [ {"action": "done", "at": "…"} ] } },
  "unmatched": { "task:<旧 id>": { "title": "…", "done": true, "doneAt": null,
                                   "history": [], "note": "题库中找不到对应任务（旧 id：…）" } } }
```

- 只记录有状态的任务；`done=false` 且没有时间/历史的任务不会占位
- `doneAt`：最近一次「勾选完成」的本地时间（带时区偏移）
- 取消勾选：`done=false`，`doneAt` 保留最近一次完成时间，`history` 追加 `undone`
- 重新勾选：`doneAt` 更新为本次时间，`history` 继续累积
- 写入是原子的（先写临时文件再替换），键按字典序排序，同一状态生成同样的文本

### 指纹与迁移

`source` 就是题库指纹，四要素缺一不可：**内容哈希**（meta 关键字段 + 全部任务的结构化 canonical JSON，排序后 sha256）、**任务总数**、**题库生成时间**（`meta.generatedAt`）、**题库格式版本**（`meta.version`）。

- **同指纹**：直接按 `taskId` 合并，不提示、不改写题库。
- **不同指纹**（题库被重新生成/改过）：按「taskId 优先、标题兜底」迁移，并在界面顶部与勾选提示里说明迁移了几条：
  1. `id` 相同且标题一致（或旧记录没存标题）→ 按 id 匹配；
  2. 剩下的按任务标题匹配（规范化空白后全等，一个新任务只用一次）；
  3. 再剩下的按 id 匹配（视作同一任务被重命名）；
  4. 仍匹配不上 → 原样保留在进度文件的 `unmatched` 区域，**绝不丢弃**，换回旧题库时还能继续用。
- 迁移完成后立即把新指纹写回进度文件，避免每次启动重复迁移。

### 老单文件格式的兼容

早期题库把 `done` / `doneAt` / `history` 内嵌在任务里。读取这类文件时：

1. 照常解析，勾选状态立即生效；
2. 若确实存在完成状态（`done=true` 或有历史），自动生成数据目录 `progress\` 下的 `_progress.json` 把状态搬过去；
3. **不修改、不删除原题库文件**，也不去掉里面的内嵌字段；
4. 之后所有读写都以进度文件为准；若进度文件已存在，则以进度文件为权威。
5. 进度文件损坏（不是合法 JSON / 不是本程序格式）时只读不写，并在界面提示「为避免覆盖已有记录，程序不会改写它」，不会静默重建。

## 让 AI 生成题库（没有现成文件时）

程序不内置任何题库，需要你自己准备 JSON。最省事的办法是让 AI 按固定结构生成一份：

1. 打开任意 AI 对话，把下面整段复制过去，按你的科目改掉【】里的内容。
2. 让它只输出 JSON。拿到后保存成 `math_checkbox_use.json`（文件名随意，建议 `科目_checkbox_use.json`，扩展名必须是 `.json`）。
3. 用记事本打开确认第一行是 `{`、最后一行是 `}`，没有 json 代码围栏（三个反引号）和多余说明文字。
4. 回到程序第一页点「选择文件」选中它。

可以直接复制的提示词：

```text
你是一个学习计划生成器。请严格按我给出的 JSON 结构，输出一份学习任务清单。
只输出 JSON 本身：不要解释、不要 Markdown 代码围栏、不要在 JSON 前后加任何文字。

我的情况：
- 科目名称：高等数学
- 计划开始日期：2026-11-09（必须是周一）
- 考试日期：2027-12-19
- 每天可学习：周一至周日，每天约 2 小时，晚上为主
- 需要覆盖的内容：极限、导数、积分、微分方程、级数（可换成你的教材目录）

结构要求（字段名一个字都不能改，层级不能变）：
{
  "meta": {
    "groupName": "高等数学",
    "subject": "高等数学",
    "kind": "study",
    "examDate": "2027-12-19",
    "planStart": "2026-11-09",
    "generatedAt": "2026-11-06T10:00:00+08:00",
    "version": 1
  },
  "months": [
    {
      "id": "2026-11",
      "label": "2026年11月",
      "weeks": [
        {
          "id": "2026-11-09",
          "index": 1,
          "label": "第1周",
          "start": "2026-11-09",
          "end": "2026-11-15",
          "days": [
            {
              "date": "2026-11-09",
              "type": "study",
              "tasks": [
                {
                  "id": "MATH-20261109-01",
                  "title": "高数：极限的定义与性质",
                  "topic": "极限",
                  "kind": "study",
                  "priority": "P1",
                  "minutes": 60,
                  "slot": "晚"
                }
              ]
            }
          ]
        }
      ]
    }
  ]
}

硬性规则：
1. months 从 planStart 所在月开始，一直覆盖到 examDate 所在月，中间不能缺月。
2. 每周 7 天：start 是周一、end 是周日；days 里每天都要有一条，没任务就写 "tasks": []。
3. 任务 id 全局唯一，格式 科目缩写-日期-序号。
4. priority 只能是 "P0"、"P1"、"P2"；kind 只能是 "study" 或 "fitness"。
5. minutes 是正整数（分钟）；slot 是自由文本，如 "早"、"午"、"晚"。
6. 任务里不要输出 done、doneAt、history，进度由程序单独保存。
7. 每天 1–3 个任务，单日总时长别超过我写的可学习时间。
8. 日期一律用 YYYY-MM-DD；带时间的一律用 2026-11-06T10:00:00+08:00 这种带时区的格式。
9. 只输出一份完整 JSON，不要省略号，不要注释，不要多余字段。
```

字段说明（想自己改或让 AI 改时用）：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `meta.groupName` | 建议 | 界面上显示的组名；缺失时用文件名回退 |
| `meta.subject` / `meta.kind` | 否 | `kind` 取 `study`（学习）或 `fitness`（健身），影响配色与月度汇总 |
| `meta.examDate` / `meta.planStart` | 建议 | `planStart` 用于「预计完成日」的兜底速率 |
| `meta.priority` | 否 | 组级默认优先级 `P0/P1/P2` |
| `months[].id` / `label` | 建议 | 形如 `2026-11` / `2026年11月`；缺失会按周起始日推算 |
| `weeks[].start` / `end` | **必填** | 周一 / 周日；`start` 非法该周会被跳过 |
| `weeks[].index` / `label` | 否 | 缺失按顺序补 |
| `days[].date` | **必填** | `YYYY-MM-DD`；非法日期会被跳过 |
| `days[].type` | 否 | 当天类型，任务没写 `kind` 时继承它 |
| `tasks[].title` | **必填** | 任务标题；缺标题的任务会被丢弃 |
| `tasks[].id` | 建议 | 缺了会自动生成；**同组内 id 重复会共用完成状态** |
| `tasks[].topic` | 否 | 板块名，用于总览页分组显示 |
| `tasks[].priority` | 否 | `P0/P1/P2`，非法值按 `P2` |
| `tasks[].minutes` | 否 | 分钟数，非法按 0 |
| `tasks[].slot` | 否 | 时间段文本，如「早」「午」「晚」 |
| `tasks[].done` / `doneAt` / `history` | 否 | 旧格式才会内嵌；新格式建议不写，程序只读题库、进度写入 `_progress.json` |

除以上字段外，多写的字段会被原样保留但界面不显示；缺 `meta`、`months` 为空、所有任务都缺标题会直接报告「没有解析到任何任务」。

## 界面四页

1. **选择任务**：多选 / 追加 / 移除 / 清空；显示名取 `meta.groupName`，缺失回退文件名；按任务数从高到低排列
2. **总览**：整年热力图（周一起始，0 / 1–2 / 3–5 / 6+ 四档，按 `doneAt` 本地日期、按任务 id 去重）、
   全部科目月历、每任务一条横条（组名 + 确定性配色 + 板块月份 + 进度 + 预计完成）
3. **月度**：只显示本组类型的一条进度条、42 格月历（P0→P1→P2、已完成下沉、健身绿色、当日总分钟）、月份卡片（完成月沉底）
4. **周度**：本周一条或两条进度条（学习组显示学习 + 健身）、周卡原地展开、勾选即时写入 `_progress.json`

预计完成时间：近 14 天加权速率（近 7 天权重 2），无近期记录退回 `planStart` 整体均值，速率过低显示「数据不足」。

## 已知限制

- 界面依赖 WebView2；极小概率在无 Edge 的环境需要手动安装运行时
- **WebView2 窗口启动抖动 / CPU 自旋（偶发）**：现象是双击后窗口迟迟不出现、或进程占着 CPU 空转；`--diag` 会报 `Main window failed to start`。影响只是一次启动失败，题库与进度文件不会被改动。绕行办法：结束进程后重启程序；仍反复出现则改用 onedir 版本（`PCB_ONEDIR=1` 打包，不再解包到 `%TEMP%`）。表现为环境相关（source 态与 onedir 态均稳定），**本轮决定不追查**，若在实际使用中频繁复现再排查
- GUI 已用 `--diag`（回读 DOM）+ 窗口标题变化验证可启动、能渲染；无交互桌面时无法做像素级截图
- 导入进度只更新内存状态（与 HTML 版一致），重新勾选即写入进度文件；不批量回写磁盘
- 题库改动（换 id、改标题、增删任务）会触发进度迁移：先 id、再标题、再 id 重命名，仍匹配不上的进 `unmatched`；但**同一时刻多处同时编辑同一个题库**时，以最后一次读到的进度文件为准
- `history` 不设上限，长期使用后单任务记录会变长
- 同级 `data\` / `docs\` 的优先级高于 `%LOCALAPPDATA%`：把 exe 放进含 `docs\` 的目录会自动沿用该目录，属预期行为；想固定到别处可用顶栏「数据目录」或 `PLANCHECKBOX_DATA_DIR`
- 分发给别人时只需要 exe（+ 可选 `data\`）；把 exe 单独拷到空目录也能启动，此时数据目录回退到 `%LOCALAPPDATA%\PlanCheckBox`
- `_MEI*` 清扫只处理名字匹配的目录；若残留目录正被其它 PyInstaller 程序使用，会被跳过并在下次启动时再尝试，不会强删
