# 声形 · Sound & Form

**一个本地资料库，同时管理声音与形体。**  
把音频、角色、模型、骨骼动作、贴图和工程文件放进一个或多个文件夹，用同一张表整理：自动分类、音效细类、自由标签、收藏，以及安全的批量重命名。

零依赖、纯 Python 标准库、全部数据留在自己的电脑里。没有账号，没有上传。

![声形欢迎页](docs/screenshots/welcome.png)

> 截图里的素材是**合成的演示库**，只用于展示界面。图中的「音效 12 / 动作 12」不是你的素材数量，也不是扫描上限；实际数量以你添加的文件夹为准。

## 先看这里：怎么安装、怎么用

声形不是 `.exe` 安装包，而是一个 Python 本地应用。**不需要 `pip install`，不需要 Node.js，也不需要数据库。**

### Windows 五步运行

1. **下载并解压**  
   打开 <https://github.com/Surtr122/sound-isle>，点 **Code → Download ZIP**。  
   解压到你喜欢的任意位置即可，**路径和文件夹名都不用照抄**。GitHub 一般会把文件夹叫 `sound-isle-main`，但以你实际解压出来的为准。

2. **安装 Python 3.10+**  
   到 <https://www.python.org/downloads/> 下载安装。安装时一定要勾选 **Add python.exe to PATH**。

3. **进入解压后的文件夹**  
   打开解压出来的文件夹，确认里面能看到 `app.py` 和 `start-windows.bat`。  
   如果解压后多套了一层同名文件夹，就再点进去一层，直到看到这两个文件。

4. **启动（推荐双击）**  
   直接双击 **`start-windows.bat`**。它会自动切换到自身所在目录，所以**解压到哪都不用改路径，也不用 `cd`**。  
   如果双击没反应，就在这个文件夹空白处按住 `Shift` 点右键，选择“在此处打开 PowerShell 窗口”，然后执行：

   ```powershell
   python app.py
   ```

   浏览器会自动打开 `http://127.0.0.1:8765`。没有自动打开就手动访问这个地址。

5. **添加素材**  
   进入页面后点 **「添加文件夹」**，选择音效、动作、模型、贴图目录。可以一次添加多个文件夹，它们会合并到同一张表里。

> 如果 `python` 打开的是微软商店，说明 Python 没有装好；重新安装 Python，或改用 `py app.py`。  
> 如果端口被占用：`python app.py --port 8766`，然后访问 `http://127.0.0.1:8766`。

### 第一次打开后先做什么

1. 点 **「添加文件夹」**，先把 `音效` 目录加进来；
2. 再点一次 **「添加文件夹」**，把 `动作` / `模型` 目录也加进来——不是替换，是追加；
3. 在表格里勾选素材，底部会出现批量操作条；
4. 点分类卡会打开「抽屉」，可以试听、预览、改分类；
5. 点音效或动作详情里的按钮，可以试听、骨骼预览或蒙皮预览。

### 它会改我的文件吗

- 读取素材时只读，不会转码、移动或删除文件；
- 标签、收藏、分类、保存视图都存在 `%APPDATA%\SoundAndForm`，不写进素材目录；
- **只有你主动执行「应用重命名」时才会改文件名**，而且只改文件名，不改内容、不改后缀。

### 卸载

删除解压出来的 `sound-isle-main` 文件夹即可。若想连标签和收藏一起清掉，再删除 `%APPDATA%\SoundAndForm`。

> macOS / Linux 用户：安装 Python 3.10+ 后，在项目目录执行 `python3 app.py`。详细命令行参数见下方「从源码运行（命令行）」。

## 多个文件夹，一张表

做动画、做游戏或做声音的人，素材通常散在好几个目录里：音效库、动作库、角色库各自成家。声形不要求你搬家，也不给音频和 3D 各建一个软件，而是把这些目录一起收进同一张可筛选的列表：

