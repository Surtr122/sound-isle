import {
  $,
  $$,
  escapeHtml,
  naturalCompare,
  formatDuration,
  formatLongDuration,
  formatSize,
  formatCount,
  formatDate,
  tagHue,
  debounce,
  isTypingTarget,
  parseTagInput,
  firstCharacter,
  parentFolder,
  clamp,
} from "./utils.js";
import { icon, categoryIcon, hydrateIcons } from "./icons.js";
import { coverMarkup } from "./cover.js";
import { mountSkinPreview, disposeSkinPreview } from "./preview3d.js";
import { plateMarkup } from "./plate.js";
import { Player } from "./player.js";
import { api } from "./api.js";

const VIEW_META = {
  library: { title: "全部素材", eyebrow: "LIBRARY / 01" },
  categories: { title: "自动分类", eyebrow: "LIBRARY / 02" },
  tags: { title: "标签", eyebrow: "LIBRARY / 03" },
  favorites: { title: "收藏", eyebrow: "LIBRARY / 04" },
};

const SORT_OPTIONS = [
  ["default", "默认（路径）"],
  ["title", "名称"],
  ["artist", "作者 / 角色"],
  ["duration", "时长（长到短）"],
  ["recent", "最近修改"],
  ["size", "文件大小"],
];

const state = {
  payload: null,
  library: null,
  view: "library",
  category: "all",
  activeTags: new Set(),
  typeFilter: "all",
  onlyFavorites: false,
  onlyPreviewable: false,
  search: "",
  sort: "default",
  selected: new Set(),
  visibleTracks: [],
  busy: false,
  welcomeBusy: false,
  welcomePath: "",
  welcomeError: "",
};

let player = null;
let searchDebounce = null;
let lastModalFocus = null;
let lastSelectedId = null;
let modalOnClose = null;

/* -------------------------------------------------------------------------- */
/* Boot                                                                       */
/* -------------------------------------------------------------------------- */

async function init() {
  hydrateIcons(document);
  player = new Player({
    onTrackChange: () => {
      updateRowsPlaying();
      updateDocumentTitle();
    },
    onFavorite: (track) => toggleTrackFavorite(track),
    onError: (message) => toast(message, { type: "error" }),
  });
  bindEvents();
  await loadInitialState();
}

async function loadInitialState() {
  try {
    const payload = await api.state();
    state.payload = payload;
    if (payload.library) {
      enterLibrary(payload, { announce: false });
    } else {
      state.library = null;
      state.welcomeError = payload.error || "";
      if (!state.welcomePath) {
        state.welcomePath = payload.recents?.[0]?.path || "";
      }
      renderWelcome();
    }
  } catch (error) {
    state.payload = null;
    state.library = null;
    state.welcomeError = error.message;
    renderWelcome();
  }
}

/* -------------------------------------------------------------------------- */
/* Small helpers                                                              */
/* -------------------------------------------------------------------------- */

function norm(value) {
  return String(value ?? "").trim().toLocaleLowerCase("zh-CN");
}

function libraryName() {
  return state.library?.name || parentFolder(state.library?.root || "") || "素材文件夹";
}

function isAudio(track) {
  return track?.kind !== "asset";
}

function trackInCategory(track, key) {
  if (!key) return true;
  const categories =
    Array.isArray(track?.categories) && track.categories.length
      ? track.categories
      : track?.category
        ? [track.category]
        : [];
  return categories.some((category) => category?.key === key);
}

function trackCategories(track) {
  const categories =
    Array.isArray(track?.categories) && track.categories.length
      ? track.categories
      : track?.category
        ? [track.category]
        : [];
  return categories.filter(Boolean);
}

function audioTracks(tracks = state.visibleTracks) {
  return tracks.filter((track) => isAudio(track));
}

function itemUnit(track) {
  return isAudio(track) ? "首" : "件";
}

function domainName(domain) {
  return domain === "audio" ? "声音" : "形体";
}

function selectedTracks() {
  if (!state.library) return [];
  return state.library.tracks.filter((track) => state.selected.has(track.id));
}

function findTrack(id) {
  return state.library?.tracks.find((track) => track.id === id) || null;
}

function inlineError(message) {
  return `<div class="inline-error">${icon("alert", 14)}<span>${escapeHtml(message)}</span></div>`;
}

function emptyState({ title, copy, action = "" }) {
  return `<div class="empty-state">
    <span class="empty-vinyl" aria-hidden="true"></span>
    <h3 class="empty-title">${escapeHtml(title)}</h3>
    <p class="empty-copy">${escapeHtml(copy)}</p>
    ${action ? `<div class="empty-actions">${action}</div>` : ""}
  </div>`;
}

function tagChip(tag, { action = "toggle-tag", muted = false, extraClass = "" } = {}) {
  const classes = ["tag-chip", muted ? "is-muted" : "", extraClass].filter(Boolean).join(" ");
  const style = `--tag-h:${tagHue(tag)}`;
  if (!action) {
    return `<span class="${classes}" style="${style}">${escapeHtml(tag)}</span>`;
  }
  return `<button class="${classes}" type="button" style="${style}" data-action="${action}" data-tag="${escapeHtml(tag)}">${escapeHtml(tag)}</button>`;
}

function statCard(label, value, unit, note) {
  return `<div class="stat-card">
    <span class="stat-label">${escapeHtml(label)}</span>
    <span class="stat-value">${escapeHtml(String(value))}${unit ? `<span class="stat-unit">${escapeHtml(unit)}</span>` : ""}</span>
    <span class="stat-note">${escapeHtml(note)}</span>
  </div>`;
}

function categoryCard(category, { large = false, active = false, parentName = "" } = {}) {
  return `<button class="category-card ${large ? "is-large" : ""} ${active ? "is-active" : ""}" type="button"
    data-action="open-category" data-category="${escapeHtml(category.key)}"
    style="--accent:${escapeHtml(category.accent)}">
    <span class="category-icon">${categoryIcon(category.key, 17)}</span>
    <span class="category-name">${escapeHtml(category.name)}</span>
    <span class="category-count">${formatCount(category.count)}<small>${category.domain === "audio" ? "首" : category.domain === "custom" ? "项" : "件"}</small></span>
    ${parentName ? `<span class="category-parent">${escapeHtml(parentName)} 下的小类</span>` : ""}
    <span class="category-hint">${escapeHtml(category.hint)}</span>
    <span class="category-bar"><span style="width:${clamp(Number(category.share) || 0, 0, 100)}%"></span></span>
  </button>`;
}

function subcategoryStrip(categoryKey, label) {
  const category = state.library?.categories.find((item) => item.key === categoryKey);
  const items = (category?.subcategories || []).filter((item) => Number(item.count) > 0);
  if (!items.length) return "";
  return `<div class="subcategory-strip">
    <span class="subcategory-label">${escapeHtml(label)}</span>
    <div class="subcategory-chips">
      ${items
        .map(
          (item) => `<button class="subcategory-chip" type="button" data-action="open-subcategory" data-category="${escapeHtml(categoryKey)}" data-sub="${escapeHtml(item.key)}">
            ${escapeHtml(item.name)}<span>${formatCount(item.count)}</span>
          </button>`,
        )
        .join("")}
    </div>
  </div>`;
}

/* -------------------------------------------------------------------------- */
/* Filters and sorting                                                        */
/* -------------------------------------------------------------------------- */

function searchHaystack(track) {
  return [
    track.title,
    track.artist,
    track.album,
    track.filename,
    track.folder,
    track.rel_path,
    track.genre,
    track.summary,
    track.note,
    track.format,
    track.kind === "asset" ? "3d 资产 模型 形体 asset" : "声音 音频 audio",
    track.category?.name,
    ...(track.tags || []),
  ]
    .filter(Boolean)
    .join(" ")
    .toLocaleLowerCase("zh-CN");
}

function sortTracks(tracks) {
  const list = [...tracks];
  switch (state.sort) {
    case "title":
      list.sort(
        (a, b) =>
          naturalCompare(a.title || a.filename, b.title || b.filename) ||
          naturalCompare(a.rel_path, b.rel_path),
      );
      break;
    case "artist":
      list.sort((a, b) => {
        if (!a.artist && b.artist) return 1;
        if (a.artist && !b.artist) return -1;
        return (
          naturalCompare(a.artist, b.artist) ||
          naturalCompare(a.title || a.filename, b.title || b.filename)
        );
      });
      break;
    case "duration":
      list.sort(
        (a, b) =>
          (Number(b.duration) || 0) - (Number(a.duration) || 0) ||
          naturalCompare(a.rel_path, b.rel_path),
      );
      break;
    case "recent":
      list.sort(
        (a, b) =>
          (Date.parse(b.modified) || 0) - (Date.parse(a.modified) || 0) ||
          naturalCompare(a.rel_path, b.rel_path),
      );
      break;
    case "size":
      list.sort(
        (a, b) =>
          (Number(b.size) || 0) - (Number(a.size) || 0) ||
          naturalCompare(a.rel_path, b.rel_path),
      );
      break;
    default:
      list.sort((a, b) => naturalCompare(a.rel_path, b.rel_path));
  }
  return list;
}

function getVisibleTracks() {
  if (!state.library) return [];
  let tracks = [...state.library.tracks];

  if (state.view === "categories" && state.category !== "all") {
    tracks = tracks.filter((track) => trackInCategory(track, state.category));
  }
  if (state.view === "favorites") {
    tracks = tracks.filter((track) => track.favorite);
  }
  if (state.activeTags.size) {
    tracks = tracks.filter((track) =>
      [...state.activeTags].every((wanted) =>
        (track.tags || []).some((tag) => norm(tag) === norm(wanted)),
      ),
    );
  }
  if (state.typeFilter === "audio") tracks = tracks.filter((track) => isAudio(track));
  else if (state.typeFilter === "asset") tracks = tracks.filter((track) => !isAudio(track));
  if (state.onlyFavorites) tracks = tracks.filter((track) => track.favorite);
  if (state.onlyPreviewable) {
    tracks = tracks.filter(
      (track) => isAudio(track) || isMotionPreviewable(track) || isSkinPreviewable(track),
    );
  }

  const query = state.search.trim().toLocaleLowerCase("zh-CN");
  if (query) {
    tracks = tracks.filter((track) => searchHaystack(track).includes(query));
  }
  return sortTracks(tracks);
}

/* -------------------------------------------------------------------------- */
/* Rendering                                                                  */
/* -------------------------------------------------------------------------- */

function sourceBar() {
  const sources = state.library?.sources || [];
  if (!sources.length) return "";
  return `<div class="source-bar">
    <span class="source-bar-label"><span class="source-bar-dot"></span>${formatCount(sources.length)} 个文件夹</span>
    <div class="source-chips">
      ${sources
        .map(
          (source) => `<span class="source-chip ${source.exists === false ? "is-missing" : ""} ${Number(source.missing) ? "has-missing" : ""}" title="${escapeHtml(source.path)}">
            <span class="source-chip-name">${escapeHtml(source.name)}</span>
            <span class="source-chip-count">${formatCount(source.count)}</span>
            ${Number(source.missing) ? `<span class="source-chip-alert" title="${formatCount(source.missing)} 个文件缺失">${formatCount(source.missing)} 缺失</span>` : ""}
            <button class="source-chip-refresh" type="button" data-action="rescan-source" data-source-id="${escapeHtml(source.id)}" title="只重新扫描这个文件夹" aria-label="重新扫描 ${escapeHtml(source.name)}">${icon("refresh", 11)}</button>
            <button class="source-chip-remove" type="button" data-action="remove-source" data-source-id="${escapeHtml(source.id)}" title="从素材库移除（不会删除文件）" aria-label="移除 ${escapeHtml(source.name)}">×</button>
          </span>`,
        )
        .join("")}
      <button class="source-add" type="button" data-action="add-folder">${icon("plus", 12)}添加文件夹</button>
      <span class="source-tools">
        <button class="source-tool" type="button" data-action="export-metadata" title="导出标签、收藏和分类资料">${icon("external", 11)}导出资料</button>
        <button class="source-tool" type="button" data-action="import-metadata" title="导入标签、收藏和分类资料">${icon("copy", 11)}导入资料</button>
        <input class="visually-hidden" id="metadata-import" type="file" accept="application/json,.json">
      </span>
    </div>
  </div>`;
}

function render({ keepScroll = false } = {}) {
  if (!state.library) {
    renderWelcome();
    return;
  }

  const root = $("#view-root");
  if (!root) return;
  const scroll = window.scrollY;
  state.visibleTracks = getVisibleTracks();

  let markup = "";
  switch (state.view) {
    case "categories":
      markup = viewCategories();
      break;
    case "favorites":
      markup = viewFavorites();
      break;
    default:
      markup = viewLibrary();
  }
  markup = `${sourceBar()}${markup}`;

  root.innerHTML = markup;
  hydrateIcons(root);
  updateChrome();
  updateSelectionUI();

  if (player) {
    player.setLibrary(state.library);
    player.setQueue(audioTracks());
  }
  updateRowsPlaying();
  updateDocumentTitle();

  if (!keepScroll) {
    root.classList.remove("view-enter");
    void root.offsetWidth;
    root.classList.add("view-enter");
  }
  if (keepScroll) {
    window.scrollTo({ top: scroll, behavior: "auto" });
  }
}

function heroAssetMarkup(track) {
  return `<div class="hero-form" style="--accent:${escapeHtml(track?.category?.accent || "#B08A45")}">
    <svg class="hero-form-art" viewBox="0 0 260 240" aria-hidden="true">
      <path d="m130 28 82 47v90l-82 47-82-47V75Z"/>
      <path d="m48 75 82 47 82-47M130 122v90" class="dim"/>
      <path d="m94 50 82 47v46" class="dim"/>
      <circle cx="48" cy="75" r="4"/><circle cx="212" cy="75" r="4"/><circle cx="130" cy="28" r="4"/>
    </svg>
    <span class="hero-form-index">${escapeHtml(track?.format || "ASSET")}</span>
  </div>`;
}

function viewLibrary() {
  const library = state.library;
  const tracks = state.visibleTracks;
  const stats = library.stats || {};
  const total = Number(stats.total) || library.tracks.length;
  const audioCount = Number(stats.audio) || library.tracks.filter((track) => isAudio(track)).length;
  const assetCount = Number(stats.assets) || library.tracks.filter((track) => !isAudio(track)).length;
  const longest = library.tracks.reduce(
    (max, track) => Math.max(max, Number(track.duration) || 0),
    0,
  );
  const favoritePercent = total ? Math.round((Number(stats.favorites) / total) * 100) : 0;
  const scanSeconds = Number(stats.scan_seconds);
  const scanNote = Number.isFinite(scanSeconds)
    ? `扫描 ${scanSeconds < 1 ? scanSeconds.toFixed(2) : scanSeconds.toFixed(1)} 秒`
    : "本次扫描";
  const featuredAsset = library.tracks.find(
    (track) => !isAudio(track) && ["character", "model", "prop", "scene"].some((key) => trackInCategory(track, key)),
  ) || library.tracks.find((track) => !isAudio(track));
  const heroTrack =
    featuredAsset ||
    library.tracks.find((track) => track.has_cover) ||
    library.tracks[0] ||
    null;
  const heroAccent = heroTrack?.category?.accent || "#B08A45";
  const heroImage =
    heroTrack && isAudio(heroTrack) && heroTrack.has_cover && heroTrack.cover_url
      ? `<div class="hero-vinyl-cover"><img src="${escapeHtml(heroTrack.cover_url)}" alt="" loading="lazy" decoding="async"></div>`
      : heroTrack && isAudio(heroTrack)
        ? `<span class="hero-vinyl-initial">${escapeHtml(firstCharacter(heroTrack?.title || "声"))}</span>`
        : "";
  const heroVisual =
    heroTrack && !isAudio(heroTrack)
      ? `<div class="hero-asset">${heroAssetMarkup(heroTrack)}</div>`
      : `<div class="hero-vinyl" style="--accent:${escapeHtml(heroAccent)}">${heroImage}</div>`;
  const heroMeta = heroTrack
    ? isAudio(heroTrack)
      ? `${escapeHtml(heroTrack.category?.name || "未分类")} · ${formatDuration(heroTrack.duration)}`
      : `${escapeHtml(heroTrack.category?.name || "未分类")} · ${escapeHtml(heroTrack.summary || heroTrack.format)}`
    : "MP3 / FLAC / WAV / GLB / FBX / BVH";

  const audioCategories = library.categories.filter((category) => !category.custom && category.domain === "audio");
  const assetCategories = library.categories.filter((category) => !category.custom && category.domain !== "audio");
  const customCategories = library.categories.filter((category) => category.custom && !category.parent);
  const customChildren = library.categories.filter((category) => category.custom && category.parent);
  const searchActive = Boolean(state.search.trim());
  const emptyMarkup = searchActive
    ? emptyState({
        title: "没有找到这类素材",
        copy: "换一个关键词，或者清空搜索，回到整座岛。",
        action: `<button class="btn btn-ghost" type="button" data-action="clear-search">清空搜索</button>`,
      })
    : emptyState({
        title: "岛上还没有素材",
        copy: "把音频或 3D 资产放进这个文件夹，或者再加一个有内容的文件夹。",
        action: `<button class="btn btn-primary" type="button" data-action="add-folder">${icon("folder", 14)}添加文件夹</button>`,
      });

  return `
    <section class="hero">
      <div class="hero-copy">
        <span class="hero-kicker">SOUND &amp; FORM · LOCAL LIBRARY</span>
        <h2 class="hero-title"><span class="hero-title-line">把声音与形体，</span><span class="hero-title-line hero-title-accent">留在岛上。</span></h2>
        <p class="hero-lede">从「${escapeHtml(libraryName())}」里整理 ${formatCount(audioCount)} 段声音与 ${formatCount(assetCount)} 件形体资产。分类、标签与收藏都在本地完成，文件一个字节都不会离开你的硬盘。</p>
        <div class="hero-actions">
          <button class="btn btn-primary" type="button" data-action="play-all" ${audioCount ? "" : "disabled"}>${icon("play", 15)}播放全部声音</button>
          <button class="btn btn-ghost" type="button" data-action="${assetCount ? "shuffle-inspect" : "shuffle"}" ${assetCount || audioCount ? "" : "disabled"}>${assetCount ? `${icon("cube", 15)}随机看一件` : `${icon("shuffle", 15)}随机播放`}</button>
        </div>
      </div>
      <div class="hero-art">
        ${heroVisual}
        <div class="hero-float">
          <span class="hero-float-label">${heroTrack && !isAudio(heroTrack) ? "FEATURED ASSET" : "CURRENT PRESSING"}</span>
          <span class="hero-float-title">${escapeHtml(heroTrack?.title || "等待第一件素材")}</span>
          <span class="hero-float-meta">${heroMeta}</span>
        </div>
        <span class="hero-serial">ISLE / ${String(total).padStart(3, "0")}</span>
      </div>
    </section>

    <div class="stats-grid">
      ${statCard("素材总数", formatCount(total), "项", scanNote)}
      ${statCard("声音", formatCount(audioCount), "段", longest ? `最长一段 ${formatDuration(longest)}` : "还没有音频")}
      ${statCard("形体资产", formatCount(assetCount), "件", `${formatCount(stats.models || 0)} 个模型 · ${formatCount(stats.textures || 0)} 张贴图`)}
      ${statCard("已收藏", formatCount(stats.favorites || 0), "项", `${favoritePercent}% 的资料库`)}
    </div>

    <div class="section-head">
      <div class="section-head-copy">
        <span class="section-kicker">AUTO ORGANISED / SOUND</span>
        <h2 class="section-title">声音的七个抽屉</h2>
        <p class="section-sub">按文件名、路径、时长与元数据透明归类，点一下就能收窄。</p>
      </div>
      <div class="section-actions">
        <button class="btn btn-quiet btn-small" type="button" data-action="go-categories">查看分类规则 ${icon("arrow-right", 13)}</button>
      </div>
    </div>
    <div class="category-grid">
      ${audioCategories.map((category) => categoryCard(category)).join("")}
    </div>

    <div class="section-head">
      <div class="section-head-copy">
        <span class="section-kicker">AUTO ORGANISED / FORM</span>
        <h2 class="section-title">形体的八个抽屉</h2>
        <p class="section-sub">先认扩展名，再读路径与结构；骨骼、角色、场景与贴图各自归位。</p>
      </div>
      <div class="section-actions">
        <button class="btn btn-quiet btn-small" type="button" data-action="create-category">${icon("plus", 13)}新建分类</button>
      </div>
    </div>
    <div class="category-grid is-four">
      ${assetCategories.map((category) => categoryCard(category)).join("")}
    </div>

    ${
      customCategories.length
        ? `<div class="section-head">
            <div class="section-head-copy">
              <span class="section-kicker">YOUR OWN DRAWERS</span>
              <h2 class="section-title">我的抽屉</h2>
              <p class="section-sub">你自己创建的分类，可能装着一段声音，也可能是一件模型。</p>
            </div>
            <div class="section-actions">
              <button class="btn btn-quiet btn-small" type="button" data-action="create-category">${icon("plus", 13)}新建分类</button>
            </div>
          </div>
          <div class="category-grid is-four">
            ${customCategories.map((category) => categoryCard(category)).join("")}
          </div>`
        : ""
    }

    <div class="section-head">
      <div class="section-head-copy">
        <span class="section-kicker">${searchActive ? "SEARCH RESULTS" : "FULL CATALOGUE"}</span>
        <h2 class="section-title">${searchActive ? "搜索结果" : "全部素材"}</h2>
        <p class="section-sub">${searchActive ? `正在寻找“${escapeHtml(state.search.trim())}”` : `按${state.sort === "default" ? "路径自然顺序" : "当前排序"}排列，勾选后可批量整理。`}</p>
      </div>
      <div class="section-actions">
        ${state.sort !== "default" ? `<button class="btn btn-quiet btn-small" type="button" data-action="reset-sort">恢复默认排序</button>` : ""}
      </div>
    </div>

    ${tableCard(tracks, { emptyMarkup })}
  `;
}

