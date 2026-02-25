# TOOLS

## ABS 主工具链
- 音频预处理：
  - `/Users/panzm/Music/whitebull/skills/flac-skill/scripts/process_flac_strict.sh`
- 封面处理：
  - `/Users/panzm/Music/whitebull/skills/cover-skill/scripts/prepare_cover_strict.sh`
  - `/Users/panzm/Music/whitebull/skills/cover-skill/scripts/fetch_cover_online.py`
- 元数据生成：
  - `/Users/panzm/Music/whitebull/skills/album-skill/scripts/fetch_musicbrainz_db_strict.sh`
  - `/Users/panzm/Music/whitebull/absolutely/beethoven_DiscogsWgetRelease.sh`
- Runme 严格处理：
  - `/Users/panzm/Music/whitebull/skills/runme-skill/scripts/process_runme_strict.sh`
- 发布处理：
  - `/Users/panzm/Music/whitebull/skills/publish-skill/scripts/process_publish_strict.sh`

## 执行规则
- 优先使用 `skills/*/scripts/*_strict.sh`。
- 支持 `--json` 的脚本优先启用 `--json`。
- 在线检索优先使用明确 `release_id`，其次 catalog/搜索兜底。
- 每阶段都做产物验证：
  - 音频阶段：`.flac` / `.cue` 结构与可用性
  - 封面阶段：`cover.jpg`（及需要时 `back.jpg`）
  - 元数据阶段：`musicbrainz_0.db/.json` 或 `discogs_0.db/.json`
  - runme 阶段：`runme` 字段校验通过

## 默认禁止
- 绕开严格脚本做手工散改
- 依赖交互式编辑器完成关键流程
- 未通过校验直接发布