- 可以添加多个文件夹，每个根目录及其子文件夹都会被扫描；统一查看，而不是切换当前库；
- 来源会显示在页面顶部，可以随时再加一个文件夹，或移除其中一个来源；移除只影响视图，不删除磁盘文件；
- 音频和 3D / 2D 资产共用标签、收藏、搜索、排序与批量重命名；
- 音频可以播放，3D 资产可以打开结构详情，BVH / GLB / glTF / FBX 动作可以播放骨骼预览；
- 分类分成「声音的七个抽屉」和「形体的八个抽屉」，但都在同一个库里；音效还能继续细分为脚步、叹息、攻击等，动作也能细分为待机、走路、跑步、跳跃等；
- 分类不是死的：可以手动改类、恢复自动判断，也可以自己新建抽屉；
- 所有状态只存在本机，不写入素材文件夹。

![全部素材：合成演示库顶部是两个来源，音效 12 项与动作 12 项合并查看](docs/screenshots/library.png)

## 五个核心动作

### 1. 默认排序

默认按**相对路径自然排序**，所以 `第2章` 会排在 `第10章` 前面，`动作/走路 2` 也不会跑到 `动作/走路 10` 后面。也可以切换为名称、作者 / 角色、时长、最近修改或大小。

### 2. 自动分类：十五个内置抽屉，外加自己的抽屉与细类

分类规则是透明、可解释的，不是黑盒模型。每条素材都会显示分类依据和置信度；不满意时，可以手动改到别的抽屉，也可以恢复自动分类。

**声音（7 类）**

| 分类 | 主要线索 |
| --- | --- |
| 歌曲 | 「歌手 - 曲名」结构、常见歌曲时长、流派标签 |
| 纯音乐 | 伴奏 / 纯音乐 / 钢琴 / 器乐 / OST / BGM |
| 播客 | 播客 / 电台 / 访谈 / Episode / 节目编号 |
| 有声书 | 有声书 / 广播剧 / 朗读 / 第 N 章 |
| 课程 | 课程 / 教程 / 讲座 / Lecture / Lesson |
| **音效** | **短于 22 秒**，或路径 / 元数据含音效、环境声、SFX、Foley |
| 其他 | 线索不足，先放在这里 |

**形体（8 类）**

| 分类 | 主要线索 |
| --- | --- |
| 骨骼动作 | `.bvh` `.anim` `.trk` `.clip`，或 walk / run / idle / pose |
| 角色 | 角色 / character / hero / NPC，或 GLB / FBX 中带角色线索 |
| 道具 | prop / weapon / item / 道具 |
| 场景 | scene / level / terrain / 场景 |
| 材质贴图 | `.png` `.jpg` `.exr` `.psd` 等，或 albedo / normal / PBR |
| 工程文件 | `.blend` `.ma` `.max` `.c4d` `.uproject` 等 |
| 模型 | `.glb` `.gltf` `.fbx` `.obj` `.usd` 等 |
| 其他 | 文档、压缩包、未知格式 |

规则按优先级执行：**工程 → 贴图 → 动画 → 角色 → 道具 → 场景 → 动作 → 模型 → 其他**。

**音效还能再细分。** 音效抽屉里有 11 个细类：脚步、叹息、攻击、水、火、动物、机械、界面、拟音、环境、其他。判断依据仍是文件名和路径关键词，所以「脚步 01.wav」「攻击_重击.wav」会自动落到对应细类；不准确的可以随时改。

**动作也能再细分。** 骨骼动作抽屉里有 10 个细类：待机、走路、跑步、跳跃、攻击、受击、死亡、舞蹈、手势表情、其他。「待机循环.bvh」「walk_01.bvh」「受击倒地.bvh」会按文件名落到对应细类。

**点开抽屉，而不是只看数字。** 点分类卡会打开一个抽屉：里面列出这一类素材，声音可以逐条试听，资产可以打开详情；音效和动作抽屉顶部都有细类 chips。每一行右侧都可以直接「骨骼预览」「蒙皮预览」「复制路径」「编辑标签」「调整分类」，预览结束会回到原来的抽屉，不用先回表格。抽屉底部可以回到表格继续筛选。