function viewCategories() {
  const library = state.library;
  const selected = library.categories.find((category) => category.key === state.category) || null;
  const tracks = state.visibleTracks;
  const searchActive = Boolean(state.search.trim());
  const audioCategories = library.categories.filter((category) => !category.custom && category.domain === "audio");
  const assetCategories = library.categories.filter((category) => !category.custom && category.domain !== "audio");
  const customCategories = library.categories.filter((category) => category.custom && !category.parent);
  const customChildren = library.categories.filter((category) => category.custom && category.parent);
  const selectedUnit = !selected ? "项" : selected.domain === "audio" ? "首" : selected.domain === "custom" ? "项" : "件";

  const detailTitle = selected ? selected.name : "所有分类";
  const detailCopy = selected
    ? selected.description
    : "点一张卡片收窄到一个抽屉，再点一次回到全部素材。";
  const emptyMarkup = emptyState({
    title: selected ? "这个抽屉还是空的" : "还没有可分类的素材",
    copy: selected
      ? "换一个分类看看，或者回到全部素材。"
      : "把音频或 3D 资产放进文件夹后重新扫描，声形会按规则自动归类。",
    action: selected
      ? `<button class="btn btn-ghost" type="button" data-action="filter-category" data-category="${escapeHtml(selected.key)}">查看全部分类</button>`
      : `<button class="btn btn-primary" type="button" data-action="rescan">${icon("refresh", 14)}重新扫描</button>`,
  });

  return `
    <div class="view-head">
      <div class="view-head-copy">
        <span class="view-kicker">02 / AUTO CATEGORIES</span>
        <h2 class="view-title">让素材自己<em>找到抽屉</em></h2>
        <p class="view-lede">十五个内置分类，外加你自己的抽屉：声音看时长、路径与元数据，形体先认扩展名，再读路径与结构。每条分类都带着一条可以追问的理由。</p>
      </div>
      <div class="view-head-actions">
        <button class="btn btn-ghost" type="button" data-action="create-category">${icon("plus", 14)}新建分类</button>
        <button class="btn btn-ghost" type="button" data-action="rescan">${icon("refresh", 14)}重新扫描</button>
      </div>
    </div>

    <div class="section-head">
      <div class="section-head-copy">
        <span class="section-kicker">SOUND / 07</span>
        <h2 class="section-title">声音的七个抽屉</h2>
        <p class="section-sub">歌曲、纯音乐、播客、有声书、课程、音效与其他。</p>
      </div>
    </div>
    <div class="category-overview">
      ${audioCategories.map((category) => categoryCard(category, { large: true, active: category.key === state.category })).join("")}
    </div>

    ${subcategoryStrip("sfx", "音效细类")}

    <div class="rule-strip">
      <span class="rule-strip-label">HOW SOUND READS</span>
      <div class="rule-step"><b>01</b><span><strong>先看时长</strong>短于 22 秒的音频优先归入音效。</span></div>
      <div class="rule-step"><b>02</b><span><strong>再读线索</strong>路径、文件名与元数据里的关键词决定大部分分类。</span></div>
      <div class="rule-step"><b>03</b><span><strong>最后兜底</strong>章节线索归有声书，节目编号归播客，剩下的按流派与时长判断。</span></div>
    </div>

    <div class="section-head">
      <div class="section-head-copy">
        <span class="section-kicker">FORM / 08</span>
        <h2 class="section-title">形体的八个抽屉</h2>
        <p class="section-sub">骨骼动作、角色、道具、场景、材质贴图、工程文件、模型与其他。</p>
      </div>
    </div>
    <div class="category-overview">
      ${assetCategories.map((category) => categoryCard(category, { large: true, active: category.key === state.category })).join("")}
    </div>

    ${subcategoryStrip("animation", "动作细类")}

    ${
      customCategories.length
        ? `<div class="section-head">
            <div class="section-head-copy">
              <span class="section-kicker">YOUR OWN DRAWERS</span>
              <h2 class="section-title">我的抽屉</h2>
              <p class="section-sub">自定义分类可以同时装声音和形体，点开抽屉就能看、能听。</p>
            </div>
          </div>
          <div class="category-overview">
            ${customCategories.map((category) => categoryCard(category, { large: true, active: category.key === state.category })).join("")}
          </div>`
        : ""
    }

    ${
      customChildren.length
        ? `<div class="section-head">
            <div class="section-head-copy">
              <span class="section-kicker">SUB-DRAWERS</span>
              <h2 class="section-title">大类下的小类</h2>
              <p class="section-sub">小类可以单独打开，也可以和所属大类一起被找到；一件素材可以同时放进多个分类。</p>
            </div>
          </div>
          <div class="category-overview">
            ${customChildren
              .map((category) => {
                const parent = library.categories.find((item) => item.key === category.parent);
                return categoryCard(category, {
                  large: true,
                  active: category.key === state.category,
                  parentName: parent?.name || "大类",
                });
              })
              .join("")}
          </div>`
        : ""
    }

    <div class="rule-strip">
      <span class="rule-strip-label">HOW FORM READS</span>
      <div class="rule-step"><b>01</b><span><strong>先认扩展名</strong>工程、贴图与动画格式直接归档。</span></div>
      <div class="rule-step"><b>02</b><span><strong>再读路径</strong>角色、道具、场景与动作关键词决定大部分分类。</span></div>
      <div class="rule-step"><b>03</b><span><strong>最后看结构</strong>GLB / BVH / OBJ 的元数据补充判断。</span></div>
    </div>

    <div class="category-detail">
      <div class="category-detail-head">
        <div>
          <h3 class="category-detail-title">
            ${selected ? `<span class="category-swatch" style="--accent:${escapeHtml(selected.accent)}"></span>` : ""}
            ${escapeHtml(detailTitle)}
          </h3>
          <p class="category-detail-copy">${escapeHtml(detailCopy)}</p>
        </div>
        <span class="result-count">${formatCount(tracks.length)} ${selectedUnit}${searchActive ? " · 含搜索" : ""}</span>
      </div>
      ${tableCard(tracks, { emptyMarkup })}
    </div>
  `;
}

function viewTags() {
  const library = state.library;
  const tags = library.tags || [];
  const stats = library.stats || {};
  const activeTag = state.activeTag || "__all__";
  const isUntagged = activeTag === "__untagged__";
  const isAll = activeTag === "__all__";
  const activeItem = tags.find((item) => item.name === activeTag) || null;
  const tracks = state.visibleTracks;

  const summaryValue = isAll
    ? `${formatCount(tags.length)} 个`
    : isUntagged
      ? "未标记"
      : activeTag;
  const summaryNote = `${formatCount(tracks.length)} 项素材${state.search.trim() ? " · 含搜索" : ""}`;
  const summaryChips = isAll
    ? tags.slice(0, 4).map((item) => tagChip(item.name)).join("")
    : isUntagged
      ? ""
      : tagChip(activeTag);

  const emptyMarkup = emptyState({
    title: isUntagged ? "没有未标记的素材" : isAll ? "还没有标签" : "这个标签下还没有素材",
    copy: isAll
      ? "在列表里勾选素材，点下方的「加标签」，给它们一个共同的抽屉。"
      : "换一个标签看看，或在全部素材里继续整理。",
    action: `<button class="btn btn-ghost" type="button" data-action="go-library">${icon("layers", 14)}回到全部素材</button>`,
  });

  return `
    <div class="view-head">
      <div class="view-head-copy">
        <span class="view-kicker">03 / TAGS</span>
        <h2 class="view-title">给素材，<em>留一张便签</em></h2>
        <p class="view-lede">标签是你自己的语言。可以给一段声音或一件模型贴很多张，也可以从这一页批量加上或撕下。</p>
      </div>
      <div class="view-head-actions">
        <button class="btn btn-ghost" type="button" data-action="go-library">${icon("layers", 14)}全部素材</button>
      </div>
    </div>

    <div class="tag-layout">
      <aside class="tag-panel">
        <div class="tag-panel-head">
          <h3 class="tag-panel-title">标签索引</h3>
          <p class="tag-panel-sub">${formatCount(tags.length)} 个标签 · ${formatCount(stats.tagged || 0)} 项已标记</p>
        </div>
        <div class="tag-filter-list">
          <button class="tag-filter ${isAll ? "is-active" : ""}" type="button" data-action="filter-tag" data-tag="__all__">
            <span class="tag-filter-dot" style="--tag-h:35"></span>
            <span class="tag-filter-name">全部标签</span>
            <span class="tag-filter-count">${formatCount(stats.total || 0)}</span>
          </button>
          <button class="tag-filter is-untagged ${isUntagged ? "is-active" : ""}" type="button" data-action="filter-tag" data-tag="__untagged__">
            <span class="tag-filter-dot"></span>
            <span class="tag-filter-name">未标记</span>
            <span class="tag-filter-count">${formatCount(stats.untagged || 0)}</span>
          </button>
          ${tags
            .map(
              (item) => `<button class="tag-filter ${!isAll && !isUntagged && norm(item.name) === norm(activeTag) ? "is-active" : ""}" type="button" data-action="filter-tag" data-tag="${escapeHtml(item.name)}">
                <span class="tag-filter-dot" style="--tag-h:${tagHue(item.name)}"></span>
                <span class="tag-filter-name">${escapeHtml(item.name)}</span>
                <span class="tag-filter-count">${formatCount(item.count)}</span>
              </button>`,
            )
            .join("")}
        </div>
      </aside>

      <div class="tag-content">
        <div class="tag-summary">
          <span class="tag-summary-label">${isAll ? "TAG INDEX" : isUntagged ? "TO SORT" : "FILTERED BY"}</span>
          <span class="tag-summary-value">${escapeHtml(summaryValue)}</span>
          <span class="tag-summary-rule"></span>
          <span class="tag-summary-note">${escapeHtml(summaryNote)}</span>
          ${summaryChips}
        </div>
        ${isUntagged ? `<p class="untagged-note">${icon("info", 13)}这些素材还没有标签；勾选后点下方的「加标签」即可。</p>` : ""}
        ${tableCard(tracks, { emptyMarkup })}
      </div>
    </div>
  `;
}

function viewFavorites() {
  const library = state.library;
  const stats = library.stats || {};
  const tracks = state.visibleTracks;

  const emptyMarkup = emptyState({
    title: "还没有收藏",
    copy: "点素材右侧的爱心，把喜欢的声音或模型留在这座岛上。它们仍然只是你硬盘里的文件。",
    action: `<button class="btn btn-ghost" type="button" data-action="go-library">${icon("layers", 14)}去挑几件</button>`,
  });

  return `
    <div class="favorites-banner">
      <div class="favorites-copy">
        <span class="section-kicker">KEPT CLOSE</span>
        <h2 class="favorites-title">把喜欢的，<em>留在手边。</em></h2>
        <p>收藏只记录在本机，不会移动、复制或上传任何文件。</p>
      </div>
      <div class="favorites-stat">
        <strong>${formatCount(stats.favorites || 0)}</strong>
        <span>FAVORITES</span>
      </div>
    </div>

    <div class="section-head">
      <div class="section-head-copy">
        <span class="section-kicker">YOUR SHORTLIST</span>
        <h2 class="section-title">收藏的素材</h2>
        <p class="section-sub">${formatCount(tracks.length)} 项${state.search.trim() ? "匹配当前搜索" : "已经留在这里"}，按当前排序排列。</p>
      </div>
      <div class="section-actions">
        <button class="btn btn-quiet btn-small" type="button" data-action="play-all" ${audioTracks(tracks).length ? "" : "disabled"}>${icon("play", 13)}播放收藏声音</button>
      </div>
    </div>

    ${tableCard(tracks, { emptyMarkup })}
  `;
}

function tableCard(tracks, { emptyMarkup = "" } = {}) {
  const missingCount = state.library?.missing?.length || 0;
  const duplicateCount = state.library?.duplicates?.length || 0;
  const savedViews = loadSavedViews();
  const selectedVisible = tracks.filter((track) => state.selected.has(track.id)).length;
  const allSelected = tracks.length > 0 && selectedVisible === tracks.length;
  const someSelected = selectedVisible > 0 && !allSelected;
  const defaultEmpty = emptyState({
    title: "这里还没有素材",
    copy: "换一个筛选条件，或者回到全部素材。",
    action: `<button class="btn btn-ghost" type="button" data-action="go-library">回到全部素材</button>`,
  });

  const body = tracks.length
    ? `<div class="table-scroll">
        <table class="track-table">
          <thead>
            <tr>
              <th class="th-check"><span class="visually-hidden">选择</span></th>
              <th>素材</th>
              <th class="th-cat">分类</th>
              <th class="th-tags">标签</th>
              <th class="th-duration">时长 / 大小</th>
              <th class="th-fav">收藏</th>
            </tr>
          </thead>
          <tbody>
            ${tracks.map((track, index) => trackRow(track, index)).join("")}
          </tbody>
        </table>
      </div>`
    : emptyMarkup || defaultEmpty;

  return `<div class="table-card">
    <div class="table-toolbar">
      <div class="toolbar-left">
        <span class="result-count">${formatCount(tracks.length)} ITEMS</span>
        <span class="toolbar-rule"></span>
        <label class="select-all-label">
          <input class="select-all-checkbox" type="checkbox" data-select-all ${allSelected ? "checked" : ""} ${someSelected ? "data-indeterminate=\"true\"" : ""}>
          全选
        </label>
      </div>
      <div class="toolbar-right">
        <label class="sort-field filter-field">
          类型
          <select class="sort-select" data-type-filter>
            <option value="all" ${state.typeFilter === "all" ? "selected" : ""}>全部</option>
            <option value="audio" ${state.typeFilter === "audio" ? "selected" : ""}>声音</option>
            <option value="asset" ${state.typeFilter === "asset" ? "selected" : ""}>形体</option>
          </select>
        </label>
        <button class="btn btn-quiet btn-small filter-toggle ${state.onlyFavorites ? "is-active" : ""}" type="button" data-action="toggle-favorites-filter">
          ${icon("heart", 12)}仅收藏
        </button>
        <button class="btn btn-quiet btn-small filter-toggle ${state.onlyPreviewable ? "is-active" : ""}" type="button" data-action="toggle-preview-filter">
          ${icon("play", 12)}可预览
        </button>
        <button class="btn btn-quiet btn-small tag-filter-toggle ${state.activeTags.size ? "is-active" : ""}" type="button" data-action="open-tag-filter">
          ${icon("tag", 12)}标签筛选${state.activeTags.size ? ` · ${state.activeTags.size}` : ""}
        </button>
        ${missingCount ? `<button class="btn btn-quiet btn-small health-toggle is-warn" type="button" data-action="open-missing">${icon("alert", 12)}缺失 ${missingCount}</button>` : ""}
        ${duplicateCount ? `<button class="btn btn-quiet btn-small health-toggle" type="button" data-action="open-duplicates">${icon("copy", 12)}重复 ${duplicateCount} 组</button>` : ""}
        <label class="sort-field">
          排序
          <select class="sort-select" data-sort>
            ${SORT_OPTIONS.map(
              ([value, label]) => `<option value="${value}" ${state.sort === value ? "selected" : ""}>${escapeHtml(label)}</option>`,
            ).join("")}
          </select>
        </label>
        ${savedViews.length ? `<select class="sort-select saved-view-select" data-saved-view aria-label="已保存视图">
          <option value="">视图…</option>
          ${savedViews.map((item) => `<option value="${escapeHtml(item.name)}">${escapeHtml(item.name)}</option>`).join("")}
        </select>` : ""}
        <button class="btn btn-quiet btn-small" type="button" data-action="save-view">${icon("shield", 12)}保存视图</button>
      </div>
    </div>
    ${body}
  </div>`;
}

