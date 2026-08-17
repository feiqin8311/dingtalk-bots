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

# 堡森：短语须全部命中。预计离港/到港与已离港/已到达拆开；港名/航次/FBA 不写死。
_BAOSEN: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("bs:eta_sail", ("预计", "离港")),
    ("bs:sail", ("已离港",)),
    ("bs:eta_pod", ("预计", "到港")),
    ("bs:pod", ("已到达",)),
    ("bs:truck_out", ("卡车", "发出")),
    ("bs:truck_ok", ("卡车", "派送成功")),
)

# 美通按钉钉「出运渠道」分套。短语须全部命中（前缀匹配，国家/承运商/时间不写死）。
# 海运先匹配「预配船期」，避免文案里的「预计到港」落到真到港。
_MEITONG_TRUCK: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("mt:wh_actual", ("您的订单实际送仓时间",)),
    ("mt:wh_eta", ("您的订单预计送仓时间",)),
    ("mt:customs", ("您的订单已抵达清关地",)),
    ("mt:rail", ("预配班列",)),
    ("mt:outbound", ("仓库监装出库",)),
)
_MEITONG_SEA: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("mt:sea_sail", ("预配船期",)),
    ("mt:outbound", ("仓库监装出库",)),
    ("mt:sea_depart", ("已于", "离港")),
    ("mt:sea_pod", ("已于", "到港")),
    ("mt:sea_deliver", ("交付",)),
)


def meitong_lane(channel: str) -> str | None:
    """卡航 / 海运（含海派）。其它渠道不套美通节点。"""
    text = channel or ""
    if "卡航" in text:
        return "truck"
    if "海运" in text or "海派" in text:
        return "sea"
    return None

# Excel/通知展示用固定中文节点名（不暴露 API 中英混写原文）
_LABELS: dict[str, str] = {
    "py:KC": "船只从始发港离港",
    "py:DG": "船只到达目的港",
    "py:SC": "货件已被完整配送至亚马逊仓库",
    "lz:ningbo": "出发地 中国宁波",
    "lz:pod": "已到达卸货港",
    "lz:pickup": "已提柜",
    "lz:fc": "货物已送达 FC 场地",
    "bs:eta_sail": "预计离港",
    "bs:sail": "已离港",
    "bs:eta_pod": "预计到港",
    "bs:pod": "已到达",
    "bs:truck_out": "卡车发出",
    "bs:truck_ok": "派送成功",
    "mt:wh_actual": "实际送仓",
    "mt:wh_eta": "预计送仓",
    "mt:customs": "抵达清关地",
    "mt:rail": "预配班列",
    "mt:outbound": "仓库监装出库",
    "mt:sea_sail": "预配船期",
    "mt:sea_depart": "离港",
    "mt:sea_pod": "到港",
    "mt:sea_deliver": "交付",
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


def match_milestone(
    event: TrackEvent,
    kind: str,
    *,
    channel: str = "",
) -> str | None:
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
    if kind == "baosen":
        desc = _compact(event.description)
        for key, phrases in _BAOSEN:
            if all(_compact(p) in desc for p in phrases):
                return key
        return None
    if kind == "meitong":
        lane = meitong_lane(channel)
        table = _MEITONG_TRUCK if lane == "truck" else _MEITONG_SEA if lane == "sea" else ()
        if not table:
            return None
        desc = _compact(event.description)
        for key, phrases in table:
            if all(_compact(p) in desc for p in phrases):
                return key
        return None
    return None


def filter_new_milestones(
    events: list[TrackEvent],
    *,
    kind: str,
    already: set[str] | None = None,
    channel: str = "",
) -> list[tuple[str, TrackEvent]]:
    """
    从轨迹中筛出尚未通知的指定节点；同一 milestone key 只取第一条。
    already: 已推送过的 milestone keys。
    """
    known = set(already or ())
    seen: set[str] = set()
    out: list[tuple[str, TrackEvent]] = []
    for event in events:
        key = match_milestone(event, kind, channel=channel)
        if not key or key in seen or key in known:
            continue
        seen.add(key)
        out.append((key, event))
    return out