移动分类时，如果选中的是音效，会直接出现「音效细类」；选中的是动作，会出现「动作细类」。所以不用先回详情，就能把某个音效放进「脚步」、把某个动作放进「走路」。自定义小类也会出现在分类选择器里。

![在分类抽屉里直接预览动作，返回后仍留在原抽屉](docs/screenshots/drawer-preview.png)

**自己造一个抽屉。** 分类页、选择栏和分类选择器都可以新建分类，名称 1–24 个字，最多 40 个。自定义分类可以同时装声音和形体，也可以随时把素材移回自动分类。

![自动分类：声音](docs/screenshots/categories.png)

![自动分类：形体](docs/screenshots/categories-form.png)

![音效抽屉：细类、试听与分类操作](docs/screenshots/sfx-drawer.png)

![手动选择分类，或新建一个抽屉](docs/screenshots/category-picker.png)

![新建自定义分类或小类](docs/screenshots/create-category.png)

![大类下的小类：可以单独打开，也可以和父分类一起被找到](docs/screenshots/custom-drawers.png)

分类可以多选：一件素材可以同时放进「骨骼动作」和「角色」，也可以同时在「音效」和自建的「脚步细节」里；从抽屉行末的「移除」只会把它移出当前分类，不会删除文件。

### 3. 标签

标签不再单独占一个页面，而是像「便签」一样贴在素材上，用来做跨分类的筛选：

- 表格工具栏的「标签筛选」可以多选，选中多个标签时要求同时满足；
- 行内标签可以直接点击切换筛选；
- 批量添加、批量移除；详情里仍可编辑单个素材的标签；
- 大小写不敏感、自动去重，单个素材最多 30 个标签；
- 标签数据不会因为隐藏标签页而丢失，也不写入素材文件夹。

![按标签筛选](docs/screenshots/tag-filter.png)

**来源健康与重复检查。** 每个来源会记录上次扫描到的文件；文件被移走后会出现在「缺失」里，只影响索引，不会删除磁盘内容。相同大小的文件会进一步算内容指纹，列成「重复 N 组」，点进去可以查看两个文件。工具栏的「保存视图」会把当前的搜索、排序、类型、标签和收藏条件存到本机，下次一键恢复。

- `Ctrl/Cmd + A` 全选当前列表；
- 收藏、加标签、移动分类后可点提示条上的「撤销」，或按 `Ctrl/Cmd + Z` 撤回最近一次整理操作（不撤销已落盘的重命名）；
- 按住 `Shift` 点复选框可以从上一次勾选的位置连选；
- 把表格行拖到分类卡上，就能直接放进那个抽屉（多分类会保留原分类）。

![重复文件检查：只提示，不自动删除](docs/screenshots/source-health.png)

**资料备份。** 来源条上的「导出资料」会生成一份只包含标签、收藏、分类和小类归属的 JSON；「导入资料」按相对路径恢复到当前库。它不包含音频或模型本体，也不会移动、改名或改写素材文件，适合换电脑或重建索引后把整理结果带回来。

### 4. 收藏

收藏不依赖标签，也不改变文件位置。它只是一条本地记录，和播放器里的爱心、收藏页的计数保持同步；收藏页的「播放收藏声音」只播放其中的音频，不会把 3D 资产塞进播放队列。

![收藏页](docs/screenshots/favorites.png)

### 5. 批量重命名

在表格选择栏或分类抽屉的批量条里选中一批素材（抽屉支持全选、加标签、收藏、移动分类与重命名），输入统一名称、起始编号、位数和分隔符，先逐条预览，确认后再执行（默认分隔符是 `-`）：