function trackRow(track, index) {
  const audio = isAudio(track);
  const current = audio && player?.current?.id === track.id;
  const playing = current && !player.audio.paused;
  const selected = state.selected.has(track.id);
  const tags = track.tags || [];
  const shownTags = tags.slice(0, 3);
  const more = tags.length - shownTags.length;
  const title = track.title || track.filename || "未命名素材";
  const category = track.category || {
    name: audio ? "其他" : "其他",
    accent: "#817F73",
    key: audio ? "other" : "asset_other",
    domain: audio ? "audio" : "asset",
  };
  const categories = trackCategories(track).length ? trackCategories(track) : [category];
  const subParts = audio
    ? [track.artist || "未知艺术家", track.filename || ""]
    : [track.format || "ASSET", track.filename || ""];
  const cover = audio
    ? `<span class="row-cover">${coverMarkup(track, { size: "sm", playing })}</span>`
    : `<span class="row-cover row-plate">${plateMarkup(track, { size: "sm" })}</span>`;

  return `<tr class="track-row ${audio ? "is-audio" : "is-asset"} ${selected ? "is-selected" : ""} ${current ? "is-playing" : ""}" draggable="true" data-track-id="${escapeHtml(track.id)}" data-kind="${audio ? "audio" : "asset"}" aria-selected="${selected ? "true" : "false"}">
    <td class="td-check">
      <input class="row-checkbox" type="checkbox" data-select="${escapeHtml(track.id)}" ${selected ? "checked" : ""} aria-label="选择 ${escapeHtml(title)}">
    </td>
    <td>
      <div class="row-main">
        <span class="row-number">${String(index + 1).padStart(2, "0")}</span>
        ${cover}
        <div class="row-info">
          <div class="row-title" title="${escapeHtml(title)}">${escapeHtml(title)}</div>
          <div class="row-sub">
            ${subParts
              .map((part, partIndex) => `${partIndex ? '<span class="dot-sep">·</span>' : ""}<span title="${escapeHtml(part)}">${escapeHtml(part)}</span>`)
              .join("")}
          </div>
          <div class="row-reason" title="${escapeHtml(track.category?.reason || "")}">${icon("sparkle", 10)}<span>${escapeHtml(track.category?.reason || "按默认规则归类")}</span></div>
          ${
            !audio && isMotionPreviewable(track)
              ? `<button class="row-preview-link" type="button" data-action="preview-motion" data-id="${escapeHtml(track.id)}">${icon("play", 10)}预览动作</button>`
              : ""
          }
        </div>
      </div>
    </td>
    <td><span class="cat-list">${categories
      .slice(0, 3)
      .map(
        (item) =>
          `<span class="cat-pill" style="--accent:${escapeHtml(item.accent)}">${escapeHtml(item.name)}</span>`,
      )
      .join("")}</span></td>
    <td>
      <span class="tag-list">
        ${shownTags.map((tag) => tagChip(tag)).join("")}
        ${more > 0 ? `<span class="tag-chip is-more">+${more}</span>` : ""}
        ${!tags.length ? '<span class="tag-empty">未标记</span>' : ""}
      </span>
    </td>
    <td class="row-duration">${audio ? (track.duration ? formatDuration(track.duration) : "—") : formatSize(track.size)}</td>
    <td class="row-fav">
      <button class="fav-btn ${track.favorite ? "is-fav" : ""}" type="button" data-action="toggle-favorite" data-id="${escapeHtml(track.id)}" aria-label="${track.favorite ? "取消收藏" : "收藏"}" aria-pressed="${track.favorite ? "true" : "false"}">${icon("heart", 15)}</button>
    </td>
  </tr>`;
}

/* -------------------------------------------------------------------------- */
/* Chrome and selection                                                       */
/* -------------------------------------------------------------------------- */

function updateChrome() {
  const meta = VIEW_META[state.view] || VIEW_META.library;
  const library = state.library;
  if (!library) return;

  const pageTitle = $("#page-title");
  const pageEyebrow = $("#page-eyebrow");
  if (pageTitle) pageTitle.textContent = meta.title;
  if (pageEyebrow) pageEyebrow.textContent = meta.eyebrow;

  const counts = {
    "#nav-count-all": library.stats?.total,
    "#nav-count-categories": library.categories.length,
    "#nav-count-tags": library.tags.length,
    "#nav-count-favorites": library.stats?.favorites,
  };
  Object.entries(counts).forEach(([selector, value]) => {
    const node = $(selector);
    if (node) node.textContent = formatCount(value || 0);
  });

  $$(".nav-item").forEach((item) => {
    const active = item.dataset.view === state.view;
    item.classList.toggle("is-active", active);
    if (active) item.setAttribute("aria-current", "page");
    else item.removeAttribute("aria-current");
  });

  const search = $("#search-input");
  if (search && document.activeElement !== search && search.value !== state.search) {
    search.value = state.search;
  }

  const rescan = $("#btn-rescan");
  if (rescan) rescan.disabled = state.busy;

  $$("#view-root [data-select-all]").forEach((box) => {
    if (box.dataset.indeterminate === "true") box.indeterminate = true;
  });
}

function syncSelectAll() {
  const boxes = $$("#view-root .track-row[data-track-id]");
  const allBox = $("#view-root [data-select-all]");
  if (!allBox) return;
  if (!boxes.length) {
    allBox.checked = false;
    allBox.indeterminate = false;
    return;
  }
  const count = boxes.filter((row) => state.selected.has(row.dataset.trackId)).length;
  allBox.checked = count === boxes.length;
  allBox.indeterminate = count > 0 && count < boxes.length;
}

function updateSelectionUI() {
  const bar = $("#selection-bar");
  const count = state.selected.size;
  if (bar) bar.hidden = count === 0;

  const countEl = $("#selection-count");
  if (countEl) countEl.textContent = String(count);

  const tracks = selectedTracks();
  const favButton = $("#selection-bar [data-action='bulk-favorite']");
  if (favButton && tracks.length) {
    const allFavorite = tracks.every((track) => track.favorite);
    favButton.innerHTML = `${icon("heart", 14)}${allFavorite ? "取消收藏" : "收藏"}`;
  }

  const subcategoryButton = $("#selection-subcategory");
  if (subcategoryButton) {
    subcategoryButton.hidden = !(tracks.length && tracks.every(isSfxTrack));
  }

  syncSelectAll();
}

function refreshSelectionDom() {
  $$("#view-root .track-row[data-track-id]").forEach((row) => {
    const selected = state.selected.has(row.dataset.trackId);
    row.classList.toggle("is-selected", selected);
    row.setAttribute("aria-selected", selected ? "true" : "false");
    const checkbox = row.querySelector("[data-select]");
    if (checkbox) checkbox.checked = selected;
  });
  updateSelectionUI();
}

function clearSelection() {
  state.selected.clear();
  refreshSelectionDom();
}

function setBusy(value) {
  state.busy = value;
  const rescan = $("#btn-rescan");
  if (rescan) {
    rescan.disabled = value;
    rescan.classList.toggle("is-spinning", value);
  }
  $$("#selection-bar button").forEach((button) => {
    button.disabled = value;
  });
}

function updateRowsPlaying() {
  if (!player) return;
  const current = player.current;
  const playing = Boolean(current) && !player.audio.paused;

  $$("#view-root .track-row[data-track-id]").forEach((row) => {
    const isCurrent = Boolean(current) && row.dataset.trackId === current.id;
    row.classList.toggle("is-playing", isCurrent);
    const cover = row.querySelector(".row-cover");
    if (!cover) return;
    if (isCurrent || cover.querySelector(".playing-overlay")) {
      const track = findTrack(row.dataset.trackId);
      if (track) {
        cover.innerHTML = coverMarkup(track, {
          size: "sm",
          playing: isCurrent && playing,
        });
      }
    }
  });
}

function updateDocumentTitle() {
  if (!player?.current) {
    document.title = "声形 · Sound & Form";
    return;
  }
  const paused = player.audio.paused;
  const title = player.current.title || player.current.filename || "未命名声音";
  document.title = paused ? `${title} · 声形` : `▶ ${title} · 声形`;
}

/* -------------------------------------------------------------------------- */
/* Welcome                                                                    */
/* -------------------------------------------------------------------------- */

function renderWelcome() {
  if (player?.current) player.stop();
  document.body.classList.add("is-welcome");
  document.body.classList.remove("modal-open");
  const root = $("#welcome-root");
  if (!root) return;

  const payload = state.payload;
  const recents = payload?.recents || [];
  const error = state.welcomeError || payload?.error || "";
  const recentMarkup = recents.length
    ? recents
        .map(
          (item) => `<button class="welcome-recent-row" type="button" data-welcome-recent="${escapeHtml(item.path)}">
            <span class="recent-icon">${icon(item.exists ? "folder-open" : "alert", 15)}</span>
            <span class="welcome-recent-copy">
              <span class="welcome-recent-name">${escapeHtml(item.name || parentFolder(item.path) || item.path)}</span>
              <span class="welcome-recent-path">${escapeHtml(item.path)}</span>
            </span>
            ${item.current ? '<span class="recent-flag">当前</span>' : !item.exists ? '<span class="recent-flag is-missing">缺失</span>' : ""}
          </button>`,
        )
        .join("")
    : `<p class="welcome-empty-recent">还没有最近打开的文件夹。</p>`;

  root.innerHTML = `<section class="welcome">
    <div class="welcome-left">
      <div class="welcome-brand">
        <span class="brand-disc" aria-hidden="true"><span class="brand-disc-label">形</span></span>
        <span class="brand-type">
          <span class="brand-cn">声形</span>
          <span class="brand-en">SOUND &amp; FORM</span>
        </span>
      </div>
      <div class="welcome-mid">
        <div class="welcome-issue">ISSUE 001 · LOCAL SOUND &amp; FORM ARCHIVE</div>
        <h1 class="welcome-title">给声音与形体，<br><em>一座自己的岛。</em></h1>
        <p class="welcome-copy">声形读取你硬盘里的一个文件夹，把声音与 3D 资产放在同一张表里：自动分类、贴上标签、收进收藏，还能把一批文件整齐地重命名。没有账号，没有上传。</p>
        <div class="welcome-features">
          <span class="welcome-feature">${icon("layers", 13)}自动分类</span>
          <span class="welcome-feature">${icon("tag", 13)}自由标签</span>
          <span class="welcome-feature">${icon("heart", 13)}收藏</span>
          <span class="welcome-feature">${icon("edit", 13)}批量重命名</span>
          <span class="welcome-feature">${icon("shield", 13)}完全本地</span>
        </div>
      </div>
      <div class="welcome-foot"><span class="status-dot"></span>所有数据留在本机 · v0.2.0</div>
    </div>

    <div class="welcome-right">
      <div class="welcome-form-wrap">
        <div class="welcome-form-kicker">OPEN YOUR LIBRARY</div>
        <h2 class="welcome-form-title">先打开<em>一座岛</em></h2>
        <p class="welcome-form-sub">输入一个存有声音或 3D 资产的文件夹路径，或从电脑里选择。声形会读取它和它的子文件夹。</p>
        <form class="welcome-form" id="welcome-form">
          <div class="field">
            <label for="welcome-path">素材文件夹</label>
            <input class="input" id="welcome-path" name="path" type="text" autocomplete="off" spellcheck="false" value="${escapeHtml(state.welcomePath || "")}" placeholder="例如 D:\\Music 或 D:\\Assets">
          </div>
          <div class="welcome-form-actions">
            <button class="btn btn-primary" type="submit" id="welcome-submit">${icon("arrow-right", 15)}打开文件夹</button>
            <button class="btn btn-ghost" type="button" id="welcome-pick">${icon("folder", 15)}从电脑选择</button>
          </div>
          <div class="welcome-error" id="welcome-error">${error ? inlineError(error) : ""}</div>
          <div class="welcome-note">${icon("shield", 13)}声形只读取声音与 3D 资产的文件信息；重命名前会先给你完整预览，绝不擅自改文件。</div>
        </form>
        <div class="welcome-recents">
          <div class="welcome-recents-head">
            <span class="welcome-recents-title">RECENT ISLANDS</span>
            <span class="welcome-recents-count">${formatCount(recents.length)}</span>
          </div>
          ${recentMarkup}
        </div>
      </div>
      <div class="welcome-right-foot">支持 MP3 / FLAC / WAV / M4A / OGG / OPUS / AIFF / GLB / GLTF / FBX / OBJ / BVH / BLEND / 贴图 · 需要本机运行</div>
    </div>
  </section>`;

  hydrateIcons(root);
  setWelcomeBusy(state.welcomeBusy);
  document.title = "声形 · Sound & Form";
}

function showWelcomeError(message) {
  state.welcomeError = message || "";
  const box = $("#welcome-error");
  if (box) box.innerHTML = message ? inlineError(message) : "";
}

function setWelcomeBusy(value) {
  state.welcomeBusy = value;
  const input = $("#welcome-path");
  const submit = $("#welcome-submit");
  const pick = $("#welcome-pick");
  if (input) input.disabled = value;
  if (submit) {
    submit.disabled = value;
    submit.innerHTML = value
      ? `<span class="spinner"></span> 正在读取…`
      : `${icon("arrow-right", 15)}打开文件夹`;
  }
  if (pick) pick.disabled = value;
  $$("[data-welcome-recent]").forEach((button) => {
    button.disabled = value;
  });
}

async function welcomeOpen(pathArg) {
  if (state.welcomeBusy) return;
  const input = $("#welcome-path");
  const path = String(pathArg ?? input?.value ?? state.welcomePath ?? "").trim();
  if (!path) {
    showWelcomeError("先输入一个文件夹路径。");
    input?.focus();
    return;
  }

  state.welcomePath = path;
  state.welcomeError = "";
  const errorBox = $("#welcome-error");
  if (errorBox) errorBox.innerHTML = "";
  setWelcomeBusy(true);

  try {
    const payload = await api.openLibrary(path);
    enterLibrary(payload);
  } catch (error) {
    showWelcomeError(error.message);
    setWelcomeBusy(false);
  }
}

async function welcomePick() {
  if (state.welcomeBusy) return;
  const button = $("#welcome-pick");
  if (button) {
    button.disabled = true;
    button.innerHTML = `<span class="spinner"></span> 选择中…`;
  }
  try {
    const result = await api.pickFolder(state.welcomePath || "");
    if (result.cancelled) return;
    if (result.error) throw new Error(result.error);
    if (result.path) {
      state.welcomePath = result.path;
      const input = $("#welcome-path");
      if (input) input.value = result.path;
      await welcomeOpen(result.path);
    }
  } catch (error) {
    showWelcomeError(error.message);
  } finally {
    if (button?.isConnected) {
      button.disabled = false;
      button.innerHTML = `${icon("folder", 15)}从电脑选择`;
    }
  }
}

/* -------------------------------------------------------------------------- */
/* Library transitions                                                        */
/* -------------------------------------------------------------------------- */

function enterLibrary(payload, { announce = true } = {}) {
  if (!payload?.library) throw new Error("没有读到这个文件夹里的素材资料。");
  if (player) player.stop();
  closeModal();

  state.payload = payload;
  state.library = payload.library;
  state.view = "library";
  state.category = "all";
  state.activeTags.clear();
  state.typeFilter = "all";
  state.onlyFavorites = false;
  state.onlyPreviewable = false;
  state.search = "";
  state.sort = "default";
  state.selected.clear();
  state.welcomeBusy = false;
  state.welcomeError = "";

  const input = $("#search-input");
  if (input) input.value = "";
  const welcome = $("#welcome-root");
  if (welcome) welcome.innerHTML = "";
  document.body.classList.remove("is-welcome");
  render();
  window.scrollTo({ top: 0, behavior: "auto" });
  if (announce) toast(`已打开「${libraryName()}」`);
}

function applyLibraryResponse(library, { keepScroll = true, clearSelection: shouldClear = false } = {}) {
  if (!library) return;
  state.library = library;
  if (state.payload) state.payload.library = library;

  if (shouldClear) {
    state.selected.clear();
  } else {
    for (const id of [...state.selected]) {
      if (!library.tracks.some((track) => track.id === id)) state.selected.delete(id);
    }
  }

  for (const tag of [...state.activeTags]) {
    if (!library.tags.some((item) => norm(item.name) === norm(tag))) {
      state.activeTags.delete(tag);
    }
  }

  if (player?.current && !library.tracks.some((track) => track.id === player.current.id)) {
    player.stop();
  }
  render({ keepScroll });
}

/* -------------------------------------------------------------------------- */
/* View switching                                                             */
/* -------------------------------------------------------------------------- */

