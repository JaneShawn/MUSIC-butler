"""
Streamlit Web App - 音乐库管理界面（含智能歌单、元数据诊断、实时监控）
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import yaml
from datetime import datetime

from agents import LibrarianAgent, ScoutAgent, CuratorAgent, OrganizerAgent


st.set_page_config(
    page_title="Music Agent",
    page_icon="🎵",
    layout="wide"
)


@st.cache_resource
def load_config():
    with open("config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


config = load_config()


@st.cache_resource
def init_agents(_config):
    librarian = LibrarianAgent(_config)
    scout = ScoutAgent(_config)
    curator = CuratorAgent(_config, librarian)
    organizer = OrganizerAgent(_config, librarian)
    return librarian, scout, curator, organizer


@st.cache_resource
def init_folder_watcher(_config):
    from core.folder_watcher import FolderWatcher
    library_path = _config.get("library", {}).get("path", "")
    music_dir = str(Path(library_path) / "MUSIC") if library_path else "../MUSIC"
    album_dir = str(Path(library_path) / "ALBUM") if library_path else "../ALBUM"
    return FolderWatcher(watch_dirs=[music_dir, album_dir])


@st.cache_resource
def init_playlist_engine(_librarian):
    from core.playlist_engine import SmartPlaylistEngine
    from core.kimi_client import KimiClient
    try:
        from graph.utils import load_config
        kimi = KimiClient(config=load_config())
    except ValueError:
        kimi = None
    return SmartPlaylistEngine(librarian=_librarian, kimi_client=kimi)


@st.cache_resource
def init_metadata_scheduler(_librarian):
    from core.metadata_scheduler import MetadataScheduler
    return MetadataScheduler(librarian=_librarian)


librarian, scout, curator, organizer = init_agents(config)
folder_watcher = init_folder_watcher(config)
folder_watcher.set_librarian(librarian)
playlist_engine = init_playlist_engine(librarian)
metadata_scheduler = init_metadata_scheduler(librarian)


# ============================================================
# 侧边栏导航
# ============================================================
st.sidebar.title("🎵 Music Agent")
page = st.sidebar.radio(
    "导航",
    ["首页", "音乐库", "发现", "周报", "整理", "智能歌单", "元数据诊断"]
)

# ============================================================
# 首页
# ============================================================
if page == "首页":
    st.title("Music Agent - 智能音乐库管理")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric(label="音乐库", value=f"{librarian.get_stats()['total_songs']} 首")
    with col2:
        st.metric(label="艺术家", value=f"{librarian.get_stats()['artists']} 位")
    with col3:
        st.metric(label="专辑", value=f"{librarian.get_stats()['albums']} 张")

    st.divider()

    # --- 实时监控 Toggle ---
    st.subheader("📁 实时监控")
    mon_col1, mon_col2 = st.columns([1, 3])
    with mon_col1:
        monitor_on = st.toggle(
            "开启实时监控",
            value=folder_watcher.is_running,
            help="监控 MUSIC/ 和 ALBUM/ 目录，检测文件新增/删除自动处理"
        )
    with mon_col2:
        if monitor_on and not folder_watcher.is_running:
            folder_watcher.start()
            st.success("✅ 实时监控已启动")
        elif not monitor_on and folder_watcher.is_running:
            folder_watcher.stop()
            st.info("⏸️ 实时监控已停止")
        elif monitor_on:
            st.caption(f"监控运行中 — 目录: {', '.join(folder_watcher.get_status().get('watch_dirs', []))}")
        else:
            st.caption("监控已关闭")

    st.divider()

    # --- 快速操作 ---
    st.subheader("快速操作")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🔄 扫描音乐库", use_container_width=True):
            with st.spinner("正在扫描..."):
                result = librarian.run("scan")
                st.success(f"扫描完成！发现 {result['new_songs']} 首新歌")
                st.info(f"总计：{result['total_indexed']} 首")
    with col2:
        if st.button("🔍 发现新音乐", use_container_width=True):
            with st.spinner("正在搜索..."):
                candidates = scout.run("all")
                if candidates:
                    recommendations = curator.run("evaluate", candidates=candidates)
                    st.success(f"发现 {len(recommendations)} 首推荐")
                    st.session_state["latest_recommendations"] = recommendations
                else:
                    st.warning("暂时没有发现新音乐")

# ============================================================
# 音乐库页面
# ============================================================
elif page == "音乐库":
    st.title("我的音乐库")

    query = st.text_input("搜索歌曲（支持自然语言）",
                         placeholder="例如：周杰伦的歌、适合下雨听的国语歌")

    if query:
        results = librarian.query(query, top_k=10)
        if results:
            st.write(f"找到 {len(results)} 首相关歌曲：")
            for i, item in enumerate(results):
                song = item["song"]
                with st.container():
                    col1, col2 = st.columns([3, 1])
                    with col1:
                        st.write(f"**{song.title}** - {song.artist}")
                        st.caption(f"专辑: {song.album} | 流派: {song.genre or '未知'}")
                    with col2:
                        st.progress(item["similarity"], text=f"匹配度: {item['similarity']:.1%}")
                    st.divider()
        else:
            st.info("没有找到匹配的歌曲")
    else:
        stats = librarian.get_stats()
        st.subheader("库统计")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("总歌曲", stats["total_songs"])
        col2.metric("艺术家", stats["artists"])
        col3.metric("专辑", stats["albums"])
        col4.metric("流派", stats["genres"])

# ============================================================
# 发现页面
# ============================================================
elif page == "发现":
    st.title("🔍 音乐发现")

    source = st.selectbox("数据源", ["all", "rss", "reddit"])

    if st.button("开始搜索", type="primary"):
        with st.spinner("侦察兵正在工作..."):
            candidates = scout.run(source)
            if candidates:
                recommendations = curator.run("evaluate", candidates=candidates)
                st.success(f"发现 {len(candidates)} 首候选，{len(recommendations)} 首推荐")
                for rec in recommendations:
                    with st.container():
                        col1, col2 = st.columns([3, 1])
                        with col1:
                            st.write(f"**{rec.candidate.title}** - {rec.candidate.artist}")
                            st.caption(f"来源: {rec.candidate.source}")
                            st.write(f"💡 {rec.match_reason}")
                        with col2:
                            st.badge(rec.action.replace("_", " ").title())
                            st.write(f"相似度: {rec.similarity_score:.2f}")
                        st.divider()
            else:
                st.info("没有发现新音乐")

# ============================================================
# 周报页面
# ============================================================
elif page == "周报":
    st.title("📊 每周音乐报告")

    if "latest_recommendations" in st.session_state:
        recs = st.session_state["latest_recommendations"]
        report = curator.run("report", recommendations=recs)
        st.header(report["title"])
        summary = report["summary"]
        col1, col2, col3 = st.columns(3)
        col1.metric("本周发现", summary["total_discovered"])
        col2.metric("强烈推荐", summary["highly_recommended"])
        col3.metric("涉及流派", len(summary["genres"]))
        st.divider()
        st.subheader("本周推荐")
        for rec in report["recommendations"]:
            with st.expander(f"{rec['artist']} - {rec['title']}"):
                st.write(f"**流派**: {', '.join(rec['genre'])}")
                st.write(f"**推荐理由**: {rec['reason']}")
                st.write(f"**来源**: {rec['source']}")
                st.write(f"**匹配度**: {rec['score']}")
    else:
        st.info("还没有生成报告，先去【发现】页面搜索新音乐吧！")

# ============================================================
# 整理页面
# ============================================================
elif page == "整理":
    st.title("📁 音乐文件整理")

    st.subheader("📊 当前目录分析")
    if st.button("分析当前结构"):
        with st.spinner("正在分析..."):
            analysis = organizer.run("analyze")
            col1, col2, col3 = st.columns(3)
            col1.metric("总歌曲", analysis["total_songs"])
            col2.metric("艺术家数", analysis["artists_count"])
            col3.metric("流派数", analysis["genres_count"])
            st.info(f"💡 推荐整理策略: **{analysis['suggestion']}**")
            st.subheader("最常听的艺术家")
            top_artists = analysis["top_artists"][:5]
            for artist, count in top_artists:
                st.write(f"- {artist}: {count}首")

    st.divider()

    st.subheader("🗂️ 执行整理")
    strategy = st.selectbox(
        "整理策略",
        ["artist/album", "artist", "album", "genre", "year", "genre/artist", "year/artist"],
        help="选择文件分类方式"
    )

    col1, col2 = st.columns(2)
    with col1:
        dry_run = st.checkbox("仅预览（不实际移动文件）", value=True)
    with col2:
        keep_original = st.checkbox("保留原文件（复制而非移动）")

    if st.button("生成整理计划", type="primary"):
        with st.spinner("正在生成计划..."):
            from agents.organizer import OrganizeStrategy
            plan = organizer.run("plan", strategy=OrganizeStrategy(strategy))
            preview = organizer.preview_plan(plan)
            st.session_state["organize_plan"] = plan
            st.session_state["organize_preview"] = preview
            summary = preview["summary"]
            st.success("计划生成完成！")
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("总文件", summary["total_files"])
            col2.metric("将移动", summary["to_move"])
            col3.metric("将复制", summary["to_copy"])
            col4.metric("跳过", summary["skip"])
            if summary["conflicts"] > 0:
                st.warning(f"⚠️ 检测到 {summary['conflicts']} 个文件名冲突（将自动重命名）")
            st.subheader("整理示例")
            for ex in preview["examples"][:3]:
                st.code(f"{ex['action'].upper()}: {Path(ex['from']).name}\n  → {Path(ex['to']).name}")

    if "organize_plan" in st.session_state:
        if dry_run:
            st.info("☝️ 当前为预览模式，实际文件不会被移动。取消'仅预览'选项后可执行整理。")
        else:
            if st.button("🚀 执行整理", type="primary"):
                with st.spinner("正在整理文件..."):
                    plan = st.session_state["organize_plan"]
                    result = organizer.run("execute", plan=plan, dry_run=False)
                    st.success(f"整理完成！成功: {result.executed}, 失败: {result.failed}")
                    if result.failed > 0:
                        with st.expander("查看失败的文件"):
                            for detail in result.details:
                                if detail["status"] == "failed":
                                    st.error(f"{detail['from']}: {detail.get('error', 'Unknown')}")

# ============================================================
# 智能歌单页面 (NEW)
# ============================================================
elif page == "智能歌单":
    st.title("🎧 智能歌单")

    tab1, tab2 = st.tabs(["✨ 创建歌单", "📋 我的歌单"])

    # --- Tab 1: 创建 ---
    with tab1:
        st.subheader("用自然语言描述你想听的歌")
        nl_query = st.text_input(
            "描述你想听的音乐",
            placeholder="例如：适合下雨天听的国语慢歌、90年代粤语经典、周杰伦风格的歌...",
            key="playlist_query"
        )
        col1, col2 = st.columns([1, 3])
        with col1:
            is_dynamic = st.checkbox("动态歌单", value=False,
                                     help="动态歌单每次打开会重新查询，保持结果最新")
        with col2:
            playlist_name = st.text_input("歌单名称（可选）",
                                          placeholder="留空则自动生成",
                                          key="playlist_name")

        if st.button("🎵 生成歌单", type="primary", use_container_width=True):
            if not nl_query.strip():
                st.warning("请输入歌曲描述")
            else:
                with st.spinner("正在理解你的需求并搜索歌曲..."):
                    result = playlist_engine.create_playlist(
                        query_text=nl_query,
                        name=playlist_name or None,
                        is_dynamic=is_dynamic,
                    )
                st.success(f"✅ 歌单「{result['name']}」创建成功！共 {result['song_count']} 首")
                st.info(f"📄 已保存: `{result['m3u8_path']}`")

                # 解析意图
                with st.expander("🔍 查看查询解析"):
                    st.json(result["intent"])

                # 歌曲预览
                if result["songs"]:
                    st.subheader(f"歌曲列表（前 20 首）")
                    for s in result["songs"][:20]:
                        st.write(f"- **{s['artist']}** — {s['title']}  `{s.get('genre', '')}`")

    # --- Tab 2: 浏览 ---
    with tab2:
        st.subheader("已保存的智能歌单")
        playlists = playlist_engine.list_playlists()

        if not playlists:
            st.info("还没有智能歌单，去创建第一个吧！")
        else:
            for pl in playlists:
                pl_id = pl["id"]
                with st.expander(
                    f"{'🔄' if pl.get('is_dynamic') else '📋'} {pl['name']} "
                    f"({pl.get('song_count', 0)} 首) — {pl.get('created_at', '')[:10]}"
                ):
                    st.caption(f"查询: {pl.get('query_text', '')}")
                    st.caption(f"M3U8: `{pl.get('m3u8_path', '')}`")

                    col1, col2, col3 = st.columns(3)
                    with col1:
                        if pl.get("is_dynamic"):
                            if st.button("🔄 刷新", key=f"refresh_{pl_id}"):
                                with st.spinner("刷新中..."):
                                    updated = playlist_engine.refresh_dynamic_playlist(pl_id)
                                    if updated:
                                        st.success(f"已刷新！{updated['song_count']} 首")
                                        st.rerun()
                    with col2:
                        detail = playlist_engine.get_playlist(pl_id)
                        if detail and detail.get("songs"):
                            st.write("**歌曲列表:**")
                            for s in detail["songs"][:10]:
                                st.write(f"- {s['artist']} — {s['title']}")
                    with col3:
                        if st.button("🗑️ 删除", key=f"del_{pl_id}"):
                            playlist_engine.delete_playlist(pl_id)
                            st.success("已删除")
                            st.rerun()

# ============================================================
# 元数据诊断页面 (NEW)
# ============================================================
elif page == "元数据诊断":
    st.title("🔬 元数据诊断与修复")

    # --- 诊断 ---
    if st.button("🔍 运行诊断", type="primary"):
        with st.spinner("正在扫描元数据..."):
            diag = metadata_scheduler.diagnose()
            st.session_state["diagnosis"] = diag

    if "diagnosis" in st.session_state:
        diag = st.session_state["diagnosis"]

        st.subheader("📊 诊断结果")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("总歌曲", diag.get("total", 0))
        col2.metric("缺少艺术家", diag.get("missing_artist", 0),
                    delta=None if diag.get("missing_artist", 0) == 0 else f"⚠️ {diag.get('missing_artist', 0)}")
        col3.metric("缺少情绪标签", diag.get("missing_emotion", 0))
        col4.metric("歌词字段异常", diag.get("has_lyrics_issue", 0))

        total_issues = diag.get("total_issues", 0)
        if total_issues > 0:
            st.warning(f"⚠️ 发现 {total_issues} 个问题需要修复")

            # 展示问题详情
            with st.expander("📋 问题详情"):
                if diag.get("songs_missing_artist"):
                    st.write(f"**缺少艺术家** ({len(diag['songs_missing_artist'])} 首):")
                    for fp in diag["songs_missing_artist"][:20]:
                        st.caption(fp)
                if diag.get("songs_missing_emotion"):
                    st.write(f"**缺少情绪标签** ({len(diag['songs_missing_emotion'])} 首):")
                    for fp in diag["songs_missing_emotion"][:20]:
                        st.caption(fp)
                if diag.get("songs_has_lyrics_issue"):
                    st.write(f"**歌词字段异常** ({len(diag['songs_has_lyrics_issue'])} 首):")
                    for fp in diag["songs_has_lyrics_issue"][:20]:
                        st.caption(fp)
        else:
            st.success("✅ 所有元数据完整，没有问题！")

        st.divider()

        # --- 修复操作 ---
        st.subheader("🛠️ 修复操作")

        col1, col2, col3 = st.columns(3)

        with col1:
            st.markdown("**情绪缓存同步**")
            st.caption("从 emotion_cache.json 同步情绪标签到数据库")
            if st.button("🔄 同步情绪缓存", use_container_width=True):
                with st.spinner("同步中..."):
                    count = metadata_scheduler.sync_emotion_cache()
                    st.success(f"已同步 {count} 首歌曲的情绪标签")
                    # Refresh diagnosis
                    st.session_state["diagnosis"] = metadata_scheduler.diagnose()
                    st.rerun()

        with col2:
            st.markdown("**修复歌词字段**")
            st.caption("将文本 '是/否' 转为整数 1/0")
            if st.button("🔧 修复歌词字段", use_container_width=True):
                with st.spinner("修复中..."):
                    fixed = metadata_scheduler.fix_has_lyrics_field()
                    st.success(f"已修复 {fixed} 条记录")
                    st.session_state["diagnosis"] = metadata_scheduler.diagnose()
                    st.rerun()

        with col3:
            st.markdown("**修复缺失元数据**")
            st.caption("在线搜索补全 artist/title/cover")
            batch_size = st.number_input("每批处理数量", 5, 100, 20, key="fix_batch")
            if st.button("🚀 一键修复元数据", use_container_width=True, type="primary"):
                with st.spinner(f"正在修复（每批 {batch_size} 首）..."):
                    result = metadata_scheduler.execute_fix(batch_size=batch_size)
                    st.success(
                        f"修复完成！"
                        f"元数据: {result.get('metadata_fixed', 0)} 首, "
                        f"封面: {result.get('covers_embedded', 0)} 首, "
                        f"歌词字段: {result.get('lyrics_field_fixed', 0)} 条"
                    )
                    if result.get("failed", 0) > 0:
                        st.warning(f"{result['failed']} 首修复失败")
                    st.session_state["diagnosis"] = metadata_scheduler.diagnose()
                    st.rerun()

        # --- 修复历史 ---
        st.divider()
        st.subheader("📝 修复历史")
        history = metadata_scheduler.get_fix_history(limit=20)
        if history:
            for h in history:
                status_icon = "✅" if h.get("status") == "success" else "❌"
                st.caption(
                    f"{status_icon} {h.get('created_at', '')[:19]} | "
                    f"{h.get('fix_type', '')} | "
                    f"{Path(h.get('file_path', '')).name} | "
                    f"{h.get('old_value', '')} → {h.get('new_value', '')}"
                )
        else:
            st.caption("暂无修复记录")


# ============================================================
# 页脚
# ============================================================
st.sidebar.divider()
st.sidebar.caption("Music Agent v1.0")