- `岛上的素材-01.fbx`、`岛上的素材-02.obj`；
- 只改文件名，**不写入、不转码、不改变文件内容**；扩展名和所在文件夹不变；
- 执行前标出目标重名、源文件消失、文件名过长；
- 两阶段临时名执行，避免互换或循环命名时互相覆盖；
- 失败时尽量回滚；
- 标签、收藏与当前播放位置会跟着迁移。

![分类抽屉里的批量操作](docs/screenshots/drawer-batch.png)

![批量重命名预览](docs/screenshots/rename-preview.png)

## 3D 资产详情

音频行直接播放；资产行打开详情抽屉。声形读取的是文件结构，不做「假装能渲染一切」的事：

- GLB / glTF：网格、节点、材质、动作、蒙皮、贴图、图片、顶点数；带蒙皮和动画通道的文件可以打开「蒙皮预览」，用 Three.js 渲染网格、材质与动画，也可以切换「骨骼预览」只看骨架；
- BVH：骨骼数、帧数、帧时长、动作名；可以播放实时骨架预览，可暂停、拖帧；
- OBJ：顶点、面、对象、组；
- FBX：版本、动作与骨骼线索；支持二进制 FBX 7.x 与 ASCII FBX 的骨骼曲线预览；在浏览器端用 FBXLoader 尝试蒙皮预览，不处理约束与 IK；
- BLEND：Blender 版本；
- PNG / JPEG / WebP / GIF / PSD / DDS / TGA：尺寸；
- 常见图片贴图会显示缩略图，其他资产显示等轴测线框与分类标记。

![资产详情](docs/screenshots/detail.png)

![GLB 骨骼动画预览](docs/screenshots/motion-preview.png)

![带蒙皮、材质与动画的 GLB 预览，可返回详情](docs/screenshots/skin-preview.png)

![FBX 资产详情](docs/screenshots/fbx-detail.png)

![FBX 骨骼动画预览](docs/screenshots/fbx-preview.png)

## 播放器

播放器只处理音频。除了常规的播放、暂停、上一首、下一首、进度与音量，还支持 **0.75× / 1× / 1.25× / 1.5× 倍速**、**实时频谱可视化**，以及 **A/B 循环**：播放时点 A 记下起点、点 B 记下终点，之后每次到 B 就会跳回 A；`×` 清除循环。切歌会自动清掉上一首的 A/B 点。

**默认单曲循环。** 点击播放器右侧的循环按钮可以在「单曲循环」和「顺序播放」之间切换；顺序播放时一首结束会自动播放下一个音频，最后一首播完停止。循环模式会保存在本机。

右侧的波形按钮会读取当前音频并画出完整波形；音频只在浏览器内存中解码，不会生成新文件。点击波形任意位置即可跳到对应播放进度。

![播放器倍速与 A/B 循环](docs/screenshots/player-speed.png)

![音频波形与点击跳转](docs/screenshots/waveform.png)

## 混合列表

同一张表里，音频显示封面、艺术家、时长；资产显示线框、格式、体积与结构摘要。列会根据素材类型自动切换，不会强迫 3D 资产拥有「时长」。

![3D 资产表格](docs/screenshots/library-table.png)

![音频表格与播放器](docs/screenshots/library-audio.png)

![点击即可试听声音](docs/screenshots/playing.png)

![窄屏下的同一张表，播放器与选择栏不会撑破页面](docs/screenshots/mobile-library.png)

## 从源码运行（命令行）

要求：**Python 3.10+**，不需要安装任何第三方包。

```bash
git clone <your-fork-url> sound-isle
cd sound-isle
python app.py
```

浏览器会自动打开 <http://127.0.0.1:8765>。首次进入后输入文件夹路径，或点「从电脑选择」。这个文件夹可以只有音频、只有资产，也可以两者混在一起。

进入后可以继续点「添加文件夹」，把音效库、动作库、角色库合并到同一张表；顶部来源条可以分别移除某个来源，不会删除磁盘文件。

不自动开浏览器：

```bash
python app.py --no-browser
```

直接打开一个素材文件夹：