function setView(view) {
  if (!state.library || !VIEW_META[view]) return;
  state.view = view;
  state.category = "all";
  state.search = "";
  state.selected.clear();
  const search = $("#search-input");
  if (search) search.value = "";
  closeSidebar();
  render();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

const SAVED_VIEWS_KEY = "soundform.savedViews.v1";

function loadSavedViews() {
  try {
    const parsed = JSON.parse(localStorage.getItem(SAVED_VIEWS_KEY) || "[]");
    return Array.isArray(parsed) ? parsed.filter((item) => item && item.name) : [];
  } catch {
    return [];
  }
}

function persistSavedViews(views) {
  try {
    localStorage.setItem(SAVED_VIEWS_KEY, JSON.stringify(views.slice(0, 12)));
  } catch {
    // ignore storage restrictions
  }
}

function saveCurrentView() {
  const suggested = `${VIEW_META[state.view]?.title || "视图"} ${loadSavedViews().length + 1}`;
  const name = window.prompt("给这个视图起个名字", suggested)?.trim();
  if (!name) return;
  const views = loadSavedViews().filter((item) => item.name !== name);
  views.unshift({
    name,
    view: state.view,
    category: state.category,
    search: state.search,
    sort: state.sort,
    typeFilter: state.typeFilter,
    onlyFavorites: state.onlyFavorites,
    onlyPreviewable: state.onlyPreviewable,
    activeTags: [...state.activeTags],
  });
  persistSavedViews(views);
  render({ keepScroll: true });
  toast(`已保存视图「${name}」。`);
}

function applySavedView(name) {
  const view = loadSavedViews().find((item) => item.name === name);
  if (!view) return;
  state.view = VIEW_META[view.view] ? view.view : "library";
  state.category = view.category || "all";
  state.search = view.search || "";
  state.sort = SORT_OPTIONS.some(([value]) => value === view.sort) ? view.sort : "default";
  state.typeFilter = ["all", "audio", "asset"].includes(view.typeFilter) ? view.typeFilter : "all";
  state.onlyFavorites = Boolean(view.onlyFavorites);
  state.onlyPreviewable = Boolean(view.onlyPreviewable);
  state.activeTags = new Set(Array.isArray(view.activeTags) ? view.activeTags : []);
  state.selected.clear();
  const search = $("#search-input");
  if (search) search.value = state.search;
  render();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

async function exportMetadata() {
  if (!state.library) return;
  try {
    const result = await api.exportMetadata();
    const blob = new Blob([JSON.stringify(result.metadata, null, 2)], {
      type: "application/json;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `声形-资料备份-${new Date().toISOString().slice(0, 10)}.json`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 2000);
    toast("资料已导出；文件内容没有写入这个备份。");
  } catch (error) {
    toast(error.message, { type: "error" });
  }
}

async function importMetadata(file) {
  if (!file || !state.library) return;
  try {
    const text = await file.text();
    const metadata = JSON.parse(text);
    if (!window.confirm("导入只会改标签、收藏和分类资料，不会移动或改写素材。继续吗？")) return;
    const result = await api.importMetadata(metadata);
    applyLibraryResponse(result.library, { clearSelection: true });
    toast(result.message || "资料已导入。");
  } catch (error) {
    toast(error instanceof SyntaxError ? "这个文件不是有效的 JSON。" : error.message, { type: "error" });
  }
}

function toggleActiveTag(tag) {
  if (!state.library) return;
  const wanted = String(tag || "").trim();
  if (!wanted) return;
  const existing = [...state.activeTags].find((item) => norm(item) === norm(wanted));
  if (existing) state.activeTags.delete(existing);
  else state.activeTags.add(wanted);
  render({ keepScroll: true });
}

function openMissingFiles() {
  const missing = state.library?.missing || [];
  if (!missing.length) {
    toast("没有发现缺失文件。");
    return;
  }
  const groups = new Map();
  missing.forEach((item) => {
    const key = item.source_id || "";
    if (!groups.has(key)) {
      groups.set(key, { name: item.source_name || "素材文件夹", path: item.source_path || "", items: [] });
    }
    groups.get(key).items.push(item);
  });
  const body = [...groups.entries()]
    .map(
      ([sourceId, group]) => `<div class="health-group">
        <div class="health-group-head">
          <div><strong>${escapeHtml(group.name)}</strong><span>${escapeHtml(group.path)}</span></div>
          <button class="btn btn-quiet btn-small" type="button" data-missing-dismiss="${escapeHtml(sourceId)}">${icon("x", 12)}从缺失列表移除</button>
        </div>
        <div class="health-list">
          ${group.items
            .map(
              (item) => `<div class="health-row">
                <span class="health-row-name">${escapeHtml(item.filename || item.rel_path)}</span>
                <span class="health-row-path">${escapeHtml(item.rel_path)}</span>
              </div>`,
            )
            .join("")}
        </div>
      </div>`,
    )
    .join("");
  const modal = openModal({
    kicker: "SOURCE HEALTH",
    title: "缺失文件",
    sub: "这些文件曾经在素材库里，现在找不到了。只清理索引，不会删除磁盘上的任何东西。",
    body: `<div class="health-shell">${body}</div>`,
    foot: `<button class="btn btn-ghost" type="button" data-close>关闭</button>`,
    wide: true,
  });
  modal.layer.querySelectorAll("[data-missing-dismiss]").forEach((button) => {
    button.addEventListener("click", async () => {
      const sourceId = button.dataset.missingDismiss || "";
      const group = groups.get(sourceId);
      if (!group) return;
      button.disabled = true;
      try {
        const result = await api.dismissMissing(sourceId, group.items.map((item) => item.rel_path));
        applyLibraryResponse(result.library);
        closeModal();
        toast(result.message || "已从缺失列表移除。");
      } catch (error) {
        button.disabled = false;
        toast(error.message, { type: "error" });
      }
    });
  });
}

function openDuplicates() {
  const groups = state.library?.duplicates || [];
  if (!groups.length) {
    toast("没有发现重复文件。");
    return;
  }
  const body = groups
    .map(
      (group, index) => `<div class="health-group">
        <div class="health-group-head">
          <div><strong>第 ${index + 1} 组 · ${formatSize(group.size)}</strong><span>内容相同 · ${group.tracks.length} 个文件</span></div>
        </div>
        <div class="health-list">
          ${group.tracks
            .map(
              (track) => `<button class="health-row health-row-button" type="button" data-duplicate-id="${escapeHtml(track.id)}">
                <span class="health-row-name">${escapeHtml(track.title || track.rel_path)}</span>
                <span class="health-row-path">${escapeHtml(track.rel_path)}</span>
              </button>`,
            )
            .join("")}
        </div>
      </div>`,
    )
    .join("");
  const modal = openModal({
    kicker: "DUPLICATE CHECK",
    title: "重复文件",
    sub: "按文件大小与内容指纹判断；不会自动删除任何文件。点一项可以查看详情。",
    body: `<div class="health-shell">${body}</div>`,
    foot: `<button class="btn btn-ghost" type="button" data-close>关闭</button>`,
    wide: true,
  });
  modal.layer.querySelectorAll("[data-duplicate-id]").forEach((button) => {
    button.addEventListener("click", () => {
      const id = button.dataset.duplicateId || "";
      closeModal();
      openInspect(id);
    });
  });
}

function openTagFilter() {
  const tags = state.library?.tags || [];
  const chosen = new Set(state.activeTags);
  const body = tags.length
    ? `<p class="picker-copy">标签筛选会同时满足选中的标签；例如选「夜晚」和「学习」，只显示同时带有这两个标签的素材。</p>
      <div class="tag-filter-choices">
        ${tags
          .map(
            (item) => `<label class="tag-filter-choice">
              <input type="checkbox" data-tag-choice="${escapeHtml(item.name)}" ${chosen.has(item.name) ? "checked" : ""}>
              <span class="tag-chip" style="--tag-h:${tagHue(item.name)}">${escapeHtml(item.name)}</span>
              <span class="tag-filter-choice-count">${formatCount(item.count)}</span>
            </label>`,
          )
          .join("")}
      </div>`
    : emptyState({
        title: "还没有标签",
        copy: "先在表格里勾选素材，用「加标签」给它们贴一个标签。",
      });
  const modal = openModal({
    kicker: "TAG FILTER",
    title: "按标签筛选",
    sub: "标签不会删除，也不会改变文件；这里只是换一种查看方式。",
    body,
    narrow: true,
    foot: `<button class="btn btn-quiet" type="button" data-tag-clear>${icon("refresh", 12)}清除</button>
      <button class="btn btn-primary" type="button" data-tag-apply>应用筛选</button>`,
  });
  const layer = modal.layer;
  layer.addEventListener("change", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLInputElement) || !target.matches("[data-tag-choice]")) return;
    if (target.checked) chosen.add(target.dataset.tagChoice);
    else chosen.delete(target.dataset.tagChoice);
  });
  layer.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof Element)) return;
    if (target.closest("[data-tag-clear]")) {
      state.activeTags.clear();
      closeModal();
      render({ keepScroll: true });
      return;
    }
    if (target.closest("[data-tag-apply]")) {
      state.activeTags = chosen;
      closeModal();
      render({ keepScroll: true });
    }
  });
}

function filterTag(tag) {
  toggleActiveTag(tag);
}

