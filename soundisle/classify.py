"""Transparent, explainable automatic classification.

Sound Isle uses a deliberately conservative content-type taxonomy instead of
guessing musical genres.  Every decision carries a human-readable reason so
the classification page never feels like a black box.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Dict, List, Optional, Tuple


@dataclass(frozen=True)
class Category:
    key: str
    name: str
    description: str
    hint: str
    accent: str
    icon: str
    domain: str = "audio"


CATEGORY_LIST: Tuple[Category, ...] = (
    Category(
        key="song",
        name="歌曲",
        description="有明确曲名与人声表达的完整作品",
        hint="歌手 - 曲名 / 歌曲时长 / 流派标签",
        accent="#C65D3B",
        icon="music",
    ),
    Category(
        key="instrumental",
        name="纯音乐",
        description="器乐、伴奏与无人声作品",
        hint="伴奏 / 纯音乐 / 钢琴 / 练习曲",
        accent="#B08A45",
        icon="piano",
    ),
    Category(
        key="podcast",
        name="播客",
        description="电台、访谈与连续更新的节目",
        hint="播客 / 电台 / 访谈 / Episode",
        accent="#4D7C67",
        icon="mic",
    ),
    Category(
        key="audiobook",
        name="有声书",
        description="长篇朗读、广播剧与故事",
        hint="有声书 / 广播剧 / 第 N 章",
        accent="#75679B",
        icon="book",
    ),
    Category(
        key="course",
        name="课程",
        description="讲座、教程与知识类录音",
        hint="课程 / 讲座 / 教程 / Lecture",
        accent="#4D7394",
        icon="cap",
    ),
    Category(
        key="sfx",
        name="音效",
        description="短音频、环境声与声音素材",
        hint="短于 22 秒 / 音效 / 声音素材 / SFX",
        accent="#AF6876",
        icon="wave",
    ),
    Category(
        key="other",
        name="其他",
        description="线索不足，等待你继续整理",
        hint="暂无足够线索",
        accent="#817F73",
        icon="dots",
    ),
)

ASSET_CATEGORY_LIST: Tuple[Category, ...] = (
    Category(
        key="animation",
        name="骨骼动作",
        description="动作、姿态、绑定与动作捕捉",
        hint="walk / run / idle / pose / BVH",
        accent="#C85A3A",
        icon="bone",
        domain="asset",
    ),
    Category(
        key="character",
        name="角色",
        description="人物、生物、NPC 与可操控角色",
        hint="角色 / character / hero / NPC",
        accent="#B08A45",
        icon="person",
        domain="asset",
    ),
    Category(
        key="prop",
        name="道具",
        description="武器、装备、摆件与场景小物",
        hint="prop / weapon / item / 道具",
        accent="#4D7C67",
        icon="sword",
        domain="asset",
    ),
    Category(
        key="scene",
        name="场景",
        description="环境、地形、关卡与建筑",
        hint="scene / level / terrain / 场景",
        accent="#4D7394",
        icon="scene",
        domain="asset",
    ),
    Category(
        key="texture",
        name="材质贴图",
        description="纹理、法线、材质与环境贴图",
        hint="albedo / normal / PBR / HDRI",
        accent="#8A6FA8",
        icon="texture",
        domain="asset",
    ),
    Category(
        key="project",
        name="工程文件",
        description="可继续编辑的源工程与项目",
        hint="blend / ma / mb / c4d / unity",
        accent="#6F7D86",
        icon="project",
        domain="asset",
    ),
    Category(
        key="model",
        name="模型",
        description="尚未指向具体用途的 3D 模型",
        hint="glb / gltf / fbx / obj / usd",
        accent="#9B6B4E",
        icon="cube",
        domain="asset",
    ),
    Category(
        key="asset_other",
        name="其他",
        description="说明文档、压缩包与未知格式",
        hint="说明文档 / 压缩包 / 未知格式",
        accent="#817F73",
        icon="dots",
        domain="asset",
    ),
)

CATEGORY_BY_KEY: Dict[str, Category] = {item.key: item for item in CATEGORY_LIST}
ASSET_CATEGORY_BY_KEY: Dict[str, Category] = {item.key: item for item in ASSET_CATEGORY_LIST}
ALL_CATEGORY_LIST: Tuple[Category, ...] = CATEGORY_LIST + ASSET_CATEGORY_LIST


# Sound effects are the one category where "音效" alone is too coarse to be
# useful.  These buckets are deliberately small, concrete and editable.
SFX_SUBCATEGORIES: Tuple[Dict[str, str], ...] = (
    {"key": "footstep", "name": "脚步", "description": "走、跑、跳与落地"},
    {"key": "sigh", "name": "叹息", "description": "呼吸、叹气与喘息"},
    {"key": "attack", "name": "攻击", "description": "打击、挥砍、枪械与冲击"},
    {"key": "water", "name": "水", "description": "雨、浪、气泡与水流"},
    {"key": "fire", "name": "火", "description": "燃烧、火焰与爆炸"},
    {"key": "animal", "name": "动物", "description": "鸟、兽、虫与宠物"},
    {"key": "mechanical", "name": "机械", "description": "引擎、齿轮、门与装置"},
    {"key": "ui", "name": "界面", "description": "点击、提示、通知与菜单"},
    {"key": "foley", "name": "拟音", "description": "衣物、纸张、玻璃与日常动作"},
    {"key": "ambience", "name": "环境", "description": "森林、城市、风声与氛围"},
    {"key": "other", "name": "其他", "description": "暂时没有更具体的线索"},
)
SFX_SUBCATEGORY_BY_KEY: Dict[str, Dict[str, str]] = {item["key"]: item for item in SFX_SUBCATEGORIES}

# Motion clips get the same treatment: "骨骼动作" is too broad when a library
# contains idles, walks, attacks and deaths.  These buckets are keyword
# guesses, never permanent judgments.
ANIMATION_SUBCATEGORIES: Tuple[Dict[str, str], ...] = (
    {"key": "idle", "name": "待机", "description": "站立、呼吸与循环待机"},
    {"key": "walk", "name": "走路", "description": "步行、巡逻与慢速移动"},
    {"key": "run", "name": "跑步", "description": "奔跑、冲刺与快速移动"},
    {"key": "jump", "name": "跳跃", "description": "起跳、腾空、落地与翻越"},
    {"key": "attack", "name": "攻击", "description": "挥砍、出拳、射击与施法"},
    {"key": "hit", "name": "受击", "description": "受伤、硬直、格挡与击退"},
    {"key": "death", "name": "死亡", "description": "倒地、阵亡与消失"},
    {"key": "dance", "name": "舞蹈", "description": "舞蹈、节奏动作与表演"},
    {"key": "gesture", "name": "手势表情", "description": "挥手、点头、说话与情绪"},
    {"key": "other", "name": "其他", "description": "暂时没有更具体的动作线索"},
)
ANIMATION_SUBCATEGORY_BY_KEY: Dict[str, Dict[str, str]] = {
    item["key"]: item for item in ANIMATION_SUBCATEGORIES
}

_ANIMATION_SUBCATEGORY_RULES: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("death", ("死亡", "倒地", "阵亡", "倒下", "去世", "death", "die", "dead", "ko", "collapse", "pass away")),
    ("hit", ("受击", "受伤", "挨打", "硬直", "格挡", "击退", "hit", "hurt", "damage", "stagger", "flinch", "block", "impact")),
    ("attack", ("攻击", "挥砍", "劈砍", "出拳", "拳击", "踢", "射击", "施法", "技能", "连招", "attack", "punch", "kick", "slash", "shoot", "cast", "spell", "combo", "fight")),
    ("jump", ("跳跃", "起跳", "腾空", "落地", "翻越", "jump", "leap", "hop", "vault", "land", "fall")),
    ("run", ("跑步", "奔跑", "冲刺", "疾跑", "run", "sprint", "jog", "dash")),
    ("walk", ("走路", "行走", "步行", "巡逻", "慢走", "walk", "patrol", "step")),
    ("idle", ("待机", "站立", "闲置", "呼吸", "循环", "idle", "stand", "breathe", "loop")),
    ("dance", ("舞蹈", "跳舞", "舞", "dance", "groove", "rhythm")),
    ("gesture", ("手势", "表情", "挥手", "点头", "说话", "鞠躬", "胜利", "gesture", "wave", "nod", "talk", "emote", "bow", "victory")),
)


def classify_animation_subcategory(rel_path: str, probe=None) -> Dict[str, str]:
    """Return a first-guess motion bucket from a path and probe metadata."""
    stats = getattr(probe, "stats", {}) if probe is not None else {}
    names = stats.get("animation_names") if isinstance(stats, dict) else None
    raw_text = " ".join(
        part
        for part in (
            rel_path.replace("\\", "/"),
            " ".join(str(name) for name in names) if isinstance(names, list) else "",
        )
        if part
    )
    text = raw_text.casefold()
    for key, keywords in _ANIMATION_SUBCATEGORY_RULES:
        for keyword in keywords:
            if keyword.casefold() in text:
                item = ANIMATION_SUBCATEGORY_BY_KEY[key]
                return {"key": item["key"], "name": item["name"]}
    item = ANIMATION_SUBCATEGORY_BY_KEY["other"]
    return {"key": item["key"], "name": item["name"]}

# More specific buckets come first; "ambience" is the broad fallback.
_SFX_SUBCATEGORY_RULES: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("footstep", ("脚步", "脚步声", "走路", "跑步", "奔跑", "踩", "踏", "鞋", "footstep", "footsteps", "step", "steps", "walk", "run", "sneaker")),
    ("sigh", ("叹息", "叹气", "呼吸", "喘息", "喘气", "深呼吸", "sigh", "breath", "breathe", "gasp", "exhale")),
    ("attack", ("攻击", "打击", "挥砍", "劈砍", "拳", "击中", "命中", "刀", "剑", "枪", "炮", "爆炸", "冲击", "attack", "hit", "impact", "punch", "slash", "sword", "gun", "shot", "explosion", "whoosh")),
    ("water", ("水", "雨", "海浪", "浪", "河", "湖", "潜水", "气泡", "水滴", "water", "rain", "ocean", "wave", "bubble", "splash", "river", "drip")),
    ("fire", ("火", "燃烧", "火焰", "篝火", "余烬", "fire", "flame", "burn", "ember")),
    ("animal", ("动物", "鸟", "狗", "猫", "马", "虫", "狼", "鸡", "牛", "羊", "animal", "bird", "dog", "cat", "horse", "insect", "wolf")),
    ("mechanical", ("机械", "引擎", "电机", "齿轮", "机器人", "液压", "装置", "引擎声", "mechanism", "engine", "motor", "gear", "robot", "servo", "machine")),
    ("ui", ("界面", "按钮", "点击", "提示", "通知", "菜单", "开关", "ui", "click", "button", "beep", "notification", "toggle", "select")),
    ("foley", ("拟音", "衣服", "摩擦", "开门", "关门", "纸张", "玻璃", "脚步外的", "foley", "cloth", "paper", "door", "glass", "rustle", "friction")),
    ("ambience", ("环境", "氛围", "森林", "城市", "风", "白噪音", "背景", "ambience", "ambient", "forest", "city", "wind", "loop", "atmosphere")),
)


def classify_sfx_subcategory(rel_path: str, meta=None) -> Dict[str, str]:
    """Return a concrete bucket for a sound effect.

    The result is intentionally editable by the user: this is a first guess,
    not a permanent judgment.
    """
    raw_text = " ".join(
        part
        for part in (
            rel_path.replace("\\", "/"),
            getattr(meta, "title", "") if meta is not None else "",
            getattr(meta, "album", "") if meta is not None else "",
            getattr(meta, "genre", "") if meta is not None else "",
        )
        if part
    )
    text = raw_text.casefold()
    for key, keywords in _SFX_SUBCATEGORY_RULES:
        for keyword in keywords:
            if keyword.casefold() in text:
                item = SFX_SUBCATEGORY_BY_KEY[key]
                return {"key": item["key"], "name": item["name"]}
    item = SFX_SUBCATEGORY_BY_KEY["other"]
    return {"key": item["key"], "name": item["name"]}


def sfx_subcategory_payload(selected: Optional[str] = None) -> List[Dict[str, object]]:
    """Subcategory list for the UI, optionally marking one as selected."""
    return [
        {
            "key": item["key"],
            "name": item["name"],
            "description": item["description"],
            "selected": item["key"] == selected,
        }
        for item in SFX_SUBCATEGORIES
    ]

# Matching order matters: the more specific editorial formats win.
_KEYWORD_RULES: Tuple[Tuple[str, Tuple[str, ...], str], ...] = (
    (
        "audiobook",
        ("有声书", "有声剧", "广播剧", "听书", "朗读", "小说", "评书", "audiobook", "audio book"),
        "有声内容",
    ),
    (
        "podcast",
        ("播客", "podcast", "电台", "访谈", "对谈", "圆桌", "节目", "频道", "radio", "episode"),
        "电台节目",
    ),
    (
        "course",
        ("课程", "教程", "讲座", "课堂", "公开课", "培训", "教学", "网课", "lecture", "lesson", "course", "tutorial"),
        "课程内容",
    ),
    (
        "sfx",
        ("音效", "声音素材", "音效库", "素材库", "环境音", "氛围声", "白噪音", "点音", "转场音", "sfx", "sound effect", "ambience", "foley", "sound design"),
        "音效素材",
    ),
    (
        "instrumental",
        ("伴奏", "纯音乐", "器乐", "钢琴", "吉他", "古筝", "小提琴", "大提琴", "练习曲", "轻音乐", "无人声", "instrumental", "karaoke", "off vocal", "backing track", "bgm"),
        "器乐作品",
    ),
)

_CHAPTER_RE = re.compile(r"第[0-9一二三四五六七八九十百零两]+[章节回卷集篇]")
_EPISODE_RE = re.compile(r"(?:^|[^a-z])(?:ep|episode|vol)[\s._-]*\d{1,4}", re.IGNORECASE)

_PODCAST_GENRES = ("podcast", "spoken word", "talk", "speech")
_AUDIOBOOK_GENRES = ("audiobook", "audio book", "spoken book")
_COURSE_GENRES = ("educational", "lecture", "course", "tutorial")
_INSTRUMENTAL_GENRES = (
    "instrumental",
    "classical",
    "ambient",
    "new age",
    "piano",
    "soundtrack",
    "score",
    "easy listening",
    "chillout",
)


def _format_seconds(seconds: Optional[float]) -> str:
    if not seconds:
        return "未知"
    total = int(round(seconds))
    minutes, sec = divmod(total, 60)
    if minutes >= 60:
        hours, minutes = divmod(minutes, 60)
        return f"{hours} 小时 {minutes} 分"
    return f"{minutes} 分 {sec} 秒"


def _has_artist_pattern(rel_path: str) -> bool:
    stem = rel_path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    return any(separator in stem for separator in (" - ", " – ", " — "))


def classify_track(rel_path: str, meta) -> Dict[str, object]:
    """Return ``{key, name, accent, reason, confidence}`` for one track."""
    raw_text = " ".join(
        part
        for part in (
            rel_path.replace("\\", "/"),
            getattr(meta, "title", ""),
            getattr(meta, "album", ""),
            getattr(meta, "genre", ""),
        )
        if part
    )
    text = raw_text.casefold()
    genre = str(getattr(meta, "genre", "") or "").casefold()
    duration = getattr(meta, "duration", None)

    # Very short files are confidently sound effects, unless they are a
    # chaptered preview that explicitly says otherwise.
    if duration is not None and 0 < duration <= 22 and not _CHAPTER_RE.search(text):
        return _result(
            "sfx",
            f"时长 {_format_seconds(duration)}，属于短音频",
            0.96,
            classify_sfx_subcategory(rel_path, meta),
        )

    for key, keywords, label in _KEYWORD_RULES:
        for keyword in keywords:
            if keyword in text:
                return _result(
                    key,
                    f"路径或元数据含「{keyword}」，识别为{label}",
                    0.91,
                    classify_sfx_subcategory(rel_path, meta) if key == "sfx" else None,
                )

    if _CHAPTER_RE.search(text):
        return _result("audiobook", "文件名呈「第 N 章 / 回」结构，识别为有声书", 0.9)
    if _EPISODE_RE.search(text):
        return _result("podcast", "文件名含节目编号，识别为播客", 0.84)

    if any(term in genre for term in _PODCAST_GENRES):
        return _result("podcast", f"流派标记为「{getattr(meta, 'genre', '')}」", 0.9)
    if any(term in genre for term in _AUDIOBOOK_GENRES):
        return _result("audiobook", f"流派标记为「{getattr(meta, 'genre', '')}」", 0.9)
    if any(term in genre for term in _COURSE_GENRES):
        return _result("course", f"流派标记为「{getattr(meta, 'genre', '')}」", 0.88)
    if any(term in genre for term in _INSTRUMENTAL_GENRES):
        return _result("instrumental", f"流派标记为「{getattr(meta, 'genre', '')}」", 0.84)

    if genre and duration and 25 <= duration <= 20 * 60:
        return _result("song", f"流派「{getattr(meta, 'genre', '')}」与歌曲时长吻合", 0.8)

    if _has_artist_pattern(rel_path) and duration and 20 <= duration <= 30 * 60:
        return _result("song", "文件名呈「歌手 - 曲名」结构，按歌曲归档", 0.68)

    if getattr(meta, "artist", "") and duration and 20 <= duration <= 20 * 60:
        return _result("song", "含艺术家信息，按歌曲归档", 0.62)

    if duration and 30 <= duration <= 15 * 60:
        return _result("song", "根据曲目时长按歌曲归档", 0.48)

    return _result("other", "暂时没有足够线索，先放入「其他」", 0.35)


def _result(
    key: str,
    reason: str,
    confidence: float,
    subcategory: Optional[Dict[str, str]] = None,
) -> Dict[str, object]:
    category = CATEGORY_BY_KEY[key]
    result: Dict[str, object] = {
        "key": key,
        "name": category.name,
        "accent": category.accent,
        "icon": category.icon,
        "domain": "audio",
        "reason": reason,
        "confidence": round(confidence, 2),
    }
    if key == "sfx":
        result["subcategory"] = subcategory or {"key": "other", "name": "其他"}
    return result


PROJECT_EXTS = {
    "blend", "blend1", "ma", "mb", "max", "c4d", "uproject", "uasset", "umap",
    "unity", "prefab", "asset", "zpr", "ztl", "spp", "sbsar", "hip", "hipnc",
    "fcstd", "nk", "nuke",
}
TEXTURE_EXTS = {
    "png", "jpg", "jpeg", "webp", "gif", "tga", "exr", "hdr", "psd", "tif",
    "tiff", "dds", "ktx", "ktx2", "mtl",
}
ANIMATION_EXTS = {"bvh", "anim", "trk", "clip"}
MODEL_EXTS = {
    "glb", "gltf", "fbx", "obj", "dae", "3ds", "stl", "ply", "usd", "usda",
    "usdc", "usdz", "abc", "step", "stp", "igs", "iges", "x3d", "wrl", "vrm",
}

CHARACTER_RE = re.compile(
    r"(角色|人物|主角|配角|人形|怪物|生物|character|characters|char|hero|npc|avatar|creature|person)",
    re.IGNORECASE,
)
PROP_RE = re.compile(
    r"(道具|武器|装备|物品|摆件|prop|props|weapon|weapons|item|items|sword|gun|shield|pickup)",
    re.IGNORECASE,
)
SCENE_RE = re.compile(
    r"(场景|环境|关卡|地形|建筑|scene|scenes|environment|env|level|levels|terrain|map|maps|world)",
    re.IGNORECASE,
)
ANIMATION_RE = re.compile(
    r"(动作|动画|骨骼|绑定|姿态|动作库|animation|animations|anim|motion|motions|rig|pose|"
    r"walk|run|jog|idle|jump|attack|dance|fight|stand|turn|drop|reach|throw|grab|look|"
    r"crouch|climb|fall|push|pull|kick|punch|wave|salute|pick|picking|fruit|react|reaction|"
    r"thrust|slash|equip|shoulder|underarm|melee|combo|dodge|stab)",
    re.IGNORECASE,
)


def _asset_result(
    key: str,
    reason: str,
    confidence: float,
    subcategory: Optional[Dict[str, str]] = None,
) -> Dict[str, object]:
    category = ASSET_CATEGORY_BY_KEY[key]
    result: Dict[str, object] = {
        "key": category.key,
        "name": category.name,
        "description": category.description,
        "hint": category.hint,
        "accent": category.accent,
        "icon": category.icon,
        "domain": "asset",
        "reason": reason,
        "confidence": round(confidence, 2),
    }
    if key == "animation":
        result["subcategory"] = subcategory or {"key": "other", "name": "其他"}
    return result


def classify_asset(rel_path: str, probe) -> Dict[str, object]:
    path = rel_path.replace("\\", "/").casefold()
    suffix = PurePosixPath(path).suffix.lstrip(".")

    if suffix in PROJECT_EXTS:
        return _asset_result("project", "工程源文件，保留可继续编辑的项目", 0.96)
    if suffix in TEXTURE_EXTS:
        return _asset_result("texture", "贴图或材质文件，按材质素材归档", 0.94)
    if suffix in ANIMATION_EXTS:
        bones = int(getattr(probe, "stats", {}).get("bones") or 0)
        subcategory = classify_animation_subcategory(rel_path, probe)
        if bones:
            return _asset_result("animation", f"动作文件 · {bones} 根骨骼", 0.98, subcategory)
        return _asset_result("animation", "BVH / 动画缓存格式，直接归入骨骼动作", 0.96, subcategory)

    if ANIMATION_RE.search(path):
        return _asset_result(
            "animation",
            "路径或文件名包含动作 / 骨骼线索",
            0.86,
            classify_animation_subcategory(rel_path, probe),
        )
    if CHARACTER_RE.search(path):
        return _asset_result("character", "路径或文件名指向角色资产", 0.9)
    if PROP_RE.search(path):
        return _asset_result("prop", "路径或文件名指向道具资产", 0.88)
    if SCENE_RE.search(path):
        return _asset_result("scene", "路径或文件名指向场景资产", 0.88)

    if suffix in MODEL_EXTS:
        animations = int(getattr(probe, "stats", {}).get("animations") or 0)
        if animations:
            return _asset_result("model", f"3D 模型，内含 {animations} 段动作但用途未定", 0.7)
        return _asset_result("model", "3D 模型格式，路径尚未指向具体用途", 0.68)
    if suffix in ("txt", "md", "pdf", "doc", "docx"):
        return _asset_result("asset_other", "说明文档，不是可预览的资产", 0.9)
    if suffix in ("zip", "7z", "rar", "tar", "gz"):
        return _asset_result("asset_other", "压缩包，暂不展开内容", 0.72)
    return _asset_result("asset_other", "暂未发现明确的三维资产线索", 0.55)


def legacy_categories() -> List[Dict[str, str]]:
    return [
        {
            "key": item.key,
            "name": item.name,
            "description": item.description,
            "hint": item.hint,
            "accent": item.accent,
            "icon": item.icon,
            "domain": item.domain,
        }
        for item in CATEGORY_LIST
    ]


def legacy_asset_categories() -> List[Dict[str, str]]:
    return [
        {
            "key": item.key,
            "name": item.name,
            "description": item.description,
            "hint": item.hint,
            "accent": item.accent,
            "icon": item.icon,
            "domain": item.domain,
        }
        for item in ASSET_CATEGORY_LIST
    ]