```bash
python app.py --library "D:\Assets"
```

### 命令行参数

```text
python app.py [--library PATH] [--port PORT] [--host HOST]
              [--no-browser] [--data-dir PATH] [--quiet] [--version]
```

| 参数 | 说明 |
| --- | --- |
| `-l, --library` | 启动时先打开的素材文件夹（之后可继续添加来源） |
| `-p, --port` | 本地端口，默认 `8765`，`0` 表示自动选择 |
| `--host` | 监听地址，默认 `127.0.0.1` |
| `--no-browser` | 不自动打开浏览器 |
| `--data-dir` | 自定义标签 / 收藏 / 分类覆盖的保存目录 |
| `--quiet` | 只输出必要信息 |

也可以用环境变量 `SOUNDANDFORM_LIBRARY` 指定默认文件夹，用 `SOUNDANDFORM_DATA_DIR` 覆盖数据目录。

## 数据与隐私

- 声形**不会上传**音频、模型、封面或标签；服务只监听本机回环地址。
- 标签、收藏、分类覆盖、来源文件夹列表保存在：
  - Windows：`%APPDATA%\SoundAndForm`
  - macOS：`~/Library/Application Support/SoundAndForm`
  - Linux：`$XDG_DATA_HOME/sound-and-form`（默认 `~/.local/share/sound-and-form`）
- 素材文件夹只被读取；只有在用户明确执行批量重命名时才写文件名。
- 不会在素材文件夹里生成标签数据库、封面缓存或隐藏文件。
- 兼容旧环境变量 `SOUNDISLE_DATA_DIR` / `SOUNDISLE_LIBRARY`，方便从 0.1 版迁移。

## 支持的格式

**音频**：`.mp3` `.flac` `.wav` `.m4a` `.m4b` `.aac` `.ogg` `.oga` `.opus` `.aiff` `.aif`

**模型 / 动画**：`.glb` `.gltf` `.fbx` `.obj` `.dae` `.3ds` `.stl` `.ply` `.usd` `.usda` `.usdc` `.usdz` `.abc` `.step` `.stp` `.igs` `.iges` `.x3d` `.wrl` `.vrm` `.bvh` `.anim` `.trk` `.clip`

**工程 / 材质**：`.blend` `.blend1` `.ma` `.mb` `.max` `.c4d` `.uproject` `.uasset` `.umap` `.unity` `.prefab` `.asset` `.zpr` `.ztl` `.spp` `.sbsar` `.hip` `.hipnc` `.fcstd` `.nk` `.nuke` `.mtl`

**贴图 / 图片**：`.png` `.jpg` `.jpeg` `.webp` `.gif` `.tga` `.exr` `.hdr` `.psd` `.tif` `.tiff` `.dds` `.ktx` `.ktx2`

**文档 / 压缩包**：`.zip` `.7z` `.rar` `.tar` `.gz` `.txt` `.md` `.pdf` `.doc` `.docx`

音频元数据为零依赖手写解析：MP3（ID3v1/v2、内嵌封面、Xing/VBRI/CBR）、FLAC、WAV、Ogg Vorbis/Opus、MP4/M4A/M4B、AIFF。损坏或未知文件不会中断扫描，会退回文件名信息。

## 开发

```text
sound-isle/
├─ app.py                     # 双击 / 命令行入口
├─ soundisle/
│  ├─ cli.py                  # 参数、启动、浏览器
│  ├─ server.py               # 本地 HTTP 服务、Range 流、缩略图、详情 API
│  ├─ library.py              # 单个来源的扫描、状态、标签、收藏、重命名编排
│  ├─ workspace.py            # 多来源合并、路由与跨来源批量操作
│  ├─ metadata.py             # 零依赖音频元数据
│  ├─ probe.py                # 零依赖 3D / 图片结构读取
│  ├─ classify.py             # 15 个内置分类 + 音效 / 动作细类
│  ├─ rename.py               # 预览、冲突检测、两阶段重命名
│  ├─ config.py               # 应用数据目录与原子 JSON
│  ├─ folder_picker.py        # 原生目录选择 / 在文件管理器中显示
│  └─ web/
│     ├─ index.html
│     └─ assets/{css,js}
├─ tests/test_core.py         # 36 个标准库 unittest
├─ scripts/                   # 演示素材、截图、浏览器流程测试
├─ docs/screenshots/
└─ .github/workflows/tests.yml
```