function filterCategory(key) {
  if (!state.library) return;
  const wasCategories = state.view === "categories";
  state.view = "categories";
  state.selected.clear();
  if (!wasCategories) {
    state.search = "";
    const search = $("#search-input");
    if (search) search.value = "";
  }
  state.category = state.category === key ? "all" : key || "all";
  closeSidebar();
  render();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function openSidebar() {
  $("#sidebar")?.classList.add("is-open");
  const scrim = $("#nav-scrim");
  if (scrim) scrim.hidden = false;
  $("#btn-menu")?.setAttribute("aria-expanded", "true");
}

function closeSidebar() {
  $("#sidebar")?.classList.remove("is-open");
  const scrim = $("#nav-scrim");
  if (scrim) scrim.hidden = true;
  $("#btn-menu")?.setAttribute("aria-expanded", "false");
}

/* -------------------------------------------------------------------------- */
/* Actions                                                                    */
/* -------------------------------------------------------------------------- */

function playVisible(shuffle = false) {
  let queue = audioTracks();
  if (!queue.length || !player) return;
  if (shuffle) {
    for (let i = queue.length - 1; i > 0; i -= 1) {
      const j = Math.floor(Math.random() * (i + 1));
      [queue[i], queue[j]] = [queue[j], queue[i]];
    }
  }
  if (player.current?.id === queue[0].id) {
    player.resume();
    return;
  }
  player.playTrack(queue[0], queue);
}

async function toggleTrackFavorite(track) {
  if (!track || state.busy) return;
  const favorite = !track.favorite;
  setBusy(true);
  try {
    const result = await api.setFavorite([track.id], favorite);
    if (!result.library) return;
    applyLibraryResponse(result.library);
    player.setFavoriteState(track.id, favorite);
    rememberUndo(favorite ? "已收进收藏" : "已取消收藏", async () => {
      const undoResult = await api.setFavorite([track.id], !favorite);
      if (undoResult.library) {
        applyLibraryResponse(undoResult.library);
        player.setFavoriteState(track.id, !favorite);
      }
    });
  } catch (error) {
    toast(error.message, { type: "error" });
  } finally {
    setBusy(false);
  }
}

async function bulkFavorite() {
  const tracks = selectedTracks();
  if (!tracks.length || state.busy) return;
  const favorite = !tracks.every((track) => track.favorite);
  const before = tracks.map((track) => ({ id: track.id, favorite: Boolean(track.favorite) }));
  setBusy(true);
  try {
    const result = await api.setFavorite(tracks.map((track) => track.id), favorite);
    if (!result.library) return;
    applyLibraryResponse(result.library, { clearSelection: true });
    rememberUndo(favorite ? `已收藏 ${tracks.length} 项` : `已取消 ${tracks.length} 项的收藏`, async () => {
      const groups = new Map();
      for (const item of before) {
        if (!groups.has(item.favorite)) groups.set(item.favorite, []);
        groups.get(item.favorite).push(item.id);
      }
      let lastResult = null;
      for (const [value, ids] of groups) lastResult = await api.setFavorite(ids, value);
      if (lastResult?.library) applyLibraryResponse(lastResult.library, { clearSelection: true });
    });
  } catch (error) {
    toast(error.message, { type: "error" });
  } finally {
    setBusy(false);
  }
}

async function rescanLibrary() {
  if (!state.library || state.busy) return;
  setBusy(true);
  try {
    const result = await api.rescan();
    if (!result.library) return;
    applyLibraryResponse(result.library);
    toast(result.message || "扫描完成");
  } catch (error) {
    toast(error.message, { type: "error" });
  } finally {
    setBusy(false);
  }
}

function handleViewClick(event) {
  const target = event.target;
  const actionNode = target.closest("[data-action]");
  if (actionNode) {
    const action = actionNode.dataset.action;
    const tag = actionNode.dataset.tag;
    const category = actionNode.dataset.category;
    const id = actionNode.dataset.id;

    switch (action) {
      case "toggle-favorite": {
        event.preventDefault();
        const track = findTrack(id);
        if (track) toggleTrackFavorite(track);
        return;
      }
      case "filter-tag":
      case "toggle-tag":
        event.preventDefault();
        toggleActiveTag(tag);
        return;
      case "open-tag-filter":
        event.preventDefault();
        openTagFilter();
        return;
      case "open-missing":
        event.preventDefault();
        openMissingFiles();
        return;
      case "open-duplicates":
        event.preventDefault();
        openDuplicates();
        return;
      case "save-view":
        event.preventDefault();
        saveCurrentView();
        return;
      case "open-waveform":
        event.preventDefault();
        openWaveform();
        return;
      case "export-metadata":
        event.preventDefault();
        exportMetadata();
        return;
      case "import-metadata":
        event.preventDefault();
        $("#metadata-import")?.click();
        return;
      case "toggle-favorites-filter":
        event.preventDefault();
        state.onlyFavorites = !state.onlyFavorites;
        state.selected.clear();
        render({ keepScroll: true });
        return;
      case "toggle-preview-filter":
        event.preventDefault();
        state.onlyPreviewable = !state.onlyPreviewable;
        state.selected.clear();
        render({ keepScroll: true });
        return;
      case "filter-category":
        event.preventDefault();
        filterCategory(category);
        return;
      case "open-category":
        event.preventDefault();
        openCategoryDrawer(category);
        return;
      case "open-subcategory":
        event.preventDefault();
        openCategoryDrawer(actionNode.dataset.category || "sfx", actionNode.dataset.sub || "");
        return;
      case "create-category":
        event.preventDefault();
        openCreateCategoryModal();
        return;
      case "preview-motion":
        event.preventDefault();
        openMotionPreview(id);
        return;
      case "play-all":
        event.preventDefault();
        playVisible(false);
        return;
      case "shuffle":
        event.preventDefault();
        playVisible(true);
        return;
      case "shuffle-inspect": {
        event.preventDefault();
        const assets = state.visibleTracks.filter((track) => !isAudio(track));
        if (assets.length) openInspect(assets[Math.floor(Math.random() * assets.length)].id);
        return;
      }
      case "open-inspect":
        event.preventDefault();
        openInspect(id);
        return;
      case "go-categories":
        event.preventDefault();
        setView("categories");
        return;
      case "go-library":
        event.preventDefault();
        setView("library");
        return;
      case "clear-search":
        event.preventDefault();
        state.search = "";
        const search = $("#search-input");
        if (search) search.value = "";
        state.selected.clear();
        render({ keepScroll: true });
        return;
      case "reset-sort":
        event.preventDefault();
        state.sort = "default";
        render({ keepScroll: true });
        return;
      case "rescan":
        event.preventDefault();
        rescanLibrary();
        return;
      case "open-folder":
      case "add-folder":
        event.preventDefault();
        openFolderModal();
        return;
      case "remove-source":
        event.preventDefault();
        removeSource(actionNode.dataset.sourceId || "");
        return;
      case "rescan-source":
        event.preventDefault();
        rescanSource(actionNode.dataset.sourceId || "");
        return;
      default:
        break;
    }
  }

  if (target.closest("button, a, input, label, select, textarea")) return;
  const row = target.closest(".track-row[data-track-id]");
  if (!row) return;
  const track = findTrack(row.dataset.trackId);
  if (!track) return;

  if (!isAudio(track)) {
    openInspect(track.id);
    return;
  }

  if (player.current?.id === track.id) {
    player.toggle();
  } else {
    player.playTrack(track, audioTracks());
  }
  updateRowsPlaying();
  updateDocumentTitle();
}

function handleViewChange(event) {
  const target = event.target;
  if (!(target instanceof Element)) return;

  if (target.id === "metadata-import") {
    importMetadata(target.files?.[0]);
    target.value = "";
    return;
  }

  const selectAll = target.closest("[data-select-all]");
  if (selectAll) {
    state.visibleTracks.forEach((track) => {
      if (selectAll.checked) state.selected.add(track.id);
      else state.selected.delete(track.id);
    });
    refreshSelectionDom();
    return;
  }

  const checkbox = target.closest("[data-select]");
  if (checkbox) {
    const id = checkbox.dataset.select;
    if (event.shiftKey && lastSelectedId && checkbox.checked) {
      const ids = state.visibleTracks.map((track) => track.id);
      const from = ids.indexOf(lastSelectedId);
      const to = ids.indexOf(id);
      if (from >= 0 && to >= 0) {
        const [start, end] = from < to ? [from, to] : [to, from];
        for (let index = start; index <= end; index += 1) state.selected.add(ids[index]);
        refreshSelectionDom();
        lastSelectedId = id;
        return;
      }
    }
    if (checkbox.checked) state.selected.add(id);
    else state.selected.delete(id);
    lastSelectedId = id;
    const row = checkbox.closest(".track-row");
    if (row) {
      row.classList.toggle("is-selected", checkbox.checked);
      row.setAttribute("aria-selected", checkbox.checked ? "true" : "false");
    }
    updateSelectionUI();
    return;
  }

  const typeFilter = target.closest("[data-type-filter]");
  if (typeFilter) {
    state.typeFilter = typeFilter.value;
    state.selected.clear();
    render({ keepScroll: true });
    return;
  }

  const savedView = target.closest("[data-saved-view]");
  if (savedView) {
    if (savedView.value) applySavedView(savedView.value);
    savedView.value = "";
    return;
  }

  const sort = target.closest("[data-sort]");
  if (sort) {
    state.sort = sort.value;
    render({ keepScroll: true });
  }
}

function handleSelectionAction(event) {
  const actionNode = event.target.closest("[data-action]");
  if (!actionNode) return;
  const action = actionNode.dataset.action;
  switch (action) {
    case "clear-selection":
      clearSelection();
      break;
    case "bulk-tag":
      openTagEditor();
      break;
    case "bulk-category":
      openCategoryPicker();
      break;
    case "bulk-subcategory":
      openCategoryPicker(null, { subcategory: true });
      break;
    case "bulk-favorite":
      bulkFavorite();
      break;
    case "bulk-rename":
      openRenameModal();
      break;
    default:
      break;
  }
}

/* -------------------------------------------------------------------------- */
/* Modals                                                                     */
/* -------------------------------------------------------------------------- */

function openModal({
  kicker = "",
  title = "",
  sub = "",
  body = "",
  foot = "",
  wide = false,
  narrow = false,
  onMount = null,
  onClose = null,
} = {}) {
  closeModal();
  lastModalFocus = document.activeElement;

  const layer = document.createElement("div");
  layer.className = "modal-layer";
  layer.innerHTML = `<div class="modal ${wide ? "is-wide" : ""} ${narrow ? "is-narrow" : ""}" role="dialog" aria-modal="true" aria-labelledby="modal-title">
    <div class="modal-head">
      ${kicker ? `<span class="modal-kicker">${escapeHtml(kicker)}</span>` : ""}
      <h2 class="modal-title" id="modal-title">${escapeHtml(title)}</h2>
      ${sub ? `<p class="modal-sub">${escapeHtml(sub)}</p>` : ""}
      <button class="modal-close" type="button" data-close aria-label="关闭">${icon("x", 15)}</button>
    </div>
    <div class="modal-body">${body}</div>
    ${foot ? `<div class="modal-foot">${foot}</div>` : ""}
  </div>`;

  layer.addEventListener("click", (event) => {
    if (!(event.target instanceof Element)) return;
    if (event.target === layer || event.target.closest("[data-close]")) {
      closeModal();
    }
  });

  $("#modal-root")?.appendChild(layer);
  document.body.classList.add("modal-open");
  modalOnClose = onClose;
  if (onMount) onMount(layer);
  return { layer, modal: layer.querySelector(".modal") };
}

function closeModal() {
  const root = $("#modal-root");
  if (!root) return;
  const layer = root.querySelector(".modal-layer");
  const callback = modalOnClose;
  modalOnClose = null;
  if (layer) layer.remove();
  document.body.classList.remove("modal-open");
  if (lastModalFocus?.isConnected) {
    try {
      lastModalFocus.focus({ preventScroll: true });
    } catch {
      // focus restoration is best effort
    }
  }
  lastModalFocus = null;
  if (callback) callback();
}

/* -------------------------------------------------------------------------- */
/* Category drawers and taxonomy                                              */
/* -------------------------------------------------------------------------- */

function categoryByKey(key) {
  return state.library?.categories.find((category) => category.key === key) || null;
}

function isSfxTrack(track) {
  return isAudio(track) && track.category?.key === "sfx";
}

function isMotionPreviewable(track) {
  if (!track || isAudio(track)) return false;
  const suffix = `.${String(track.filename || "").split(".").pop().toLowerCase()}`;
  if (suffix === ".bvh" || suffix === ".fbx") return true;
  return (suffix === ".glb" || suffix === ".gltf") && Number(track.stats?.animations || 0) > 0;
}

function isSkinPreviewable(track) {
  if (!track || isAudio(track)) return false;
  const suffix = `.${String(track.filename || "").split(".").pop().toLowerCase()}`;
  return suffix === ".glb" || suffix === ".gltf" || suffix === ".fbx";
}

async function openSkinPreview(id, { onReturn = null } = {}) {
  const track = findTrack(id);
  if (!track || state.busy) return;
  let dispose = null;
  const modal = openModal({
    kicker: "SKINNED PREVIEW",
    title: track.title || track.filename || "蒙皮预览",
    sub: `${String(track.format || "").toUpperCase()} · 骨骼与蒙皮预览 · 只读`,
    wide: true,
    body: `<div class="skin-preview">
      <div class="skin-stage" data-skin-canvas>
        <div class="skin-hud"><span class="skin-hud-label">VIEWPORT / LIVE</span><span class="skin-hud-value" data-skin-status>正在读取模型…</span></div>
      </div>
      <aside class="skin-side">
        <h3 class="skin-side-title">${escapeHtml(track.title || track.filename || "模型")}</h3>
        <p class="skin-side-path">${escapeHtml(track.rel_path || "")}</p>
        <p class="skin-status" data-skin-status>正在读取模型…</p>
        <p class="skin-meta" data-skin-meta></p>
        <p class="skin-materials" data-skin-materials></p>
        <div class="skin-controls">
          <label class="skin-control">动画
            <select class="select-input" data-skin-animation><option value="">静态模型</option></select>
          </label>
          <label class="skin-check"><input type="checkbox" data-skin-wire> 线框模式</label>
          <div class="skin-actions">
            <button class="btn btn-quiet btn-small" type="button" data-skin-reset>${icon("refresh", 12)}重置视角</button>
            <button class="btn btn-quiet btn-small" type="button" data-skin-shot>${icon("copy", 12)}保存截图</button>
          </div>
          <p class="skin-note">拖拽旋转、滚轮缩放、右键平移。预览只读，不会修改原始素材。</p>
        </div>
      </aside>
    </div>`,
    foot: `<button class="btn btn-ghost" type="button" data-preview-back>${icon("arrow-left", 13)}${onReturn ? "返回分类" : "返回详情"}</button>`,
    onMount: (layer) => {
      const container = layer.querySelector(".skin-preview");
      try {
        dispose = mountSkinPreview(container, track);
      } catch (error) {
        layer.querySelectorAll("[data-skin-status]").forEach((node) => {
          node.textContent = error.message;
          node.classList.add("is-bad");
        });
      }
    },
    onClose: () => {
      if (dispose) {
        try {
          dispose();
        } catch {
          // already disposed
        }
        dispose = null;
      }
      if (modal?.layer?.isConnected === false) {
        if (onReturn) onReturn();
        else openInspect(id);
      }
    },
  });
  modal.layer.classList.add("skin-layer");
  modal.layer.querySelector("[data-preview-back]")?.addEventListener("click", () => closeModal());
}

function drawerRowMarkup(track, selected = false, categoryKey = "") {
  const audio = isAudio(track);
  const current = audio && player?.current?.id === track.id;
  const playing = current && !player.audio.paused;
  const memberships = trackCategories(track);
  const cover = audio
    ? `<span class="drawer-cover">${coverMarkup(track, { size: "sm", playing })}</span>`
    : `<span class="drawer-cover drawer-cover-asset">${plateMarkup(track, { size: "sm" })}</span>`;
  const sub = [
    audio ? track.artist || "未知艺术家" : track.format || "ASSET",
    track.filename || "",
  ]
    .filter(Boolean)
    .map((value) => `<span>${escapeHtml(value)}</span>`)
    .join('<span class="dot-sep">·</span>');
  return `<div class="drawer-row ${current ? "is-playing" : ""} ${selected ? "is-selected" : ""}" data-drawer-id="${escapeHtml(track.id)}" data-kind="${audio ? "audio" : "asset"}">
    <label class="drawer-check" title="选择这项素材">
      <input type="checkbox" data-drawer-check="${escapeHtml(track.id)}" ${selected ? "checked" : ""} aria-label="选择 ${escapeHtml(track.title || track.filename || "素材")}">
      <span></span>
    </label>
    ${cover}
    <div class="drawer-copy">
      <div class="drawer-title">${escapeHtml(track.title || track.filename || "未命名素材")}</div>
      <div class="drawer-sub">${sub}</div>
      <div class="drawer-reason">${escapeHtml(track.category?.reason || "按默认规则归类")}${track.category?.subcategory ? ` · ${escapeHtml(track.category.subcategory.name)}` : ""}</div>
    </div>
    <span class="drawer-meta">${audio ? (track.duration ? formatDuration(track.duration) : "—") : formatSize(track.size)}</span>
    <span class="drawer-actions">
      ${
        audio
          ? `<button class="drawer-action" type="button" data-drawer-play="${escapeHtml(track.id)}" aria-label="${playing ? "暂停" : "试听"}">${icon(playing ? "pause" : "play", 15)}</button>`
          : `<button class="drawer-action" type="button" data-drawer-inspect="${escapeHtml(track.id)}" aria-label="查看详情">${icon("arrow-right", 15)}</button>`
      }
      ${
        !audio && isMotionPreviewable(track)
          ? `<button class="drawer-action" type="button" data-drawer-motion="${escapeHtml(track.id)}" aria-label="骨骼预览" title="骨骼预览">${icon("bone", 15)}</button>`
          : ""
      }
      ${
        !audio && isSkinPreviewable(track)
          ? `<button class="drawer-action" type="button" data-drawer-skin="${escapeHtml(track.id)}" aria-label="蒙皮预览" title="蒙皮预览">${icon("cube", 15)}</button>`
          : ""
      }
      <button class="drawer-action drawer-action-muted" type="button" data-drawer-copy="${escapeHtml(track.id)}" aria-label="复制路径" title="复制路径">${icon("copy", 12)}</button>
      <button class="drawer-action drawer-action-muted" type="button" data-drawer-tags="${escapeHtml(track.id)}" aria-label="编辑标签" title="编辑标签">${icon("tag", 12)}</button>
      <button class="drawer-action drawer-action-muted drawer-action-adjust" type="button" data-drawer-reveal="${escapeHtml(track.id)}" aria-label="在文件夹中显示" title="在文件夹中显示">${icon("folder", 12)}</button>
      <button class="drawer-action drawer-action-muted drawer-action-adjust" type="button" data-drawer-category="${escapeHtml(track.id)}" aria-label="调整分类" title="调整分类">${icon("layers", 12)}<span>调整</span></button>
      ${categoryKey ? `<button class="drawer-action drawer-action-muted drawer-action-adjust" type="button" data-drawer-remove="${escapeHtml(track.id)}" data-category-key="${escapeHtml(categoryKey)}" aria-label="从此分类移除" title="从此分类移除">${icon("minus", 12)}<span>移除</span></button>` : ""}
    </span>
  </div>`;
}

function drawerBody(category, subKey, selected = new Set()) {
  let tracks = (state.library?.tracks || []).filter((track) => trackInCategory(track, category.key));
  const subs = category.subcategories || [];
  if (subKey) tracks = tracks.filter((track) => track.category?.subcategory?.key === subKey);
  const visibleSelected = tracks.filter((track) => selected.has(track.id));
  const allSelected = tracks.length > 0 && visibleSelected.length === tracks.length;
  const body = tracks.length
    ? tracks.map((track) => drawerRowMarkup(track, selected.has(track.id), category.key)).join("")
    : emptyState({
        title: "这个抽屉还是空的",
        copy: "可以给素材手动改分类，或换一个抽屉看看。",
      });
  const disabled = visibleSelected.length ? "" : "disabled";
  return `<div class="drawer-summary">
      <span class="drawer-count">${formatCount(tracks.length)}</span>
      <span class="drawer-count-label">${category.domain === "audio" ? "段声音" : "项素材"}</span>
      <span class="drawer-rule"></span>
      <span class="drawer-hint">${escapeHtml(category.hint || category.description || "")}</span>
    </div>
    <div class="drawer-batch">
      <label class="drawer-selectall"><input type="checkbox" data-drawer-selectall ${allSelected ? "checked" : ""} ${tracks.length ? "" : "disabled"}> 全选</label>
      <span class="drawer-batch-count" data-drawer-selected-count>${formatCount(visibleSelected.length)} 项已选</span>
      <span class="drawer-batch-rule"></span>
      <button class="drawer-batch-btn" type="button" data-drawer-bulk="tag" ${disabled}>${icon("tag", 12)}加标签</button>
      <button class="drawer-batch-btn" type="button" data-drawer-bulk="favorite" ${disabled}>${icon("heart", 12)}收藏</button>
      <button class="drawer-batch-btn" type="button" data-drawer-bulk="category" ${disabled}>${icon("layers", 12)}移动分类</button>
      <button class="drawer-batch-btn" type="button" data-drawer-bulk="rename" ${disabled}>${icon("edit", 12)}重命名</button>
    </div>
    ${
      subs.length
        ? `<div class="drawer-subchips">
            <button class="subcategory-chip ${!subKey ? "is-active" : ""}" type="button" data-drawer-sub="">全部 ${formatCount(category.count)}</button>
            ${subs
              .map(
                (item) => `<button class="subcategory-chip ${subKey === item.key ? "is-active" : ""}" type="button" data-drawer-sub="${escapeHtml(item.key)}">${escapeHtml(item.name)}<span>${formatCount(item.count)}</span></button>`,
              )
              .join("")}
          </div>`
        : ""
    }
    <div class="drawer-list" data-drawer-list>${body}</div>
    <p class="drawer-footnote">${icon("shield", 11)} 试听与查看都在本机进行；播放队列只包含声音，不会把 3D 文件送进播放器。</p>`;
}

function openCategoryDrawer(categoryKey, subKey = "") {
  const category = categoryByKey(categoryKey);
  if (!category) return;
  let activeSub = subKey || "";
  const drawerSelected = new Set();
  const build = () => drawerBody(category, activeSub, drawerSelected);
  const hint =
    category.domain === "audio"
      ? "点一条声音即可试听。"
      : category.domain === "custom"
        ? "声音可以试听，资产可以查看详情。"
        : category.key === "animation"
          ? "点一行查看详情，或直接打开动作预览。"
          : "点一行查看详情。";
  const modal = openModal({
    kicker: "CATEGORY DRAWER",
    title: category.name,
    sub: `${category.description || category.hint || "打开抽屉，看看里面有什么。"} · ${hint}`,
    body: build(),
    wide: true,
    foot: `<button class="btn btn-quiet" type="button" data-drawer-filter>${icon("layers", 13)}在表格中查看</button>
      ${!category.parent ? `<button class="btn btn-quiet" type="button" data-drawer-create-child>${icon("plus", 13)}新建小类</button>` : ""}
      <button class="btn btn-ghost" type="button" data-close>关闭</button>`,
  });
  const layer = modal.layer;
  layer.classList.add("drawer-layer");
  layer.dataset.category = categoryKey;
  layer.dataset.sub = activeSub;

  const repaint = () => {
    const body = layer.querySelector(".modal-body");
    if (!body) return;
    const list = body.querySelector("[data-drawer-list]");
    const scroll = list?.scrollTop || 0;
    body.innerHTML = build();
    hydrateIcons(body);
    const nextList = body.querySelector("[data-drawer-list]");
    if (nextList) nextList.scrollTop = scroll;
    layer.dataset.sub = activeSub;
  };

  const currentDrawerTracks = () => {
    let tracks = (state.library?.tracks || []).filter((track) => trackInCategory(track, categoryKey));
    if (activeSub) tracks = tracks.filter((track) => track.category?.subcategory?.key === activeSub);
    return tracks;
  };

  layer.addEventListener("change", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLInputElement)) return;
    if (target.matches("[data-drawer-check]")) {
      const id = target.dataset.drawerCheck;
      if (target.checked) drawerSelected.add(id);
      else drawerSelected.delete(id);
      repaint();
      return;
    }
    if (target.matches("[data-drawer-selectall]")) {
      const ids = currentDrawerTracks().map((track) => track.id);
      if (target.checked) ids.forEach((id) => drawerSelected.add(id));
      else ids.forEach((id) => drawerSelected.delete(id));
      repaint();
    }
  });

  layer.addEventListener("click", async (event) => {
    const target = event.target;
    if (!(target instanceof Element)) return;

    const bulk = target.closest("[data-drawer-bulk]");
    if (bulk) {
      const ids = [...drawerSelected];
      if (!ids.length) return;
      const action = bulk.dataset.drawerBulk;
      if (action === "tag") {
        closeModal();
        openTagEditor(ids);
      } else if (action === "category") {
        closeModal();
        openCategoryPicker(ids);
      } else if (action === "rename") {
        closeModal();
        openRenameModal(ids);
      } else if (action === "favorite") {
        closeModal();
        state.busy = true;
        try {
          const result = await api.setFavorite(ids, true);
          if (result.library) {
            applyLibraryResponse(result.library, { clearSelection: true });
            toast(`已收藏 ${ids.length} 项`);
          }
        } catch (error) {
          toast(error.message, { type: "error" });
        } finally {
          state.busy = false;
          refreshSelectionDom();
        }
      }
      return;
    }

    const subButton = target.closest("[data-drawer-sub]");
    if (subButton) {
      activeSub = subButton.dataset.drawerSub || "";
      repaint();
      return;
    }

    const play = target.closest("[data-drawer-play]");
    if (play) {
      const track = findTrack(play.dataset.drawerPlay);
      if (!track) return;
      const visible = (state.library?.tracks || []).filter((item) => trackInCategory(item, categoryKey));
      const queue = audioTracks(activeSub ? visible.filter((item) => item.category?.subcategory?.key === activeSub) : visible);
      if (player?.current?.id === track.id) player.toggle();
      else player.playTrack(track, queue);
      updateRowsPlaying();
      updateDocumentTitle();
      window.setTimeout(repaint, 50);
      return;
    }

    const motionButton = target.closest("[data-drawer-motion]");
    if (motionButton) {
      const id = motionButton.dataset.drawerMotion;
      closeModal();
      openMotionPreview(id, { onReturn: () => openCategoryDrawer(categoryKey, activeSub) });
      return;
    }

    const skinButton = target.closest("[data-drawer-skin]");
    if (skinButton) {
      const id = skinButton.dataset.drawerSkin;
      closeModal();
      openSkinPreview(id, { onReturn: () => openCategoryDrawer(categoryKey, activeSub) });
      return;
    }

    const copyButton = target.closest("[data-drawer-copy]");
    if (copyButton) {
      try {
        const result = await api.inspect(copyButton.dataset.drawerCopy);
        if (result?.asset?.absolute_path) await copyText(result.asset.absolute_path);
      } catch (error) {
        toast(error.message, { type: "error" });
      }
      return;
    }

    const tagsButton = target.closest("[data-drawer-tags]");
    if (tagsButton) {
      openTagEditor([tagsButton.dataset.drawerTags]);
      return;
    }

    const inspect = target.closest("[data-drawer-inspect]");
    if (inspect) {
      closeModal();
      openInspect(inspect.dataset.drawerInspect);
      return;
    }

    const reveal = target.closest("[data-drawer-reveal]");
    if (reveal) {
      await api.reveal(reveal.dataset.drawerReveal).catch((error) => toast(error.message, { type: "error" }));
      return;
    }

    const remove = target.closest("[data-drawer-remove]");
    if (remove) {
      try {
        const track = findTrack(remove.dataset.drawerRemove);
        const beforeKeys = track ? trackCategories(track).map((item) => item.key) : [];
        const result = await api.removeFromCategory([remove.dataset.drawerRemove], remove.dataset.categoryKey);
        if (result.library) {
          applyLibraryResponse(result.library, { keepScroll: true });
          rememberUndo("已从这个分类移除，素材本身没有删除。", async () => {
            const undoResult = await api.setMemberships([remove.dataset.drawerRemove], beforeKeys);
            if (undoResult.library) applyLibraryResponse(undoResult.library, { keepScroll: true });
          });
          closeModal();
        }
      } catch (error) {
        toast(error.message, { type: "error" });
      }
      return;
    }

    const move = target.closest("[data-drawer-category]");
    if (move) {
      closeModal();
      openCategoryPicker([move.dataset.drawerCategory]);
      return;
    }

    if (target.closest("[data-drawer-create-child]")) {
      closeModal();
      openCreateCategoryModal(categoryKey);
      return;
    }

    if (target.closest("[data-drawer-filter]")) {
      closeModal();
      filterCategory(categoryKey);
    }
  });
}

