"""
Streamlit Web App - 音乐库管理界面（含智能歌单、元数据诊断、实时监控）
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import yaml
from datetime import datetime

from hermes import WebTrigger
from agents import OrganizerAgent

# Hermes Trigger 层：标准化 Web 输入
web_trigger = WebTrigger(user_id="web")

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
    from agents.librarian import get_librarian
    librarian = get_librarian(_config)
    organizer = OrganizerAgent(_config, librarian)
    return librarian, organizer


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


librarian, organizer = init_agents(config)
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
    ["首页", "音乐库", "整理", "智能歌单", "元数据诊断"]
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
# ============================================================
# 音乐库页面
# ============================================================
elif page == "音乐库":
    from core.music_library_db import get_library_db
    lib_db = get_library_db()

    st.title("我的音乐库")

    # 初始化 session state
    if "lib_filter_artist" not in st.session_state:
        st.session_state.lib_filter_artist = "全部"
    if "lib_filter_album" not in st.session_state:
        st.session_state.lib_filter_album = "全部"
    if "lib_filter_genre" not in st.session_state:
        st.session_state.lib_filter_genre = "全部"
    if "lib_filter_lang" not in st.session_state:
        st.session_state.lib_filter_lang = "全部"
    if "lib_filter_emotion" not in st.session_state:
        st.session_state.lib_filter_emotion = "全部"
    if "lib_edit_song" not in st.session_state:
        st.session_state.lib_edit_song = None

    # ── 搜索栏 ──
    search_query = st.text_input("🔍 搜索",
        placeholder="歌名、艺术家名，或自然语言如 '适合下雨听的国语歌'")

    # ── 筛选器 ──
    with st.expander("📋 筛选", expanded=False):
        artists = ["全部"] + lib_db.list_artists()
        albums = ["全部"] + lib_db.list_albums()
        genres = ["全部"] + lib_db.list_genres()
        languages = ["全部"] + lib_db.list_languages()
        emotions = ["全部"] + [
            {"happy": "快乐", "sad": "悲伤", "energetic": "激情", "calm": "平静",
             "romantic": "浪漫", "nostalgic": "怀旧", "angry": "愤怒",
             "focus": "专注", "party": "派对"}.get(e, e)
            for e in lib_db.list_emotions()
        ]
        emotion_map = {
            "快乐": "happy", "悲伤": "sad", "激情": "energetic", "平静": "calm",
            "浪漫": "romantic", "怀旧": "nostalgic", "愤怒": "angry",
            "专注": "focus", "派对": "party",
        }

        c1, c2, c3 = st.columns(3)
        with c1:
            st.session_state.lib_filter_artist = st.selectbox(
                "艺术家", artists, key="filt_artist")
        with c2:
            st.session_state.lib_filter_album = st.selectbox(
                "专辑", albums, key="filt_album")
        with c3:
            st.session_state.lib_filter_genre = st.selectbox(
                "流派", genres, key="filt_genre")

        c4, c5 = st.columns(2)
        with c4:
            st.session_state.lib_filter_lang = st.selectbox(
                "语言", languages, key="filt_lang")
        with c5:
            st.session_state.lib_filter_emotion = st.selectbox(
                "情绪", emotions, key="filt_emotion")

    # ── 查询 ──
    if search_query:
        event = web_trigger.normalize(search_query)
        results = librarian.query(event.content, top_k=20)
        songs_to_show = []
        seen = set()
        for item in results:
            s = item["song"]
            key = f"{s.artist}|{s.title}"
            if key not in seen:
                seen.add(key)
                rec = lib_db.get_record(s.artist, s.title)
                songs_to_show.append((s, rec, item.get("similarity", 0)))
    else:
        fa = st.session_state.lib_filter_artist
        fb = st.session_state.lib_filter_album
        fg = st.session_state.lib_filter_genre
        fl = st.session_state.lib_filter_lang
        fe_cn = st.session_state.lib_filter_emotion
        fe = emotion_map.get(fe_cn, None)

        records = lib_db.filter_songs(
            artist=fa if fa != "全部" else None,
            album=fb if fb != "全部" else None,
            genre=fg if fg != "全部" else None,
            language=fl if fl != "全部" else None,
            emotion=fe if fe_cn != "全部" else None,
            limit=500,
        )
        songs_to_show = []
        for rec in records:
            song = librarian.songs.get(librarian._file_to_id(rec.file_path))
            songs_to_show.append((song, rec, None))

    # ── 列表 ──
    if not songs_to_show:
        st.info("没有匹配的歌曲")
    else:
        st.caption(f"共 {len(songs_to_show)} 首")

        # 表头
        h1, h2, h3, h4, h5, h6, h7 = st.columns([3, 2, 1.5, 1, 1, 0.8, 0.8])
        h1.caption("**标题**")
        h2.caption("**艺术家**")
        h3.caption("**专辑**")
        h4.caption("**语言**")
        h5.caption("**情绪**")
        h6.caption("**详情**")
        h7.caption("**编辑**")

        st.divider()

        for song, rec, sim in songs_to_show[:200]:
            if song is None and rec is None:
                continue
            title = (song.title if song else rec.title) or "?"
            artist = (song.artist if song else rec.artist) or "?"
            album = rec.album if rec and rec.album not in ("Unknown", "") else "-"
            language = rec.language if rec and rec.language else "-"
            emotion_raw = rec.emotion if rec and rec.emotion else "-"
            emo_display = {
                "happy": "😊快乐", "sad": "😢悲伤", "energetic": "🔥激情",
                "calm": "😌平静", "romantic": "💕浪漫", "nostalgic": "📻怀旧",
                "angry": "😡愤怒", "focus": "🧠专注", "party": "🎉派对",
            }.get(emotion_raw, emotion_raw)

            song_key = f"{artist}|{title}"
            c1, c2, c3, c4, c5, c6, c7, c8 = st.columns([2.5, 1.8, 1.5, 0.8, 0.8, 0.6, 0.6, 0.6])
            with c1:
                sim_str = f"  `{sim:.0%}`" if sim is not None else ""
                st.write(f"{title}{sim_str}")
            with c2:
                st.write(artist[:20])
            with c3:
                st.write(album[:15])
            with c4:
                st.write(language)
            with c5:
                st.write(emo_display)
            with c6:
                detail_key = f"detail_{song_key}"
                if st.button("📋", key=detail_key, help="查看详情"):
                    st.session_state[f"exp_{song_key}"] = not st.session_state.get(f"exp_{song_key}", False)
            with c7:
                edit_key = f"edit_{hash(song_key) % 100000}"
                if st.button("✏️", key=edit_key, help="编辑标签"):
                    st.session_state.lib_edit_song = (artist, title, rec)
            with c8:
                pl_key = f"addpl_{hash(song_key) % 100000}"
                if st.button("➕", key=pl_key, help="加入歌单"):
                    st.session_state.lib_add_to_pl = (artist, title, rec.file_path if rec else "")

            # 展开详情
            if st.session_state.get(f"exp_{song_key}", False):
                with st.expander("", expanded=True):
                    if rec:
                        d1, d2, d3 = st.columns(3)
                        with d1:
                            st.caption(f"流派: {rec.genre or '-'}")
                            st.caption(f"年份: {rec.year or '-'}")
                            st.caption(f"时长: {rec.duration or '-'}s")
                        with d2:
                            st.caption(f"播放次数: {rec.play_count}")
                            st.caption(f"最后播放: {rec.last_played or '-'}")
                            st.caption(f"有歌词: {'是' if rec.has_lyrics_int else '否'}")
                        with d3:
                            st.caption(f"文件: `...{rec.file_path[-40:]}`" if rec.file_path else "")
                            st.caption(f"备注: {rec.notes or '-'}")

                    if st.button("关闭详情", key=f"close_{song_key}"):
                        st.session_state[f"exp_{song_key}"] = False
                        st.rerun()

            st.divider()

        # ── 单曲编辑弹窗 ──
        if st.session_state.lib_edit_song is not None:
            edit_artist, edit_title, edit_rec = st.session_state.lib_edit_song
            st.divider()
            st.subheader(f"✏️ 编辑: {edit_artist} - {edit_title}")

            with st.form("edit_song_form"):
                col_a, col_b = st.columns(2)
                with col_a:
                    new_lang = st.selectbox(
                        "语言",
                        ["", "国语", "英语", "粤语", "日语", "韩语", "法语", "德语", "西班牙语"],
                        index=(["", "国语", "英语", "粤语", "日语", "韩语", "法语", "德语", "西班牙语"]
                               .index(edit_rec.language) if edit_rec and edit_rec.language in
                               ["", "国语", "英语", "粤语", "日语", "韩语", "法语", "德语", "西班牙语"] else 0),
                    )
                    new_genre = st.text_input("流派", value=edit_rec.genre if edit_rec else "")
                with col_b:
                    emo_options = ["", "happy", "sad", "energetic", "calm", "romantic", "nostalgic", "angry", "focus", "party"]
                    emo_labels = ["无", "😊快乐", "😢悲伤", "🔥激情", "😌平静", "💕浪漫", "📻怀旧", "😡愤怒", "🧠专注", "🎉派对"]
                    cur_emo = edit_rec.emotion if edit_rec else ""
                    emo_idx = emo_options.index(cur_emo) if cur_emo in emo_options else 0
                    new_emotion = st.selectbox("情绪", emo_labels, index=emo_idx)
                    new_album = st.text_input("专辑", value=edit_rec.album if edit_rec and edit_rec.album != "Unknown" else "")

                saved = st.form_submit_button("💾 保存", type="primary")
                if saved:
                    fields = {}
                    if new_lang:
                        fields["language"] = new_lang
                        fields["language_source"] = "manual"
                    if new_genre:
                        fields["genre"] = new_genre
                    if new_album:
                        fields["album"] = new_album
                    emo_en = emo_options[emo_idx] if emo_idx > 0 else ""
                    if emo_en:
                        fields["emotion"] = emo_en
                        fields["emotion_confidence"] = "manual"

                    if fields:
                        ok = lib_db.update_song_fields(edit_artist, edit_title, **fields)
                        if ok:
                            st.success(f"已更新 {edit_artist} - {edit_title}")
                            # 同步更新内存中的 song 对象
                            song_id = librarian._file_to_id(edit_rec.file_path) if edit_rec else None
                            if song_id and song_id in librarian.songs:
                                s = librarian.songs[song_id]
                                if "language" in fields:
                                    s.album = fields.get("album", s.album)
                            st.session_state.lib_edit_song = None
                            st.rerun()
                        else:
                            st.error("保存失败，请重试")
                    else:
                        st.warning("没有需要更新的字段")

            if st.button("取消编辑"):
                st.session_state.lib_edit_song = None
                st.rerun()

        # ── 加入歌单弹窗 ──
        if st.session_state.get("lib_add_to_pl") is not None:
            pl_artist, pl_title, pl_path = st.session_state.lib_add_to_pl
            playlists = lib_db.list_playlists()
            pl_names = [pl["name"] for pl in playlists]
            st.divider()
            st.subheader(f"➕ 加入歌单: {pl_artist} - {pl_title}")
            if not pl_names:
                st.info("还没有歌单，先去「智能歌单」页面创建一个吧")
            else:
                selected_pl = st.selectbox("选择歌单", pl_names, key="add_to_pl_select")
                if st.button("确认加入", type="primary"):
                    pl_id = next((pl["id"] for pl in playlists if pl["name"] == selected_pl), None)
                    if pl_id:
                        lib_db.add_song_to_playlist(pl_id, pl_artist, pl_title, pl_path)
                        st.success(f"已加入「{selected_pl}」")
                        st.session_state.lib_add_to_pl = None
                        st.rerun()
            if st.button("取消"):
                st.session_state.lib_add_to_pl = None
                st.rerun()

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
                    event = web_trigger.normalize(nl_query)
                    result = playlist_engine.create_playlist(
                        query_text=event.content,
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
                    pl_id_new = result.get("id")
                    for s in result["songs"][:20]:
                        c_s, c_b = st.columns([10, 1])
                        with c_s:
                            st.write(f"- **{s['artist']}** — {s['title']}  `{s.get('genre', '')}`")
                        with c_b:
                            if pl_id_new and st.button("✕", key=f"rm_new_{s['artist']}_{s['title']}"[:50], help="移除"):
                                lib_db.remove_song_from_playlist(pl_id_new, s['artist'], s['title'])
                                st.rerun()

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
                            for s in detail["songs"][:20]:
                                c_s, c_b = st.columns([10, 1])
                                with c_s:
                                    st.write(f"- {s['artist']} — {s['title']}")
                                with c_b:
                                    if st.button("✕", key=f"rm_{pl_id}_{s['artist']}_{s['title']}"[:50], help="移除"):
                                        lib_db.remove_song_from_playlist(pl_id, s['artist'], s['title'])
                                        st.rerun()
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