运行测试：

```bash
python -m unittest discover -s tests -v
```

测试只使用临时目录，不会读取或改动真实素材；当前 36 项全部通过。

浏览器流程（本机 Playwright + Edge，服务需先启动）：

```bash
BASE=http://127.0.0.1:8787 PW=<playwright-module-path> node scripts/test_ui.cjs
```

### 重新生成演示图

截图全部使用合成音频与合成 3D 资产，不含任何个人素材：

```bash
python scripts/make_demo_assets.py
python scripts/make_demo_library.py
python scripts/make_skin_demo.py
# 把 .demo-library 里的 WAV 与 .demo-assets 里的 3D 文件整理成两个来源
# 也可以用下面的方式直接生成最终演示目录：
python - <<'PY'
from pathlib import Path
import shutil
root = Path('.demo')
(root / '音效').mkdir(parents=True, exist_ok=True)
(root / '动作').mkdir(parents=True, exist_ok=True)
for p in Path('.demo-library').glob('*.wav'):
    shutil.copy2(p, root / '音效' / p.name)
shutil.copytree('.demo-assets', root / '动作', dirs_exist_ok=True)
for p in (root / '动作').rglob('测试三角.gltf'):
    p.unlink()
PY
python app.py --library '.demo/音效' --port 8787 --no-browser --data-dir .tmp-final-data
# 另一个终端：添加动作来源并写入演示标签 / 收藏 / 小类
python scripts/seed_demo.py
# 再运行截图（需要本机 Playwright + Edge）：
BASE=http://127.0.0.1:8787 PW=<playwright-module-path> node scripts/capture_docs_final.cjs
```

脚本会写入演示标签、收藏和两个小类，并截取欢迎页、混合总表、标签筛选、分类抽屉、批量条、选择器、蒙皮/骨骼预览、重命名和移动端等图。演示库只包含合成音频与合成资产。

生成的 `.demo/`、`.demo-library/`、`.demo-assets/` 与 `.tmp-*` 都被 gitignore。

## 已知边界

- 自动分类、音效细类与动作细类依据**路径、文件名、扩展名与文件结构**，不做音频内容识别，也不理解模型语义；分类结果可以随时手动覆盖或恢复自动，抽屉里也能逐行调整。
- 3D 详情读取的是文件元数据；骨骼预览只画关节与连线，不渲染网格。蒙皮预览用浏览器端 Three.js 渲染 GLB / glTF / FBX 的网格、材质与动画；FBX 的蒙皮效果取决于导出文件是否包含网格、蒙皮与动画通道。部分 FBX 只有骨骼/动作曲线，没有可显示网格，此时会提示并自动切到骨骼预览，不会停在空白画布。
- GLB / glTF 的 JSON chunk、BVH 头等有大小上限（24MB），动作预览最多采样 160 帧；超大文件会给出提示并退回基础信息。
- 浏览器决定实际可播放的音频格式；音频元数据读取不受浏览器编解码限制。
- 批量重命名不跨文件夹移动，也不改扩展名；批量「移动分类」只改资料库里的分类，不会移动磁盘文件。
- 每个来源文件夹的标签、收藏与分类覆盖分别保存；合并视图只是展示层，不会把两个目录真的合并成一个。
- 本地单用户工具，不是多用户服务器；默认只监听 `127.0.0.1`。

## License

[MIT](LICENSE)

---

如果它让你的素材文件夹安静了一点，欢迎 star、提 issue，或者把它改成你自己的「岛」。