function openCategoryPicker(idsOverride = null, { subcategory = false } = {}) {
  const ids = idsOverride || [...state.selected];
  const tracks = state.library?.tracks.filter((track) => ids.includes(track.id)) || [];
  if (!tracks.length) {
    toast("先选择要整理的素材。", { type: "info" });
    return;
  }
  const sfxOnly = tracks.every(isSfxTrack);
  const animationOnly = tracks.every((track) => trackInCategory(track, "animation"));
  const chooseSub = subcategory && sfxOnly;
  const category = chooseSub ? categoryByKey("sfx") : null;
  const source = chooseSub
    ? (category?.subcategories || []).map((item) => ({ ...item, domain: "sub" }))
    : state.library.categories;
  const currentSub = tracks[0]?.category?.subcategory?.key || "auto";
  const inlineSubKey = !chooseSub && sfxOnly ? "sfx" : !chooseSub && animationOnly ? "animation" : "";
  const inlineSubCategory = inlineSubKey ? categoryByKey(inlineSubKey) : null;
  let chosenSub = inlineSubCategory ? currentSub : "auto";
  const chosen = chooseSub
    ? new Set([currentSub])
    : new Set(
        trackCategories(tracks[0])
          .map((item) => item.key)
          .filter((key) => key && key !== "auto"),
      );
  const grouped = [
    ["声音", source.filter((item) => item.domain === "audio")],
    ["形体", source.filter((item) => item.domain === "asset")],
    ["我的分类", source.filter((item) => item.domain === "custom")],
  ];
  const body = `<p class="picker-copy">${
    chooseSub
      ? "只改变音效的细类；原文件与标签不会动。"
      : "可以同时放进多个分类。分类只影响这张表的整理方式，不移动、不重命名、不修改文件。"
  }</p>
    ${grouped
      .filter(([, items]) => items.length)
      .map(
        ([label, items]) => `<div class="picker-section">
          <span class="picker-label">${label}</span>
          <div class="picker-grid">
            ${items
              .map(
                (item) => `<button class="picker-option ${chosen.has(item.key) ? "is-picked" : ""}" type="button" data-pick-category="${escapeHtml(item.key)}" style="--accent:${escapeHtml(item.accent || "#817F73")}">
                  <span class="picker-dot"></span><span>${escapeHtml(item.name)}</span><span class="picker-check">${chosen.has(item.key) ? icon("check", 12) : ""}</span>
                </button>`,
              )
              .join("")}
          </div>
        </div>`,
      )
      .join("")}
    ${
      inlineSubCategory
        ? `<div class="picker-section">
            <span class="picker-label">${inlineSubKey === "sfx" ? "音效细类（可选）" : "动作细类（可选）"}</span>
            <div class="picker-grid">
              ${[
                { key: "auto", name: "自动判断" },
                ...(inlineSubCategory.subcategories || []).map((item) => ({ ...item, count: item.count })),
              ]
                .map(
                  (item) => `<button class="picker-option ${chosenSub === item.key ? "is-picked" : ""}" type="button" data-pick-subcategory="${escapeHtml(item.key)}" style="--accent:${escapeHtml(inlineSubCategory.accent || "#817F73")}">
                    <span class="picker-dot"></span><span>${escapeHtml(item.name)}</span><span class="picker-check">${chosenSub === item.key ? icon("check", 12) : ""}</span>
                  </button>`,
                )
                .join("")}
            </div>
          </div>`
        : ""
    }
    <div class="picker-foot-links">
      <button class="btn btn-quiet picker-auto" type="button" data-pick-category="auto">${icon("refresh", 12)}恢复自动分类</button>
      ${chooseSub ? "" : `<button class="btn btn-quiet picker-auto" type="button" data-picker-create>${icon("plus", 12)}新建一个分类</button>`}
    </div>`;
  const modal = openModal({
    kicker: chooseSub ? "SFX SUBCATEGORY" : "MOVE TO A DRAWER",
    title: chooseSub ? "这段音效像什么？" : "把这些素材放进哪些抽屉？",
    sub: chooseSub ? "细类只影响分类视图，不会重命名或移动文件。" : "可多选；手动分类会覆盖自动判断，但不会改动文件。",
    body,
    narrow: true,
    foot: chooseSub
      ? ""
      : `<button class="btn btn-ghost" type="button" data-close>取消</button>
        <button class="btn btn-primary" type="button" data-picker-apply ${chosen.size ? "" : "disabled"}>应用分类</button>`,
  });
  const layer = modal.layer;
  let working = false;

  layer.addEventListener("click", async (event) => {
    const target = event.target;
    if (!(target instanceof Element)) return;
    if (target.closest("[data-picker-create]")) {
      closeModal();
      openCreateCategoryModal();
      return;
    }
    if (target.closest("[data-picker-apply]") && !working) {
      const button = target.closest("[data-picker-apply]");
      working = true;
      button.disabled = true;
      const before = ids.map((id) => findTrack(id)).filter(Boolean).map((track) => ({
        id: track.id,
        keys: trackCategories(track).map((item) => item.key),
        sub: track.category?.subcategory?.key || "auto",
      }));
      try {
        let result = await api.setMemberships(ids, [...chosen]);
        if (inlineSubCategory && chosenSub !== currentSub) {
          result = await api.setSubcategory(ids, chosenSub);
        }
        applyLibraryResponse(result.library, { clearSelection: !idsOverride });
        closeModal();
        rememberUndo("分类已更新。", async () => {
          let lastResult = null;
          for (const item of before) lastResult = await api.setMemberships([item.id], item.keys);
          if (inlineSubCategory) {
            lastResult = await api.setSubcategory(ids, before[0]?.sub || "auto");
          }
          if (lastResult?.library) applyLibraryResponse(lastResult.library, { clearSelection: !idsOverride });
        });
      } catch (error) {
        toast(error.message, { type: "error" });
        working = false;
        button.disabled = false;
      }
      return;
    }
    const subChoice = target.closest("[data-pick-subcategory]");
    if (subChoice && !working) {
      chosenSub = subChoice.dataset.pickSubcategory || "auto";
      layer.querySelectorAll("[data-pick-subcategory]").forEach((node) => {
        const active = node.dataset.pickSubcategory === chosenSub;
        node.classList.toggle("is-picked", active);
        const check = node.querySelector(".picker-check");
        if (check) check.innerHTML = active ? icon("check", 12) : "";
      });
      return;
    }

    const choice = target.closest("[data-pick-category]");
    if (!choice || working) return;
    const key = choice.dataset.pickCategory;
    if (key === "auto" && !chooseSub) {
      working = true;
      choice.disabled = true;
      try {
        const result = await api.setCategory(ids, "auto");
        applyLibraryResponse(result.library, { clearSelection: !idsOverride });
        closeModal();
        toast("已恢复自动分类。");
      } catch (error) {
        toast(error.message, { type: "error" });
        working = false;
        choice.disabled = false;
      }
      return;
    }
    if (!chooseSub) {
      if (chosen.has(key)) chosen.delete(key);
      else chosen.add(key);
      choice.classList.toggle("is-picked", chosen.has(key));
      const check = choice.querySelector(".picker-check");
      if (check) check.innerHTML = chosen.has(key) ? icon("check", 12) : "";
      const apply = layer.querySelector("[data-picker-apply]");
      if (apply) apply.disabled = !chosen.size;
      return;
    }
    working = true;
    choice.disabled = true;
    try {
      const result = await api.setSubcategory(ids, key);
      applyLibraryResponse(result.library, { clearSelection: !idsOverride });
      closeModal();
      toast("音效细类已更新。");
    } catch (error) {
      toast(error.message, { type: "error" });
      working = false;
      choice.disabled = false;
    }
  });
}

function openCreateCategoryModal(parentKey = "") {
  const swatches = ["#C85A3A", "#B08A45", "#4D7C67", "#4D7394", "#8A6FA8", "#9B6B4E"];
  let accent = swatches[0];
  const parents = (state.library?.categories || []).filter((category) => !category.parent);
  const modal = openModal({
    kicker: parentKey ? "NEW SUB-DRAWER" : "NEW DRAWER",
    title: parentKey ? "在大类下建一个小类" : "造一个自己的抽屉",
    sub: parentKey
      ? "小类只改变声形里的整理方式，不会移动或重命名文件。"
      : "分类只改变声形里的整理方式，不会移动或重命名文件。",
    body: `<form class="create-category-form" id="create-category-form">
      <div class="field">
        <label for="category-parent">归属大类</label>
        <select class="select-input" id="category-parent" name="parent">
          <option value="">不归属大类（创建顶层分类）</option>
          ${parents
            .map(
              (category) =>
                `<option value="${escapeHtml(category.key)}" ${category.key === parentKey ? "selected" : ""}>${escapeHtml(category.name)}</option>`,
            )
            .join("")}
        </select>
        <span class="field-hint">留空创建顶层抽屉；选择大类后，这个分类会显示在它下面。</span>
      </div>
      <div class="field">
        <label for="category-name">分类名称</label>
        <input class="input" id="category-name" name="name" maxlength="24" required autocomplete="off" placeholder="例如：战斗音效、主角模型">
        <span class="field-hint">最多 24 个字，之后可以在选择素材时手动放进来。</span>
      </div>
      <div class="field">
        <span class="field-label">标记色</span>
        <div class="swatch-row">
          ${swatches
            .map(
              (color, index) => `<button class="swatch ${index === 0 ? "is-active" : ""}" type="button" data-swatch="${color}" style="--swatch:${color}" aria-label="颜色 ${color}"></button>`,
            )
            .join("")}
        </div>
      </div>
      <div class="modal-inline-error" data-category-error></div>
    </form>`,
    foot: `<button class="btn btn-ghost" type="button" data-close>取消</button>
      <button class="btn btn-primary" type="submit" form="create-category-form">${icon("plus", 13)}创建分类</button>`,
  });
  const layer = modal.layer;
  layer.querySelectorAll("[data-swatch]").forEach((button) => {
    button.addEventListener("click", () => {
      accent = button.dataset.swatch || swatches[0];
      layer.querySelectorAll("[data-swatch]").forEach((node) => node.classList.toggle("is-active", node === button));
    });
  });
  const form = layer.querySelector("#create-category-form");
  form?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const name = layer.querySelector("#category-name")?.value?.trim() || "";
    const parent = layer.querySelector("#category-parent")?.value || "";
    const errorBox = layer.querySelector("[data-category-error]");
    if (!name) {
      if (errorBox) errorBox.innerHTML = inlineError("给分类起一个名字。");
      return;
    }
    try {
      const result = await api.createCategory(name, accent, parent);
      applyLibraryResponse(result.library);
      closeModal();
      toast(result.message || (parent ? "小类已创建。" : "分类已创建。"));
      if (result.category?.key) openCategoryDrawer(result.category.key);
    } catch (error) {
      if (errorBox) errorBox.innerHTML = inlineError(error.message);
    }
  });
  window.setTimeout(() => layer.querySelector("#category-name")?.focus(), 50);
}

/* -------------------------------------------------------------------------- */
/* BVH motion preview                                                         */
/* -------------------------------------------------------------------------- */

function drawMotionFrame(ctx, canvas, motion, index, accent) {
  const frames = motion.frames || [];
  const frame = frames[index] || frames[0] || [];
  const width = canvas.width;
  const height = canvas.height;
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#102228";
  ctx.fillRect(0, 0, width, height);
  ctx.strokeStyle = "rgba(180, 196, 192, 0.12)";
  ctx.lineWidth = 1;
  for (let x = 0; x <= width; x += 40) {
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, height);
    ctx.stroke();
  }
  for (let y = 0; y <= height; y += 40) {
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(width, y);
    ctx.stroke();
  }
  const pad = Math.min(width, height) * 0.12;
  const scale = Math.min(width - pad * 2, height - pad * 2) / 2;
  const project = (point) => [width / 2 + point[0] * scale, height / 2 + point[1] * scale];
  ctx.strokeStyle = accent;
  ctx.lineWidth = 3;
  ctx.lineCap = "round";
  (motion.edges || []).forEach(([from, to]) => {
    if (!frame[from] || !frame[to]) return;
    const a = project(frame[from]);
    const b = project(frame[to]);
    ctx.beginPath();
    ctx.moveTo(a[0], a[1]);
    ctx.lineTo(b[0], b[1]);
    ctx.stroke();
  });
  frame.forEach((point, jointIndex) => {
    const [x, y] = project(point);
    ctx.beginPath();
    ctx.fillStyle = jointIndex === 0 ? "#F4EEDF" : accent;
    ctx.arc(x, y, jointIndex === 0 ? 5 : 3.5, 0, Math.PI * 2);
    ctx.fill();
  });
  ctx.fillStyle = "rgba(244, 238, 223, 0.55)";
  ctx.font = "11px ui-monospace, monospace";
  ctx.fillText(`FRAME ${String(index + 1).padStart(3, "0")} / ${String(frames.length).padStart(3, "0")}`, 18, height - 18);
}

async function openMotionPreview(id, { returnToDetail = false, onReturn = null } = {}) {
  if (!id || state.busy) return;
  setBusy(true);
  try {
    const result = await api.motion(id);
    const motion = result.motion;
    if (!motion?.frames?.length) throw new Error("这个动作没有可预览的帧。");
    const accent = findTrack(id)?.category?.accent || "#C85A3A";
    const modal = openModal({
      kicker: "MOTION PREVIEW",
      title: result.track?.title || "动作预览",
      sub: `${motion.format || "动作"} · ${motion.joints?.length || 0} 根骨骼 · ${formatCount(motion.frame_count)} 帧 · ${motion.fps || 0} fps${motion.animation_name ? ` · ${motion.animation_name}` : ""}`,
      body: `<div class="motion-stage"><canvas id="motion-canvas" width="920" height="520" aria-label="骨骼动画预览"></canvas></div>
        <div class="motion-controls">
          <button class="btn btn-primary btn-small" type="button" data-motion-toggle>${icon("pause", 13)}暂停</button>
          <input class="motion-range" type="range" min="0" max="${Math.max(0, motion.frames.length - 1)}" value="0" step="1" data-motion-seek aria-label="动作帧">
          <span class="motion-frame" data-motion-frame>01 / ${String(motion.frames.length).padStart(2, "0")}</span>
        </div>
        <p class="motion-note">${icon("info", 12)} 这是从动作骨骼数据实时画出的结构预览，不是最终渲染。原始文件不会被修改。</p>`,
      wide: true,
      foot: returnToDetail || onReturn
        ? `<button class="btn btn-ghost" type="button" data-motion-back>${icon("arrow-left", 13)}${onReturn ? "返回分类" : "返回详情"}</button>`
        : "",
      onClose: () => {
        if (onReturn) onReturn();
        else if (returnToDetail) openInspect(id);
      },
    });
    const layer = modal.layer;
    layer.classList.add("motion-layer");
    layer.querySelector("[data-motion-back]")?.addEventListener("click", () => closeModal());
    const canvas = layer.querySelector("#motion-canvas");
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;
    const seek = layer.querySelector("[data-motion-seek]");
    const toggle = layer.querySelector("[data-motion-toggle]");
    const frameLabel = layer.querySelector("[data-motion-frame]");
    let frame = 0;
    let playing = true;
    let last = 0;
    const span = Math.max(1, 1000 / (Number(motion.fps) || 24));
    const draw = () => {
      drawMotionFrame(ctx, canvas, motion, frame, accent);
      if (seek) seek.value = String(frame);
      if (frameLabel) frameLabel.textContent = `${String(frame + 1).padStart(2, "0")} / ${String(motion.frames.length).padStart(2, "0")}`;
    };
    const loop = (now) => {
      if (!layer.isConnected) return;
      if (playing && now - last >= span) {
        frame = (frame + 1) % motion.frames.length;
        draw();
        last = now;
      }
      requestAnimationFrame(loop);
    };
    draw();
    requestAnimationFrame(loop);
    seek?.addEventListener("input", () => {
      playing = false;
      frame = Number(seek.value) || 0;
      if (toggle) toggle.innerHTML = `${icon("play", 13)}播放`;
      draw();
    });
    toggle?.addEventListener("click", () => {
      playing = !playing;
      toggle.innerHTML = playing ? `${icon("pause", 13)}暂停` : `${icon("play", 13)}播放`;
      last = 0;
    });
  } catch (error) {
    toast(error.message, { type: "error" });
  } finally {
    setBusy(false);
  }
}

function toast(message, { type = "success", duration = 3200, action = null } = {}) {
  const root = $("#toast-root");
  if (!root) return;
  const node = document.createElement("div");
  node.className = `toast ${type === "error" ? "is-error" : ""}`;
  const iconName = type === "error" ? "alert" : type === "info" ? "info" : "check";
  node.innerHTML = `<span class="toast-icon">${icon(iconName, 14)}</span><span class="toast-copy">${escapeHtml(message)}</span>`;
  if (action) {
    const button = document.createElement("button");
    button.className = "toast-action";
    button.type = "button";
    button.textContent = action.label || "撤销";
    button.addEventListener("click", async () => {
      button.disabled = true;
      try {
        await action.run();
      } finally {
        node.classList.add("is-leaving");
        window.setTimeout(() => node.remove(), 240);
      }
    });
    node.appendChild(button);
    duration = Math.max(duration, 6500);
  }
  root.appendChild(node);
  window.setTimeout(() => {
    node.classList.add("is-leaving");
    window.setTimeout(() => node.remove(), 240);
  }, duration);
}

let lastUndo = null;

