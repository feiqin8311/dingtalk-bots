from __future__ import annotations

import re

from pingyi_client import TrackEvent


def _compact(text: str) -> str:
    """去空白/标点后小写，便于「出发地 中国宁波」≈「出发地：中国宁波」。"""
    return re.sub(r"[\s:：·.。,，/\\_-]+", "", (text or "")).lower()


# 平谊：track_code 优先，其次描述包含关键字 → 稳定 milestone key（跨次运行去重）
_PINGYI: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    ("py:KC", ("KC",), ("船只从始发港离港",)),
    ("py:DG", ("DG",), ("船只到达目的港",)),
    ("py:SC", ("SC",), ("货件已被完整配送至亚马逊仓库", "完整配送至亚马逊仓库")),
)

# 龙舟：描述包含关键字
_LONGZHOU: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("lz:ningbo", ("出发地中国宁波",)),
    ("lz:pod", ("已到达卸货港",)),
    ("lz:pickup", ("已提柜",)),
    ("lz:fc", ("货物已送达fc场地", "货物已送达FC场地")),
)

# 美通：前缀匹配，后面的国家/仓库/时间不固定。先匹配「实际送仓」以免落到「预计送仓」。
_MEITONG: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("mt:wh_actual", ("您的订单实际送仓时间",)),
    ("mt:wh_eta", ("您的订单预计送仓时间",)),
    ("mt:customs", ("您的订单已抵达清关地",)),
    ("mt:rail", ("预配班列",)),
    ("mt:outbound", ("仓库监装出库",)),
)

# Excel/通知展示用固定中文节点名（不暴露 API 中英混写原文）
_LABELS: dict[str, str] = {
    "py:KC": "船只从始发港离港",
    "py:DG": "船只到达目的港",
    "py:SC": "货件已被完整配送至亚马逊仓库",
    "lz:ningbo": "出发地 中国宁波",
    "lz:pod": "已到达卸货港",
    "lz:pickup": "已提柜",
    "lz:fc": "货物已送达 FC 场地",
    "mt:wh_actual": "实际送仓",
    "mt:wh_eta": "预计送仓",
    "mt:customs": "抵达清关地",
    "mt:rail": "预配班列",
    "mt:outbound": "仓库监装出库",
}

# 无日期节点单独记一笔，补上日期后还能再推（不去覆盖 dated key）
UNDATED_SUFFIX = ":undated"
_OCCUR_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}\b")


def event_has_date(event: TrackEvent) -> bool:
    return bool(_OCCUR_DATE.match((event.occur_date or "").strip()))


def notify_event_key(mkey: str, dated: bool) -> str:
    return mkey if dated else f"{mkey}{UNDATED_SUFFIX}"


def base_milestone_key(key: str) -> str:
    if key.endswith(UNDATED_SUFFIX):
        return key[: -len(UNDATED_SUFFIX)]
    return key


def milestone_label(key: str) -> str:
    base = base_milestone_key(key)
    return _LABELS.get(base, base)


def match_milestone(event: TrackEvent, kind: str) -> str | None:
    """命中指定业务节点则返回稳定 key（如 py:KC / lz:pod），否则 None。"""
    if kind == "pingyi":
        code = (event.track_code or "").strip().upper()
        desc = _compact(event.description)
        for key, codes, phrases in _PINGYI:
            if code and code in codes:
                return key
            for phrase in phrases:
                if _compact(phrase) in desc:
                    return key
        return None
    if kind == "longzhou":
        desc = _compact(event.description)
        for key, phrases in _LONGZHOU:
            for phrase in phrases:
                if _compact(phrase) in desc:
                    return key
        return None
    if kind == "meitong":
        desc = _compact(event.description)
        for key, phrases in _MEITONG:
            for phrase in phrases:
                if _compact(phrase) in desc:
                    return key
        return None
    return None


def filter_new_milestones(
    events: list[TrackEvent],
    *,
    kind: str,
    already: set[str] | None = None,
) -> list[tuple[str, TrackEvent]]:
    """
    从轨迹中筛出尚未通知的指定节点；同一 milestone key 只取第一条。
    already: 已推送过的 milestone keys。
    """
    known = set(already or ())
    seen: set[str] = set()
    out: list[tuple[str, TrackEvent]] = []
    for event in events:
        key = match_milestone(event, kind)
        if not key or key in seen or key in known:
            continue
        seen.add(key)
        out.append((key, event))
    return out
