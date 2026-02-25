#!/usr/bin/env bash
# WhiteBull‑Music‑Toolkit
# -----------------------
# 本工具集包含了一系列 Bash 与 Python 脚本，专门用于 FLAC 版音乐库的清理、打标签与整理。
# 目录结构与原始 CD 目录保持一致，脚本采用 **nix** 环境（bash、zsh、GNU 工具）编写，
# 本 README 说明了所需依赖、文件组织与常用工作流。

## 依赖项

以下工具均直接被脚本调用，可通过 Ubuntu（或 macOS）软件源安装。

| 工具 | 作用 | 安装命令 |
|------|------|-----------|
| **MPD** | 音乐播放守护进程（用于标签编辑回调） | `sudo apt install mpd` |
| **metaflac** | FLAC 标签处理 | `sudo apt install flac` |
| **kid3‑cli** | CLI 标签编辑器，复杂字段备选方案 | `sudo apt install kid3-cli` |
| **jq** | JSON 处理（composer 数据） | `sudo apt install jq` |
| **fzf** | 模糊查找器（可选，经常用于辅助脚本） | `sudo apt install fzf` |
| **shntool** | 单首歌曲拆分（用于 CD） | `sudo apt install shntool` |
| **ffmpeg** | 图像格式转换（png/bmp → jpg） | `sudo apt install ffmpeg` |
| **python‑3‑pip** | Python 依赖 | `sudo apt install python3-pip` |

Python 依赖（位于 `pyabs/`）
------------

```bash
pip install fuzzywuzzy python-Levenshtein
```

脚本默认在音乐库根目录下运行，即仓库根目录（`/Users/.../whitebull`）

## 目录结构

```
├── composer          # 通用 FLAC 处理脚本
│   ├── 1-composer_write_flac.sh      # 写入 composer 标签
│   ├── 1.2‑cue2compser.sh           # 从 CUE 提取 composer
│   └── …
├── pyabs            # Python 辅助工具（封面提取、标签同步等）
├── cases            # 示例工作流 & 测试脚本
├── flyflac           # CD 专用脚本（封面处理、拆分等）
├── data             # JSON / csv 数据库
├── imslp            # IMSLP 原始数据
└── doc              # 文档片段（2022_10_08.md 等）
```

> **命名约定**：`NN‑description.sh`
> - `NN`：工作流编号或组 ID
> - `description`：脚本功能简述
> 例如 `10‑mpd_clean.sh` 用于清理 MPD 数据库，`1‑composer_write_flac.sh` 用来给 FLAC 写 composer 字段。

## 文档与迁移指引

正在将 Bash/混合脚本迁移到统一的 Python CLI。相关文档：
- `docs/python-migration-plan.md`：总体迁移目标、架构与里程碑；新增 Dry‑run/日志/自检/回滚等规范。
- `docs/cli-parity.md`：旧脚本到新 CLI 的命令映射与示例调用。
- `docs/MIGRATION-SUPPLEMENT.md`：补充细节与每日≤2小时的文档完善计划。
- `docs/script_overview.md`：脚本概览，含迁移提示与交叉链接。
- `docs/nanobot-organizer.md`：面向 nanobot 的自动整理入口（CLI/API），支持“给源目录+目标目录”后批量整理。

如需使用新 CLI，请先阅读上述文档并确保依赖自检通过。

## 常见工作流

### 1. 导入新 CD
1. 将 CD 镜像（`*.cda` 或 `*.flac`）放入符合 `\[XXX YYY-Z\]  Artist - Title/` 规则的文件夹。
2. 运行对应的拆分脚本（以标准 CD 为例）：
   ```bash
   cd flyflac
   ./split_cd.sh "[XXX YYY-Z]  Artist - Title"
   ```
3. 把全部 CUE 轨道导出为单独 FLAC：
   ```bash
   cd composer
   ./1.5‑flac-export2cue.sh "[XXX YYY-Z]  Artist - Title"
   ```

### 2. 打标签 & 元数据
* **Composer 标签** – `composer/1‑composer_write_flac.sh` 根据文件夹名或 CUE 写入 *Composer* 字段。
* **外部数据库同步** – `pyabs/ravel_sync_tag-cache.sh` 拉取 MusicBrainz/Discogs 信息并写回 FLAC。
* **手工修正** – 当自动检测失败时，使用 `composer/1.4‑manual2composer.sh` 交互确认正确 composer。

### 3. 封面处理
所有封面工作集中在 `flyflac/torroba‑processCover.sh`。

```bash
cd flyflac
./torroba‑processCover.sh [debug]
```

该脚本完成：
* PNG/BMP 转 JPG
* 文件名规范化（小写、去除特殊字符）
* 将子目录（Artwork/、Cover/、Scan/ 等）中的图片移动到主目录
* 生成/更新 `cover.jpg`，供 MPD、播放器使用

### 4. 库清理
* `composer/4mpd_clean.sh`：删除孤立文件并统一文件夹命名
* `flyflac/decca‑CD‑year.sh`：自动填充专辑年份

### 5. 完整工作流

```bash
cd <album_folder>
../composer/1‑composer_write_flac.sh
../composer/1.2‑cue2compser.sh
../flyflac/torroba‑processCover.sh
../composer/4mpd_clean.sh
```

> **提示**：大多数脚本支持 `debug` 标志。加上该标志可以预览命令而不执行操作。

### 6. 录音查重与维护
- 使用 `pyabs/songv2_check_duplicate.py` 查询 `data/composer_album.lst`，避免重复整理同一作曲家的专辑或录音。
- 整理完新的录音后，请及时把 `Composer:Album (Performer - Year)` 形式的条目追加到 `data/composer_album.lst`，保持查重列表最新。

## 扩展 & 贡献

脚本采用 Bash + 轻量 Python 方案，便于移植。要添加新脚本，只需：
1. 在对应目录创建文件
2. 采用 `NN‑desc.sh` 命名
3. 在文件开头添加说明
4. 若脚本需要外部数据，更新 `data/` 目录
5. 如有单元测试，请在 `pyabs/` 添加测试用例

所有脚本均可通过 `pyabs` 里的单元测试验证：
```bash
cd pyabs
python -m unittest discover
```

---

### 常见问题

**Q**：为什么有这么多小脚本？

**A**：这是个人工具集，历年逐步扩展。小脚本便于试验与维护。

**Q**：如何更新 composer 数据库？

**A**：使用 OpenOPUS JSON：
```bash
wget -O data/opus_dump.json https://api.openopus.org/work/dump.json
```
然后用 `jq` 生成所需列表。

**Q**：文件夹名含非 ASCII 字符怎么办？

**A**：脚本会自动使用 `iconv`/`convmv` 正常化。手动批量转换：
```bash
find . -depth -name "*.flac" -exec convmv --notest --ascii {} -r 
```

**Q**：Windows 可用吗？

**A**：脚本针对类 Unix 环境，如需在 Windows 运行，需要 WSL、Git‑Bash 或 Cygwin。

---

祝你使用愉快，音乐文件整理顺利！