function rememberUndo(label, run) {
  lastUndo = { label, run };
  toast(label, { action: { label: "撤销", run: performUndo }, duration: 7000 });
}

async function performUndo() {
  if (!lastUndo || state.busy) return;
  const action = lastUndo;
  lastUndo = null;
  setBusy(true);
  try {
    await action.run();
    toast("已撤销上一步。", { type: "info" });
  } catch (error) {
    toast(error.message, { type: "error" });
  } finally {
    setBusy(false);
  }
}

/* -------------------------------------------------------------------------- */
/* Folder modal                                                               */
/* -------------------------------------------------------------------------- */

function recentRows(recents, currentRoot = "") {
  if (!recents.length) return `<p class="welcome-empty-recent">还没有最近打开的文件夹。</p>`;
  return recents
    .map(
      (item) => `<button class="recent-row" type="button" data-folder-recent="${escapeHtml(item.path)}">
        <span class="recent-icon">${icon(item.exists ? "folder-open" : "alert", 14)}</span>
        <span class="recent-copy">
          <span class="recent-name">${escapeHtml(item.name || parentFolder(item.path) || item.path)}</span>
          <span class="recent-path">${escapeHtml(item.path)}</span>
        </span>
        ${norm(item.path) === norm(currentRoot) ? '<span class="recent-flag">当前</span>' : !item.exists ? '<span class="recent-flag is-missing">缺失</span>' : ""}
      </button>`,
    )
    .join("");
}

function openFolderModal() {
  if (!state.library) return;
  const recents = state.payload?.recents || [];
  openModal({
    kicker: "ADD FOLDER",
    title: "再加一个文件夹",
    sub: "当前素材库不会被替换。新文件夹会加进同一张表，标签、收藏与分类仍按文件夹分开保存。",
    body: `<form id="folder-form">
      <div class="field">
        <label for="folder-path">文件夹路径</label>
        <div class="input-row">
          <input class="input" id="folder-path" type="text" autocomplete="off" spellcheck="false" value="" placeholder="D:\\Music 或 D:\\Assets">
          <button class="btn btn-ghost" type="button" data-folder-pick>${icon("folder", 14)}选择</button>
        </div>
        <span class="field-hint">支持常见音频格式，以及 GLB、GLTF、FBX、OBJ、BVH、BLEND、贴图与工程文件。</span>
      </div>
      <div class="welcome-error" id="folder-error"></div>
      <div class="folder-recents">
        <p class="folder-recents-title">RECENT FOLDERS</p>
        ${recentRows(recents, state.library.root)}
      </div>
    </form>`,
    foot: `<button class="btn btn-ghost" type="button" data-close>取消</button>
      <button class="btn btn-primary" type="submit" form="folder-form" id="folder-submit">${icon("plus", 14)}添加</button>`,
    onMount(layer) {
      const form = layer.querySelector("#folder-form");
      const input = layer.querySelector("#folder-path");
      form?.addEventListener("submit", (event) => {
        event.preventDefault();
        openFolderFromModal(layer, input?.value || "");
      });

      layer.querySelector("[data-folder-pick]")?.addEventListener("click", async (event) => {
        const button = event.currentTarget;
        button.disabled = true;
        button.innerHTML = `<span class="spinner"></span> 选择中…`;
        try {
          const result = await api.pickFolder(input?.value || "");
          if (result.cancelled) return;
          if (result.error) throw new Error(result.error);
          if (result.path) {
            if (input) input.value = result.path;
            await openFolderFromModal(layer, result.path);
          }
        } catch (error) {
          const box = layer.querySelector("#folder-error");
          if (box) box.innerHTML = inlineError(error.message);
        } finally {
          if (button.isConnected) {
            button.disabled = false;
            button.innerHTML = `${icon("folder", 14)}选择`;
          }
        }
      });

      layer.querySelectorAll("[data-folder-recent]").forEach((button) => {
        button.addEventListener("click", () => {
          const path = button.dataset.folderRecent;
          if (input) input.value = path;
          openFolderFromModal(layer, path);
        });
      });
    },
  });
}

async function openFolderFromModal(layer, path) {
  const value = String(path || "").trim();
  const errorBox = layer.querySelector("#folder-error");
  if (!value) {
    if (errorBox) errorBox.innerHTML = inlineError("先输入一个文件夹路径。");
    return;
  }
  const submit = layer.querySelector("#folder-submit");
  if (submit) {
    submit.disabled = true;
    submit.innerHTML = `<span class="spinner"></span> 正在读取…`;
  }
  if (errorBox) errorBox.innerHTML = "";

  try {
    const payload = await api.addLibrary(value);
    closeModal();
    adoptWorkspace(payload, `已添加「${payload.library?.name || "素材文件夹"}」`);
  } catch (error) {
    if (errorBox?.isConnected) errorBox.innerHTML = inlineError(error.message);
  } finally {
    if (submit?.isConnected) {
      submit.disabled = false;
      submit.innerHTML = `${icon("plus", 14)}添加`;
    }
  }
}

function adoptWorkspace(payload, message = "") {
  if (!payload?.library) return;
  state.payload = payload;
  if (!state.library) {
    enterLibrary(payload, { announce: false });
  } else {
    state.library = payload.library;
    applyLibraryResponse(payload.library, { keepScroll: true });
  }
  if (message) toast(message, { type: "success" });
}

async function removeSource(sourceId) {
  if (!sourceId || state.busy) return;
  setBusy(true);
  try {
    const payload = await api.removeLibrary(sourceId);
    adoptWorkspace(payload, "已从素材库移除这个文件夹");
  } catch (error) {
    toast(error.message, { type: "error" });
  } finally {
    setBusy(false);
  }
}

async function rescanSource(sourceId) {
  if (!sourceId || state.busy) return;
  setBusy(true);
  try {
    const result = await api.rescan(sourceId);
    applyLibraryResponse(result.library, { keepScroll: true });
    toast(result.message || "已重新扫描这个文件夹。");
  } catch (error) {
    toast(error.message, { type: "error" });
  } finally {
    setBusy(false);
  }
}

/* -------------------------------------------------------------------------- */
/* Tag editor                                                                 */
/* -------------------------------------------------------------------------- */

function openTagEditor(idsOverride = null) {
  const tracks = Array.isArray(idsOverride)
    ? state.library.tracks.filter((track) => idsOverride.includes(track.id))
    : selectedTracks();
  if (!tracks.length) {
    toast("先在列表里勾选素材", { type: "info" });
    return;
  }
  const ids = tracks.map((track) => track.id);
  const existing = new Set();
  tracks.forEach((track) => (track.tags || []).forEach((tag) => existing.add(tag)));
  const existingTags = [...existing].sort(naturalCompare);
  const suggestions = (state.library.tags || [])
    .filter((item) => !existing.has(item.name))
    .slice(0, 18);

  const removeBlock = existingTags.length
    ? `<div class="tag-remove-block">
        <h4 class="tag-remove-title">从选中素材移除</h4>
        <p class="tag-remove-copy">只会移除标签，不会动硬盘上的文件。</p>
        <div class="tag-remove-list">
          ${existingTags
            .map(
              (tag) => `<button class="tag-remove-btn" type="button" data-remove-tag="${escapeHtml(tag)}">${escapeHtml(tag)} ×</button>`,
            )
            .join("")}
        </div>
      </div>`
    : "";

  const modal = openModal({
    kicker: "ADD TAGS",
    title: "给素材贴一个标签",
    sub: `将给选中的 ${tracks.length} 项素材添加标签。可以一次输入多个。`,
    narrow: true,
    body: `<form id="tag-form">
      <div class="field">
        <label for="tag-input">标签</label>
        <input class="input" id="tag-input" type="text" autocomplete="off" placeholder="例如：夜晚，通勤，待整理" maxlength="160">
        <span class="field-hint">用逗号、顿号或换行分隔；大小写不敏感，单项最多 30 个标签。</span>
      </div>
      ${
        suggestions.length
          ? `<div class="tag-editor-suggestions">
              ${suggestions
                .map(
                  (item) => `<button class="tag-suggestion" type="button" data-suggest="${escapeHtml(item.name)}">${escapeHtml(item.name)}</button>`,
                )
                .join("")}
            </div>`
          : ""
      }
      <div class="welcome-error" id="tag-error"></div>
      ${removeBlock}
    </form>`,
    foot: `<button class="btn btn-ghost" type="button" data-close>取消</button>
      <button class="btn btn-primary" type="submit" form="tag-form" id="tag-submit">${icon("plus", 14)}加标签</button>`,
    onMount(layer) {
      const form = layer.querySelector("#tag-form");
      const input = layer.querySelector("#tag-input");
      const errorBox = layer.querySelector("#tag-error");
      const submit = layer.querySelector("#tag-submit");
      input?.focus();

      const appendSuggestion = (tag) => {
        if (!input) return;
        const current = parseTagInput(input.value);
        if (!current.includes(tag)) current.push(tag);
        input.value = current.join("，");
        input.focus();
      };

      layer.querySelectorAll("[data-suggest]").forEach((button) => {
        button.addEventListener("click", () => appendSuggestion(button.dataset.suggest));
      });

      layer.querySelectorAll("[data-remove-tag]").forEach((button) => {
        button.addEventListener("click", async () => {
          const tag = button.dataset.removeTag;
          button.disabled = true;
          try {
            const result = await api.removeTag(ids, tag);
            if (!result.library) return;
            closeModal();
            applyLibraryResponse(result.library, { clearSelection: true });
            toast(`已移除标签「${tag}」`);
          } catch (error) {
            button.disabled = false;
            if (errorBox) errorBox.innerHTML = inlineError(error.message);
          }
        });
      });

      form?.addEventListener("submit", async (event) => {
        event.preventDefault();
        const tags = parseTagInput(input?.value || "");
        if (!tags.length) {
          if (errorBox) errorBox.innerHTML = inlineError("至少输入一个标签。");
          input?.focus();
          return;
        }
        if (submit) {
          submit.disabled = true;
          submit.innerHTML = `<span class="spinner"></span> 正在添加…`;
        }
        try {
          const beforeTags = tracks.map((track) => ({ id: track.id, tags: [...(track.tags || [])] }));
          const result = await api.addTags(ids, tags);
          if (!result.library) return;
          closeModal();
          applyLibraryResponse(result.library, { clearSelection: true });
          rememberUndo(`已为 ${tracks.length} 项素材添加 ${tags.length} 个标签`, async () => {
            let lastResult = null;
            for (const item of beforeTags) lastResult = await api.setTags(item.id, item.tags);
            if (lastResult?.library) applyLibraryResponse(lastResult.library, { clearSelection: true });
          });
        } catch (error) {
          if (errorBox) errorBox.innerHTML = inlineError(error.message);
          if (submit) {
            submit.disabled = false;
            submit.innerHTML = `${icon("plus", 14)}加标签`;
          }
        }
      });
    },
  });

  return modal;
}

/* -------------------------------------------------------------------------- */
/* Batch rename                                                               */
/* -------------------------------------------------------------------------- */

function openRenameModal(idsOverride = null) {
  const tracks = Array.isArray(idsOverride)
    ? state.library.tracks.filter((track) => idsOverride.includes(track.id))
    : selectedTracks();
  if (!tracks.length) {
    toast("先在列表里勾选素材", { type: "info" });
    return;
  }
  const ids = tracks.map((track) => track.id);
  const first = tracks[0];
  const filename = first.filename || "";
  const suffixIndex = filename.lastIndexOf(".");
  const suffix = suffixIndex > 0 ? filename.slice(suffixIndex) : "";
  const defaultDigits = clamp(String(tracks.length).length + 1, 2, 6);

  const modal = openModal({
    kicker: "BATCH RENAME",
    title: "给这一批素材编号",
    sub: `会重命名选中的 ${tracks.length} 项素材。只改文件名，不写入或转码素材内容；后缀和所在文件夹保持不变。`,
    wide: true,
    body: `<form id="rename-form">
      <div class="form-grid">
        <div class="field">
          <label for="rename-name">统一名称</label>
          <input class="input" id="rename-name" type="text" autocomplete="off" placeholder="例如：岛上素材" maxlength="80">
        </div>
        <div class="field">
          <label for="rename-start">起始编号</label>
          <input class="input" id="rename-start" type="number" min="0" max="999999" value="1">
        </div>
        <div class="field">
          <label for="rename-digits">编号位数</label>
          <select class="select-input" id="rename-digits">
            ${[2, 3, 4, 5, 6].map((value) => `<option value="${value}" ${value === defaultDigits ? "selected" : ""}>${value} 位</option>`).join("")}
          </select>
        </div>
        <div class="field">
          <label for="rename-separator">分隔符</label>
          <select class="select-input" id="rename-separator">
            <option value=" ">空格</option>
            <option value="-" selected>短横线 -</option>
            <option value="_">下划线 _</option>
            <option value="">无</option>
          </select>
        </div>
        <div class="field is-full">
          <span class="field-hint">生成「统一名称-编号.后缀」，例如 ${escapeHtml(first.title || "岛上素材")}-01${escapeHtml(suffix)}。只改文件名，不写入素材内容，不移动文件夹，不改后缀。</span>
        </div>
      </div>
      <div class="example-line">${icon("edit", 13)}<span>新名字示例</span><code id="rename-example">岛上素材-01${escapeHtml(suffix)}</code></div>
      <div class="preview-shell">
        <div class="preview-head">
          <span>${icon("layers", 12)} 重命名预览</span>
          <span class="preview-status" id="rename-preview-status">输入名称后检查</span>
        </div>
        <div class="preview-list" id="rename-preview-list">
          <div class="preview-empty">输入统一名称后，这里会出现每个文件的新名字。</div>
        </div>
      </div>
      <div class="welcome-error" id="rename-error"></div>
    </form>`,
    foot: `<span class="modal-foot-note">${tracks.length} 项素材 · 先预览再应用</span>
      <button class="btn btn-ghost" type="button" data-close>取消</button>
      <button class="btn btn-primary" type="submit" form="rename-form" id="rename-submit" disabled>应用重命名</button>`,
    onMount(layer) {
      const form = layer.querySelector("#rename-form");
      const nameInput = layer.querySelector("#rename-name");
      const startInput = layer.querySelector("#rename-start");
      const digitsInput = layer.querySelector("#rename-digits");
      const separatorInput = layer.querySelector("#rename-separator");
      const example = layer.querySelector("#rename-example");
      const status = layer.querySelector("#rename-preview-status");
      const previewList = layer.querySelector("#rename-preview-list");
      const errorBox = layer.querySelector("#rename-error");
      const submit = layer.querySelector("#rename-submit");

      let plan = null;
      let sequence = 0;
      let applying = false;

      const options = () => ({
        name: nameInput?.value.trim() || "",
        start: Number(startInput?.value),
        digits: Number(digitsInput?.value),
        separator: separatorInput?.value ?? "-",
      });

      const updateExample = () => {
        if (!example) return;
        const current = options();
        const number = Number.isFinite(current.start) ? current.start : 1;
        const base = current.name || "新名字";
        const digits = Number.isFinite(current.digits) ? current.digits : 2;
        example.textContent = `${base}${current.separator}${String(number).padStart(digits, "0")}${suffix}`;
      };

      const setStatus = (text, bad = false) => {
        if (!status) return;
        status.textContent = text;
        status.classList.toggle("is-bad", bad);
      };

      const clearPreview = () => {
        plan = null;
        if (previewList) previewList.innerHTML = `<div class="preview-empty">输入统一名称后，这里会出现每个文件的新名字。</div>`;
        if (errorBox) errorBox.innerHTML = "";
        if (submit) submit.disabled = true;
        setStatus("输入名称后检查");
      };

      const renderPreview = (nextPlan) => {
        plan = nextPlan;
        const items = plan?.items || [];
        const badCount = items.filter((item) => !item.ok).length;
        if (plan?.ok) {
          setStatus(`可以重命名 ${plan.total || items.length} 个文件`);
        } else {
          setStatus(`${plan?.conflicts || badCount || 1} 处冲突，先处理`, true);
        }

        if (previewList) {
          if (!items.length) {
            previewList.innerHTML = `<div class="preview-empty">没有可重命名的文件。</div>`;
          } else {
            const visible = items.slice(0, 100);
            previewList.innerHTML =
              visible
                .map(
                  (item) => `<div class="preview-row ${item.ok ? "" : "is-conflict"}">
                    <span class="preview-old" title="${escapeHtml(item.old_name)}">${escapeHtml(item.old_name)}</span>
                    <span class="preview-arrow">→</span>
                    <span class="preview-new" title="${escapeHtml(item.new_name || "")}">${escapeHtml(item.new_name || "—")}</span>
                    <span class="preview-flag ${item.ok ? "ok" : "bad"}" title="${escapeHtml(item.error || item.warning || "")}">${item.ok ? (item.warning ? "注意" : "就绪") : "冲突"}</span>
                  </div>`,
                )
                .join("") +
              (items.length > visible.length
                ? `<div class="preview-more">还有 ${items.length - visible.length} 个文件未展开</div>`
                : "");
          }
        }

        if (errorBox) {
          const firstBad = items.find((item) => !item.ok);
          const firstWarning = items.find((item) => item.warning);
          if (firstBad) {
            errorBox.innerHTML = inlineError(firstBad.error || "生成的文件名有冲突。");
          } else if (firstWarning) {
            errorBox.innerHTML = `<div class="example-line">${icon("info", 13)}<span>${escapeHtml(firstWarning.warning)}</span></div>`;
          } else {
            errorBox.innerHTML = "";
          }
        }
        if (submit) submit.disabled = !plan?.ok;
      };

      const doPreview = async () => {
        const current = options();
        sequence += 1;
        const thisSequence = sequence;
        if (!current.name) {
          clearPreview();
          return null;
        }
        updateExample();
        if (errorBox) errorBox.innerHTML = "";
        setStatus("正在检查…");
        if (submit) submit.disabled = true;

        try {
          const result = await api.previewRename(
            ids,
            current.name,
            current.start,
            current.digits,
            current.separator,
          );
          if (thisSequence !== sequence || !layer.isConnected) return null;
          renderPreview(result.plan);
          return result.plan;
        } catch (error) {
          if (thisSequence !== sequence || !layer.isConnected) return null;
          plan = null;
          if (previewList) previewList.innerHTML = `<div class="preview-empty">预览失败，请再试一次。</div>`;
          setStatus("预览失败", true);
          if (errorBox) errorBox.innerHTML = inlineError(error.message);
          if (submit) submit.disabled = true;
          return null;
        }
      };

      const debouncedPreview = debounce(doPreview, 260);
      const onOptionChange = () => {
        updateExample();
        if (errorBox) errorBox.innerHTML = "";
        debouncedPreview();
      };

      nameInput?.addEventListener("input", onOptionChange);
      startInput?.addEventListener("input", onOptionChange);
      digitsInput?.addEventListener("change", onOptionChange);
      separatorInput?.addEventListener("change", onOptionChange);
      updateExample();
      nameInput?.focus();

      form?.addEventListener("submit", async (event) => {
        event.preventDefault();
        if (applying) return;
        const current = options();

        if (!current.name) {
          if (errorBox) errorBox.innerHTML = inlineError("先输入一个统一名称。");
          nameInput?.focus();
          return;
        }
        if (!Number.isFinite(current.start) || current.start < 0 || current.start > 999999) {
          if (errorBox) errorBox.innerHTML = inlineError("起始编号需要在 0 到 999999 之间。");
          startInput?.focus();
          return;
        }

        const stale =
          !plan ||
          plan.base !== current.name ||
          Number(plan.start) !== current.start ||
          Number(plan.digits) !== current.digits ||
          plan.separator !== current.separator;
        if (stale) {
          const fresh = await doPreview();
          if (!fresh?.ok) return;
        }
        if (!plan?.ok) return;

        applying = true;
        if (submit) {
          submit.disabled = true;
          submit.innerHTML = `<span class="spinner"></span> 正在重命名…`;
        }

        try {
          const result = await api.applyRename(
            ids,
            current.name,
            current.start,
            current.digits,
            current.separator,
          );
          if (!result?.ok) {
            if (result?.plan) renderPreview(result.plan);
            if (errorBox) errorBox.innerHTML = inlineError("重命名没有完成，请检查预览里的冲突。");
            return;
          }
          handleRenameSuccess(result);
        } catch (error) {
          if (error.data?.plan) renderPreview(error.data.plan);
          if (errorBox?.isConnected) errorBox.innerHTML = inlineError(error.message);
          toast(error.message, { type: "error" });
        } finally {
          applying = false;
          if (submit?.isConnected) {
            submit.disabled = !plan?.ok;
            submit.textContent = "应用重命名";
          }
        }
      });
    },
  });

  return modal;
}

function handleRenameSuccess(result) {
  const library = result.library;
  if (!library) {
    toast("重命名已经执行，但刷新资料库失败；请重新扫描文件夹。", { type: "error" });
    return;
  }
  const mapping = result.plan?.mapping || [];
  const currentId = player?.current?.id;
  const mapped = mapping.find((item) => item.id === currentId);
  const nextTrack = mapped?.new_id
    ? library.tracks.find((track) => track.id === mapped.new_id) || null
    : null;

  closeModal();
  state.library = library;
  if (state.payload) state.payload.library = library;
  state.selected.clear();

  if (mapped) {
    if (nextTrack) player.replaceTrack(nextTrack);
    else player.stop();
  }

  render({ keepScroll: true });
  if (nextTrack) player.setQueue(audioTracks());
  toast(`已重命名 ${result.plan?.renamed ?? mapping.length} 个文件`);
}

/* -------------------------------------------------------------------------- */
/* Asset inspector                                                            */
/* -------------------------------------------------------------------------- */

const STAT_LABELS = {
  meshes: "网格",
  materials: "材质",
  animations: "动作",
  skins: "蒙皮",
  textures: "贴图",
  images: "图片",
  nodes: "节点",
  bones: "骨骼",
  frames: "帧",
  vertices: "顶点",
  faces: "面",
  objects: "对象",
  groups: "组",
  duration: "时长",
  width: "宽",
  height: "高",
  version: "版本",
};

function detailStats(asset) {
  const stats = asset.stats || {};
  const rows = [["格式", asset.format || "ASSET"]];
  Object.entries(STAT_LABELS).forEach(([key, label]) => {
    const value = stats[key];
    if (value === undefined || value === null || value === "" || value === 0) return;
    if (key === "duration") {
      rows.push([label, `${Number(value).toFixed(2)} 秒`]);
      return;
    }
    if (key === "width" || key === "height") {
      rows.push([label, `${value}px`]);
      return;
    }
    rows.push([label, String(value)]);
  });
  rows.push(["文件大小", formatSize(asset.size)]);
  rows.push(["更新", formatDate(asset.modified)]);
  return rows.slice(0, 9);
}

function detailMarkup(asset) {
  const stats = detailStats(asset)
    .map(
      ([label, value]) => `<div class="detail-stat">
        <div class="detail-stat-label">${escapeHtml(label)}</div>
        <div class="detail-stat-value" title="${escapeHtml(value)}">${escapeHtml(value)}</div>
      </div>`,
    )
    .join("");
  const tags = (asset.tags || []).map((tag) => tagChip(tag, { action: null })).join("");
  return `<div class="detail-layout">
    <div class="detail-plate">${plateMarkup(asset, { size: "lg", detail: true })}</div>
    <div class="detail-body">
      <div class="detail-kicker">${categoryIcon(asset.category?.key, 13)}<span>${escapeHtml(asset.category?.name || "其他")} / ${escapeHtml(asset.format || "ASSET")}</span></div>
      <h3 class="detail-title">${escapeHtml(asset.title || asset.filename)}</h3>
      <p class="detail-path">${escapeHtml(asset.rel_path || "")}</p>
      <p class="detail-summary">${escapeHtml(asset.summary || "已读取这个资产的结构信息。")}</p>
      <div class="detail-stats">${stats}</div>
      <div class="detail-section">
        <div class="detail-section-label">标签 / TAGS</div>
        <div class="detail-tags">${tags || '<span class="tag-empty">未标记</span>'}</div>
      </div>
      ${asset.note ? `<div class="detail-note">${icon("info", 12)} ${escapeHtml(asset.note)}</div>` : ""}
      <div class="detail-actions">
        <button class="btn btn-ghost" type="button" data-inspect-action="category">${icon("layers", 13)}更改分类</button>
        ${
          asset.category?.key === "sfx"
            ? `<button class="btn btn-ghost" type="button" data-inspect-action="subcategory">${icon("wave", 13)}音效细类</button>`
            : ""
        }
        ${
          isMotionPreviewable(asset)
            ? `<button class="btn btn-ghost" type="button" data-inspect-action="motion">${icon("play", 13)}骨骼预览</button>`
            : ""
        }
        ${
          isSkinPreviewable(asset)
            ? `<button class="btn btn-ghost" type="button" data-inspect-action="skin">${icon("cube", 13)}蒙皮预览</button>`
            : ""
        }
        <button class="btn btn-ghost" type="button" data-inspect-action="reveal">${icon("folder-open", 13)}在文件夹中显示</button>
        <button class="btn btn-ghost" type="button" data-inspect-action="copy">${icon("copy", 13)}复制路径</button>
        <button class="btn btn-ghost" type="button" data-inspect-action="tags">${icon("tag", 13)}编辑标签</button>
      </div>
    </div>
  </div>
  <div class="detail-foot">${icon("file", 11)}<span title="${escapeHtml(asset.absolute_path || "")}">${escapeHtml(asset.absolute_path || "")}</span></div>`;
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const area = document.createElement("textarea");
    area.value = text;
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    const copied = document.execCommand("copy");
    area.remove();
    return copied;
  }
}

async function openWaveform() {
  const track = player?.current;
  if (!track) {
    toast("先选一段声音，再看波形。", { type: "info" });
    return;
  }
  let context = null;
  const modal = openModal({
    kicker: "WAVEFORM",
    title: "声音的轮廓",
    sub: `${track.title || track.filename} · 点击波形可以跳转播放位置`,
    wide: true,
    body: `<div class="waveform-shell">
      <canvas id="waveform-canvas" width="1080" height="260" aria-label="音频波形"></canvas>
      <div class="waveform-meta"><span data-wave-time>正在读取波形…</span><span>${escapeHtml(track.filename || "")}</span></div>
    </div>`,
    foot: `<button class="btn btn-ghost" type="button" data-close>关闭</button>`,
    onClose: () => {
      if (context) context.close().catch(() => {});
    },
  });
  const canvas = modal.layer.querySelector("#waveform-canvas");
  const timeLabel = modal.layer.querySelector("[data-wave-time]");
  const ctx = canvas?.getContext("2d");
  if (!canvas || !ctx) return;

  const drawEmpty = (message) => {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = "#102228";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = "rgba(244,238,223,0.55)";
    ctx.font = "14px sans-serif";
    ctx.fillText(message, 24, 40);
  };
  drawEmpty("正在读取波形…");

  try {
    const response = await fetch(track.stream_url, { cache: "no-store" });
    if (!response.ok) throw new Error("无法读取音频");
    const arrayBuffer = await response.arrayBuffer();
    context = new (window.AudioContext || window.webkitAudioContext)();
    const buffer = await context.decodeAudioData(arrayBuffer.slice(0));
    const channel = buffer.getChannelData(0);
    const bars = 360;
    const block = Math.max(1, Math.floor(channel.length / bars));
    const peaks = [];
    for (let index = 0; index < bars; index += 1) {
      let peak = 0;
      const start = index * block;
      const end = Math.min(channel.length, start + block);
      for (let cursor = start; cursor < end; cursor += 1) {
        const value = Math.abs(channel[cursor]);
        if (value > peak) peak = value;
      }
      peaks.push(peak);
    }
    const max = Math.max(...peaks, 0.001);
    const draw = () => {
      const width = canvas.width;
      const height = canvas.height;
      ctx.clearRect(0, 0, width, height);
      ctx.fillStyle = "#102228";
      ctx.fillRect(0, 0, width, height);
      const barWidth = width / peaks.length;
      peaks.forEach((peak, index) => {
        const value = Math.max(0.02, peak / max);
        const barHeight = value * (height - 28);
        const x = index * barWidth;
        ctx.fillStyle = "rgba(176, 138, 69, 0.72)";
        ctx.fillRect(x, (height - barHeight) / 2, Math.max(1, barWidth - 1.2), barHeight);
      });
      const duration = player.audio.duration || buffer.duration || 1;
      const progress = player.audio.currentTime / duration;
      ctx.fillStyle = "rgba(198, 93, 59, 0.95)";
      ctx.fillRect(progress * width - 1, 0, 2, height);
    };
    draw();
    timeLabel.textContent = `波形已读取 · ${formatDuration(buffer.duration)}`;
    canvas.addEventListener("click", (event) => {
      const rect = canvas.getBoundingClientRect();
      const ratio = clamp((event.clientX - rect.left) / rect.width, 0, 1);
      player.audio.currentTime = ratio * (player.audio.duration || buffer.duration);
      draw();
    });
  } catch (error) {
    drawEmpty("这个音频暂时无法解析出波形。");
    timeLabel.textContent = error.message || "波形读取失败";
  }
}

async function openInspect(id) {
  if (!id || state.busy) return;
  setBusy(true);
  try {
    const result = await api.inspect(id);
    const asset = result.asset;
    if (!asset) throw new Error("没有找到这件资产。");
    openModal({
      kicker: "ASSET INSPECTOR",
      title: "资产详情",
      sub: `${asset.category?.name || "其他"} · ${asset.format || "ASSET"}`,
      body: detailMarkup(asset),
      wide: true,
      onMount: (layer) => {
        layer.querySelector('[data-inspect-action="copy"]')?.addEventListener("click", async () => {
          const copied = await copyText(asset.absolute_path || "");
          toast(copied ? "路径已复制" : "复制失败，请手动选择路径", { type: copied ? "success" : "error" });
        });
        layer.querySelector('[data-inspect-action="reveal"]')?.addEventListener("click", async () => {
          try {
            await api.reveal(asset.id);
          } catch (error) {
            toast(error.message, { type: "error" });
          }
        });
        layer.querySelector('[data-inspect-action="tags"]')?.addEventListener("click", () => {
          closeModal();
          openTagEditor([asset.id]);
        });
        layer.querySelector('[data-inspect-action="category"]')?.addEventListener("click", () => {
          closeModal();
          openCategoryPicker([asset.id]);
        });
        layer.querySelector('[data-inspect-action="subcategory"]')?.addEventListener("click", () => {
          closeModal();
          openCategoryPicker([asset.id], { subcategory: true });
        });
        layer.querySelector('[data-inspect-action="skin"]')?.addEventListener("click", () => {
          openSkinPreview(asset.id);
        });
        layer.querySelector('[data-inspect-action="motion"]')?.addEventListener("click", () => {
          openMotionPreview(asset.id, { returnToDetail: true });
        });
      },
    });
  } catch (error) {
    toast(error.message, { type: "error" });
  } finally {
    setBusy(false);
  }
}

/* -------------------------------------------------------------------------- */
/* Events                                                                     */
/* -------------------------------------------------------------------------- */

function bindEvents() {
  $$("[data-view]").forEach((button) => {
    button.addEventListener("click", () => setView(button.dataset.view));
  });

  $("#btn-menu")?.addEventListener("click", () => {
    if ($("#sidebar")?.classList.contains("is-open")) closeSidebar();
    else openSidebar();
  });
  $("#nav-scrim")?.addEventListener("click", closeSidebar);
  $("#btn-open")?.addEventListener("click", openFolderModal);
  $("#sidebar-open")?.addEventListener("click", openFolderModal);
  $("#btn-rescan")?.addEventListener("click", rescanLibrary);

  const search = $("#search-input");
  if (search) {
    searchDebounce = debounce(() => render({ keepScroll: true }), 160);
    search.addEventListener("input", () => {
      state.search = search.value;
      state.selected.clear();
      updateSelectionUI();
      searchDebounce();
    });
  }

  $("#view-root")?.addEventListener("click", handleViewClick);
  $("#view-root")?.addEventListener("change", handleViewChange);
  $("#selection-bar")?.addEventListener("click", handleSelectionAction);
  $("#player-wave-open")?.addEventListener("click", openWaveform);

  const welcome = $("#welcome-root");
  welcome?.addEventListener("submit", (event) => {
    if (event.target.id !== "welcome-form") return;
    event.preventDefault();
    welcomeOpen();
  });
  welcome?.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof Element)) return;
    const recent = target.closest("[data-welcome-recent]");
    if (recent) {
      const path = recent.dataset.welcomeRecent;
      state.welcomePath = path;
      const input = $("#welcome-path");
      if (input) input.value = path;
      welcomeOpen(path);
      return;
    }
    if (target.closest("#welcome-pick")) {
      event.preventDefault();
      welcomePick();
    }
  });

  const audio = $("#audio");
  audio?.addEventListener("play", () => {
    updateRowsPlaying();
    updateDocumentTitle();
  });
  audio?.addEventListener("pause", () => {
    updateRowsPlaying();
    updateDocumentTitle();
  });
  audio?.addEventListener("ended", () => {
    window.setTimeout(() => {
      updateRowsPlaying();
      updateDocumentTitle();
    }, 0);
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      if ($("#modal-root .modal-layer")) {
        closeModal();
        return;
      }
      if ($("#sidebar")?.classList.contains("is-open")) {
        closeSidebar();
        return;
      }
      if (document.activeElement === search) {
        if (search.value) {
          search.value = "";
          state.search = "";
          state.selected.clear();
          render({ keepScroll: true });
        } else {
          search.blur();
        }
      }
      return;
    }

    const inModal = Boolean($("#modal-root .modal-layer"));
    const inField = isTypingTarget(event.target) || event.target.closest?.("button, a");
    if (event.key === "/" && !inField && !inModal) {
      event.preventDefault();
      search?.focus();
      return;
    }
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z" && !inField && !inModal) {
      event.preventDefault();
      performUndo();
      return;
    }
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "a" && !inField && !inModal) {
      event.preventDefault();
      state.selected = new Set(state.visibleTracks.map((track) => track.id));
      refreshSelectionDom();
      return;
    }
    if (event.code === "Space" && !inField && !inModal && player?.current) {
      event.preventDefault();
      player.toggle();
    }
  });

  document.addEventListener("dragstart", (event) => {
    const row = event.target.closest?.(".track-row[data-track-id]");
    if (!row) return;
    event.dataTransfer?.setData("text/plain", row.dataset.trackId);
    if (event.dataTransfer) event.dataTransfer.effectAllowed = "copy";
    row.classList.add("is-dragging");
  });

  document.addEventListener("dragend", (event) => {
    event.target.closest?.(".track-row")?.classList.remove("is-dragging");
    $$(".category-card.is-drop-target").forEach((card) => card.classList.remove("is-drop-target"));
  });

  document.addEventListener("dragover", (event) => {
    const card = event.target.closest?.(".category-card[data-category]");
    if (!card) return;
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = "copy";
    card.classList.add("is-drop-target");
  });

  document.addEventListener("dragleave", (event) => {
    const card = event.target.closest?.(".category-card[data-category]");
    if (!card || card.contains(event.relatedTarget)) return;
    card.classList.remove("is-drop-target");
  });

  document.addEventListener("drop", async (event) => {
    const card = event.target.closest?.(".category-card[data-category]");
    if (!card) return;
    event.preventDefault();
    card.classList.remove("is-drop-target");
    const id = event.dataTransfer?.getData("text/plain") || "";
    const track = findTrack(id);
    const categoryKey = card.dataset.category;
    if (!track || !categoryKey) return;
    const current = trackCategories(track).map((category) => category.key);
    if (current.includes(categoryKey)) {
      toast("这件素材已经在这个抽屉里了。");
      return;
    }
    const beforeKeys = [...current];
    try {
      const result = await api.setMemberships([id], [...current, categoryKey]);
      applyLibraryResponse(result.library, { keepScroll: true });
      rememberUndo(`已放进「${categoryByKey(categoryKey)?.name || "新分类"}」。`, async () => {
        const undoResult = await api.setMemberships([id], beforeKeys);
        if (undoResult.library) applyLibraryResponse(undoResult.library, { keepScroll: true });
      });
    } catch (error) {
      toast(error.message, { type: "error" });
    }
  });

  const imageError = (event) => {
    const image = event.target;
    if (!(image instanceof HTMLImageElement)) return;
    image.closest(".cover, .hero-vinyl-cover, .asset-plate")?.classList.add("is-broken");
  };
  document.addEventListener("error", imageError, true);

  window.addEventListener("resize", () => {
    if (window.innerWidth > 940) closeSidebar();
  });
}

init();
