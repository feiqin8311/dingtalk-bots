"""Address parsing and matching helpers for shipment document checks."""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Iterable, List, Optional, Tuple


def _unique_preserve_order(items: Iterable[str]) -> List[str]:
    seen = set()
    result: List[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


ADDRESS_MATCH_PASS_SCORE = 82.0
ADDRESS_MATCH_MIN_GAP = 8.0
SUPPORTED_ADDRESS_COUNTRIES = {"US", "DE", "UK", "AU"}

_ROAD_KEYWORDS = (
    "ROAD",
    "STREET",
    "DRIVE",
    "AVENUE",
    "PASEO",
    "LANE",
    "WAY",
    "BOULEVARD",
    "BLVD",
    "COURT",
    "PLACE",
    "TERRACE",
    "HIGHWAY",
    "STRASSE",
)
_STREET_ABBR_WORD_MAP = {
    "RD": "ROAD",
    "ST": "STREET",
    "DR": "DRIVE",
    "AVE": "AVENUE",
    "BLVD": "BOULEVARD",
    "STR": "STRASSE",
}
_COMPANY_SUFFIX_TOKENS = {
    "INC",
    "INCORPORATED",
    "LLC",
    "LTD",
    "LIMITED",
    "CO",
    "COMPANY",
    "GMBH",
    "SARL",
}
_COUNTRY_WORD_TOKENS = {
    "US",
    "USA",
    "UNITED",
    "STATES",
    "GERMANY",
    "DEUTSCHLAND",
    "UK",
    "ENGLAND",
    "AU",
    "AUSTRALIA",
}

_UK_POSTAL_RE = re.compile(
    r"([A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2})(?=(?:\b|ENGLAND\b|UK\b|UNITED\s*KINGDOM\b|$))"
)
_US_CITY_STATE_ZIP_RE = re.compile(
    r"\b([A-Z][A-Z\-]*(?:\s+[A-Z][A-Z\-]*){0,3})\s+([A-Z]{2})\s+(\d{5}(?:\d{4})?)\b"
)
_US_STATE_ZIP_RE = re.compile(r"\b([A-Z]{2})\s+(\d{5}(?:\d{4})?)\b")
_DE_ZIP_CITY_RE = re.compile(r"\b(\d{5})\s*([A-Z][A-Z\s\-]+)\b")
_AU_CITY_STATE_POSTAL_RE = re.compile(r"\b([A-Z][A-Z\s\-]+)\s+(NSW|VIC|QLD|WA|SA|TAS|ACT|NT)\s+(\d{4})\b")
_NOISE_LINE_PREFIX_RE = re.compile(
    r"^\s*(ANMELDER|DECLARANT|CONSIGNEE|ATTN|ATTENTION|收件人)\s*[:：]",
    re.IGNORECASE,
)
_COUNTRY_LINE_RE = re.compile(
    r"^(美国|德国|英国|澳大利亚|澳洲|US|USA|GERMANY|DEUTSCHLAND|UK|ENGLAND|AUSTRALIA|AU)$",
    re.IGNORECASE,
)
_SOURCE_NOISE_TOKENS = {
    "ZHEJIANG",
    "HANGZHOU",
    "XIHU",
    "CHINA",
    "ROOM",
    "BUILDING",
    "DISTRICT",
    "BUSINESS",
    "CENTER",
    "WENYIXI",
    "WENRYIXI",
    "JIANGCUN",
    "YPLUSEU",
    "LIBRATON",
}
_DE_CITY_STOP_TOKENS = _SOURCE_NOISE_TOKENS | {"ROAD", "STRASSE", "NO"}
_UK_REGION_TOKENS = {"WEST", "EAST", "NORTH", "SOUTH", "MIDLANDS", "GREATER"}
_UK_STREET_DROP_TOKENS = {
    "BU",
    "B",
    "ROOM",
    "NO",
    "ENTER",
    "CENTER",
    "C",
    "ILDINGB",
    "BUILDINGB",
    "EU",
    "SARL",
    "UK",
    "AMAZON",
}


@dataclass
class AddressRecord:
    country_mode: str
    raw_text: str
    fc_code: str
    company: str = ""
    street: str = ""
    street_no: str = ""
    city: str = ""
    state: str = ""
    zip5: str = ""
    postal_code: str = ""


@dataclass
class AddressCandidateScore:
    record: AddressRecord
    score: float
    hard_ok: bool
    hard_reason: str


@dataclass
class AddressMatchOutcome:
    fc_code: str
    score: float
    gap: float
    postal_code: str
    city: str
    ocr_extracted: str
    excel_extracted: str


def _normalize_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _normalize_text_for_match(text: str) -> str:
    normalized = str(text or "").upper()
    normalized = (
        normalized.replace("Ä", "AE")
        .replace("Ö", "OE")
        .replace("Ü", "UE")
        .replace("ß", "SS")
    )
    normalized = re.sub(r"[^A-Z0-9\s]", " ", normalized)
    return _normalize_spaces(normalized)


def _normalize_uk_postal_code(postal: str) -> str:
    compact = re.sub(r"[^A-Z0-9]", "", str(postal or "").upper())
    if len(compact) < 5:
        return ""
    return f"{compact[:-3]} {compact[-3:]}"


def _normalize_au_state(value: str) -> str:
    text = _normalize_text_for_match(value)
    text = text.replace("N S W", "NSW").replace("N.S.W", "NSW")
    return text


def normalize_fc_code(value: str) -> str:
    compact = re.sub(r"[^A-Z0-9]", "", str(value or "").upper())
    if not compact:
        return ""
    match = re.search(r"[A-Z]{3}\d", compact)
    if match:
        return match.group(0)
    return compact


def detect_country_mode_by_nation(nation: Optional[str]) -> Optional[str]:
    raw = str(nation or "").strip()
    if not raw:
        return None
    upper = raw.upper()
    if "美国" in raw or "UNITED STATES" in upper or re.search(r"\bUSA?\b", upper):
        return "US"
    if "德国" in raw or "GERMANY" in upper or "DEUTSCHLAND" in upper:
        return "DE"
    if "英国" in raw or "UNITED KINGDOM" in upper or "ENGLAND" in upper or re.search(r"\bUK\b", upper):
        return "UK"
    if "澳洲" in raw or "澳大利亚" in raw or "AUSTRALIA" in upper or re.search(r"\bAU\b", upper):
        return "AU"
    return None


def _is_fc_contains_country(nation: Optional[str]) -> bool:
    text = str(nation or "").strip()
    if not text:
        return False
    return any(country in text for country in ("加拿大", "日本", "阿联酋"))


def is_fc_contains_country(nation: Optional[str]) -> bool:
    return _is_fc_contains_country(nation)


def dest_code_contains_in_ocr_text(dest_ids: List[str], ocr_text: str) -> bool:
    compact_ocr = re.sub(r"[^A-Z0-9]+", "", str(ocr_text or "").upper())
    if not compact_ocr:
        return False
    for dest_id in _unique_preserve_order(dest_ids):
        code = normalize_fc_code(dest_id)
        if not code:
            continue
        if code in compact_ocr:
            return True
    return False


def extract_destination_block(text: str) -> str:
    one_line = _normalize_spaces(str(text or "").replace("\r", " ").replace("\n", " "))
    if one_line:
        same_line_match = re.search(
            r"(?:目的地|DESTINATION)\s*[:：]?\s*(.*?)\s*(?:发货地|SHIP\s*FROM|SHIPFROM)\s*[:：]?",
            one_line,
            flags=re.IGNORECASE,
        )
        if same_line_match:
            return _normalize_spaces(same_line_match.group(1))

    lines = [line.strip() for line in str(text or "").replace("\r", "\n").splitlines() if line.strip()]
    if not lines:
        return ""

    start_idx: Optional[int] = None
    prefix_line: Optional[str] = None
    for index, line in enumerate(lines):
        if re.search(r"(目的地|DESTINATION)\s*[:：]?", line, flags=re.IGNORECASE):
            start_idx = index + 1
            line_after = re.split(r"[:：]", line, maxsplit=1)
            if len(line_after) == 2:
                prefix_line = line_after[1].strip()
            break

    if start_idx is None:
        return "\n".join(lines)

    end_idx = len(lines)
    for index in range(start_idx, len(lines)):
        if re.search(r"(发货地|SHIP\s*FROM|SHIPFROM)\s*[:：]?", lines[index], flags=re.IGNORECASE):
            end_idx = index
            break

    selected = []
    if prefix_line:
        selected.append(prefix_line)
    selected.extend(lines[start_idx:end_idx])
    return "\n".join([item for item in selected if item])


def _normalize_street_text(text: str, country_mode: str) -> str:
    normalized = _normalize_text_for_match(text)
    normalized = re.sub(r"(?<=\d)(?=[A-Z])", " ", normalized)
    normalized = re.sub(r"(?<=[A-Z])(?=\d)", " ", normalized)
    normalized = re.sub(r"\b(ROAD)(ROOM)\b", r"\1 \2", normalized)
    normalized = re.sub(r"\b(STREET)(ROOM)\b", r"\1 \2", normalized)
    normalized = re.sub(r"\b(DRIVE)(ROOM)\b", r"\1 \2", normalized)
    normalized = re.sub(r"\b(LANE)(ROOM)\b", r"\1 \2", normalized)
    normalized = re.sub(r"\b(AVENUE)(ROOM)\b", r"\1 \2", normalized)
    normalized = re.sub(r"\b([A-Z]{3,})(DR|RD|ST|AVE)\b", r"\1 \2", normalized)
    for short, full in _STREET_ABBR_WORD_MAP.items():
        normalized = re.sub(rf"\b{short}\b", full, normalized)
    if country_mode == "DE":
        normalized = re.sub(r"\bSTRASSE\b", "STRASSE", normalized)
    return normalized


def _extract_street_no(street: str, country_mode: str) -> str:
    text = _normalize_text_for_match(street)
    if country_mode == "DE":
        match = re.search(r"(\d+[A-Z]?)$", text)
        if match:
            return match.group(1)
    # For US/UK/AU, skip long numeric chunks (e.g. 310030 from source-side postal noise).
    for match in re.finditer(r"\b(\d+[A-Z]?)\b", text):
        candidate = match.group(1)
        digits = re.sub(r"\D", "", candidate)
        if not digits:
            continue
        if len(digits) <= 5:
            return candidate
    return ""


def _street_similarity(a: str, b: str) -> float:
    ta = _normalize_street_text(a, "US")
    tb = _normalize_street_text(b, "US")
    if not ta or not tb:
        return 0.0
    tokens_a = set(ta.split())
    tokens_b = set(tb.split())
    jaccard = (len(tokens_a & tokens_b) / len(tokens_a | tokens_b)) if (tokens_a or tokens_b) else 0.0
    seq = SequenceMatcher(None, ta, tb).ratio()
    return 0.6 * seq + 0.4 * jaccard


def _uk_street_token_coverage(source_street: str, candidate_street: str) -> float:
    source = _normalize_street_text(source_street, "UK")
    candidate = _normalize_street_text(candidate_street, "UK")
    if not source or not candidate:
        return 0.0

    def clean_tokens(text: str) -> List[str]:
        tokens: List[str] = []
        for token in text.split():
            if token in _UK_STREET_DROP_TOKENS or token in _SOURCE_NOISE_TOKENS:
                continue
            if token in _COUNTRY_WORD_TOKENS:
                continue
            if re.fullmatch(r"\d{3,}", token):
                continue
            tokens.append(token)
        return tokens

    source_set = set(clean_tokens(source))
    candidate_tokens = clean_tokens(candidate)
    if not source_set or not candidate_tokens:
        return 0.0
    required = [token for token in candidate_tokens if token not in {"WEST", "MIDLANDS"}]
    if not required:
        required = candidate_tokens
    matched = sum(1 for token in required if token in source_set)
    return matched / len(required)


def _company_similarity(a: str, b: str) -> float:
    ta = [token for token in _normalize_text_for_match(a).split() if token not in _COMPANY_SUFFIX_TOKENS]
    tb = [token for token in _normalize_text_for_match(b).split() if token not in _COMPANY_SUFFIX_TOKENS]
    if not ta or not tb:
        return 0.0
    a_text = " ".join(ta)
    b_text = " ".join(tb)
    return SequenceMatcher(None, a_text, b_text).ratio()


def _city_matches(expected: str, actual: str) -> bool:
    left = _normalize_text_for_match(expected)
    right = _normalize_text_for_match(actual)
    if not left or not right:
        return False
    if left == right:
        return True
    if left in right or right in left:
        return True

    left_tokens = [t for t in left.split() if t and t not in _ROAD_KEYWORDS and not re.search(r"\d", t)]
    right_tokens = [t for t in right.split() if t and t not in _ROAD_KEYWORDS and not re.search(r"\d", t)]
    if not left_tokens or not right_tokens:
        return False
    if left_tokens[-1] == right_tokens[-1] and len(left_tokens[-1]) >= 4:
        return True
    overlap = set(left_tokens) & set(right_tokens)
    if overlap and len(overlap) >= min(len(left_tokens), len(right_tokens)):
        return True
    # OCR city tokens may contain minor character errors (e.g. HAZLE vs HAZIE).
    # Accept when normalized whole-city similarity is sufficiently high.
    if SequenceMatcher(None, " ".join(left_tokens), " ".join(right_tokens)).ratio() >= 0.72:
        return True
    return False


def _is_country_line(line: str) -> bool:
    normalized = _normalize_text_for_match(line)
    if not normalized:
        return True
    if _COUNTRY_LINE_RE.match(line.strip()):
        return True
    if normalized in {"US", "USA", "GERMANY", "UK", "ENGLAND", "AUSTRALIA", "AU"}:
        return True
    return False


def _is_source_noise_line(line: str) -> bool:
    normalized = _normalize_text_for_match(line)
    if not normalized:
        return False
    tokens = set(normalized.split())
    return any(token in tokens for token in _SOURCE_NOISE_TOKENS)


def _prepare_address_lines(text: str) -> List[str]:
    lines: List[str] = []
    for raw_line in str(text or "").replace("\r", "\n").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        line = re.sub(r"^\s*(目的地|DESTINATION)\s*[:：]\s*", "", line, flags=re.IGNORECASE)
        line = re.sub(r"^\s*(发货地|SHIP\s*FROM|SHIPFROM)\s*[:：]\s*", "", line, flags=re.IGNORECASE)
        line = line.strip()
        if not line:
            continue
        if _NOISE_LINE_PREFIX_RE.search(line):
            continue
        line = re.sub(r"^\s*FBA\s*[:：]\s*", "", line, flags=re.IGNORECASE).strip()
        if not line:
            continue
        # Do not drop the whole line for one-line OCR; cut known footer tails instead.
        line = re.split(r"\b(?:CREATED|ERSTELLT)\b", line, maxsplit=1, flags=re.IGNORECASE)[0].strip()
        line = re.split(r"\bFBA[A-Z0-9]{6,}\b", line, maxsplit=1, flags=re.IGNORECASE)[0].strip()
        if not line:
            continue
        if _is_country_line(line):
            continue
        lines.append(line)
    return lines


def has_required_fields(record: AddressRecord, country_mode: str) -> bool:
    mode = (country_mode or "").upper()
    if mode == "US":
        return bool(record.street_no and record.city and record.state and record.zip5)
    if mode == "DE":
        return bool(record.street_no and record.street and record.city and record.zip5)
    if mode == "UK":
        return bool(record.postal_code and record.city and record.street)
    if mode == "AU":
        return bool(record.postal_code and record.state and record.city and record.street)
    return False


def missing_required_fields(record: AddressRecord, country_mode: str) -> List[str]:
    mode = (country_mode or "").upper()
    fields: List[str] = []
    if mode == "US":
        checks = ("street_no", "city", "state", "zip5")
    elif mode == "DE":
        checks = ("street_no", "street", "city", "zip5")
    elif mode == "UK":
        checks = ("postal_code", "city", "street")
    elif mode == "AU":
        checks = ("postal_code", "state", "city", "street")
    else:
        checks = ()
    for field_name in checks:
        if not str(getattr(record, field_name, "")).strip():
            fields.append(field_name)
    return fields


def _extract_street_segment(text: str, country_mode: str) -> str:
    source = _normalize_street_text(text, country_mode)
    if not source:
        return source

    if country_mode in ("US", "UK", "AU"):
        road_keywords_pattern = "|".join(_ROAD_KEYWORDS)
        match = re.search(
            rf"(\d{{1,5}}\s*[A-Z0-9\s\-]{{0,90}}\b(?:{road_keywords_pattern})\b)",
            source,
        )
        if match:
            return _normalize_spaces(match.group(1))

    if country_mode == "DE":
        match = re.search(r"([A-Z][A-Z\s\-]*STRASSE)\s*(\d+[A-Z]?)\b", source)
        if match:
            return _normalize_spaces(f"{match.group(1)} {match.group(2)}")
        match = re.search(r"([A-Z0-9\s\-]{1,90}\s+\d+[A-Z]?)$", source)
        if match:
            return _normalize_spaces(match.group(1))

    return source


def _extract_us_city_state_zip(text: str) -> Optional[Tuple[str, str, str]]:
    raw = str(text or "").upper()
    raw = (
        raw.replace("Ä", "AE")
        .replace("Ö", "OE")
        .replace("Ü", "UE")
        .replace("ß", "SS")
    )
    raw = re.sub(r"[^A-Z0-9,\s\-]", " ", raw)
    raw = _normalize_spaces(raw)
    if not raw:
        return None

    road_stop_tokens = set(_ROAD_KEYWORDS) | {"APT", "SUITE", "STE", "UNIT", "BLDG", "BUILDING", "NO"}
    state_zip_matches = list(_US_STATE_ZIP_RE.finditer(raw))
    candidates: List[Tuple[str, str, str, int]] = []
    for match in state_zip_matches:
        state = match.group(1).strip()
        zip5 = match.group(2)[:5]
        prefix = raw[:match.start()].strip()
        if not prefix:
            continue

        tail = prefix.split(",")[-1].strip() if "," in prefix else prefix
        tokens = tail.split()
        if not tokens:
            continue
        city_tokens_reversed: List[str] = []
        for token in reversed(tokens):
            if re.search(r"\d", token):
                break
            if token in _COUNTRY_WORD_TOKENS:
                if city_tokens_reversed:
                    break
                continue
            if token in road_stop_tokens:
                if city_tokens_reversed:
                    break
                continue
            city_tokens_reversed.append(token)
            if len(city_tokens_reversed) >= 3:
                break
        if not city_tokens_reversed:
            continue
        city = " ".join(reversed(city_tokens_reversed))
        candidates.append((city, state, zip5, match.start()))

    if candidates:
        candidates.sort(key=lambda item: item[3], reverse=True)
        return candidates[0][0], candidates[0][1], candidates[0][2]

    line = _normalize_text_for_match(raw)
    regex_matches = list(_US_CITY_STATE_ZIP_RE.finditer(line))
    if not regex_matches:
        return None

    filtered: List[Tuple[str, str, str, int, int]] = []
    for match in regex_matches:
        city = _normalize_spaces(match.group(1))
        state = match.group(2).strip()
        zip5 = match.group(3)[:5]
        city_tokens = city.split()
        if not city_tokens:
            continue
        if any(token in _ROAD_KEYWORDS for token in city_tokens):
            continue
        if any(re.search(r"\d", token) for token in city_tokens):
            continue
        filtered.append((city, state, zip5, len(city_tokens), match.start()))

    if not filtered:
        last = regex_matches[-1]
        return _normalize_spaces(last.group(1)), last.group(2).strip(), last.group(3)[:5]

    latest_start = max(item[4] for item in filtered)
    latest_candidates = [item for item in filtered if item[4] == latest_start]
    latest_candidates.sort(key=lambda item: item[3])
    chosen = latest_candidates[0]
    return chosen[0], chosen[1], chosen[2]


def _extract_uk_city_postal(text: str) -> Optional[Tuple[str, str]]:
    line = _normalize_text_for_match(text)
    matches = list(_UK_POSTAL_RE.finditer(line))
    if not matches:
        return None
    match = matches[-1]
    postal = _normalize_uk_postal_code(match.group(1))
    if not postal:
        return None

    prefix = _normalize_spaces(line[:match.start()])
    tokens = prefix.split()
    city_tokens_reversed: List[str] = []
    for token in reversed(tokens):
        if re.search(r"\d", token):
            break
        if token in _COUNTRY_WORD_TOKENS:
            if city_tokens_reversed:
                break
            continue
        if token in _ROAD_KEYWORDS:
            if city_tokens_reversed:
                break
            continue
        if token in _SOURCE_NOISE_TOKENS:
            if city_tokens_reversed:
                break
            continue
        if token in _UK_REGION_TOKENS:
            if city_tokens_reversed:
                break
            continue
        city_tokens_reversed.append(token)
        if len(city_tokens_reversed) >= 2:
            break
    if not city_tokens_reversed:
        return "", postal
    city = " ".join(reversed(city_tokens_reversed))
    return city, postal


def _extract_uk_street(lines: List[str], city: str, postal: str) -> str:
    road_pattern = re.compile(r"\b([A-Z0-9][A-Z0-9\s\-]{0,48}?\b(?:ROAD|STREET|DRIVE|LANE|WAY|AVENUE|PARK))\b")
    city_pattern = re.compile(rf"\b{re.escape(_normalize_text_for_match(city))}\b") if city else None
    postal_spaced = _normalize_text_for_match(postal)
    postal_compact = re.sub(r"[^A-Z0-9]", "", postal_spaced)
    segments: List[str] = []

    for raw in lines:
        text = _normalize_street_text(raw, "UK")
        if not text:
            continue
        if city_pattern:
            split_parts = city_pattern.split(text, maxsplit=1)
            text = split_parts[0] if split_parts else text
        if postal_spaced:
            text = re.sub(rf"\b{re.escape(postal_spaced)}\b", " ", text)
        if postal_compact:
            text = re.sub(rf"\b{re.escape(postal_compact)}\b", " ", re.sub(r"[^A-Z0-9\s]", " ", text))
            text = _normalize_street_text(text, "UK")
        for match in road_pattern.finditer(text):
            segment = _normalize_spaces(match.group(1))
            if not segment:
                continue
            raw_tokens = segment.split()
            cleaned_tokens: List[str] = []
            for token in raw_tokens:
                if token in _SOURCE_NOISE_TOKENS:
                    continue
                if token in _UK_STREET_DROP_TOKENS:
                    continue
                if re.fullmatch(r"\d{5,}", token):
                    continue
                cleaned_tokens.append(token)
            cleaned_segment = _normalize_spaces(" ".join(cleaned_tokens))
            if not cleaned_segment:
                continue
            if not re.search(r"\b(ROAD|STREET|DRIVE|LANE|WAY|AVENUE|PARK)\b", cleaned_segment):
                continue
            segments.append(cleaned_segment)

    if not segments:
        return ""
    return " ".join(_unique_preserve_order(segments))


def format_address_record_for_reply(record: AddressRecord) -> str:
    parts: List[str] = []
    if record.company:
        parts.append(f"公司={record.company}")
    if record.street:
        parts.append(f"街道={record.street}")
    if record.street_no:
        parts.append(f"门牌号={record.street_no}")
    if record.city:
        parts.append(f"城市={record.city}")
    if record.state:
        parts.append(f"州={record.state}")
    postal = record.postal_code or record.zip5
    if postal:
        parts.append(f"邮编={postal}")
    if record.fc_code:
        parts.append(f"仓库编码={record.fc_code}")
    return "; ".join(parts) if parts else "-"


def format_ocr_record_for_reply(record: AddressRecord) -> str:
    lines: List[str] = []
    if record.fc_code:
        lines.append(f"仓库编码={record.fc_code};")
    if record.street:
        lines.append(f"街道={record.street};")
    if record.street_no:
        lines.append(f"门牌号={record.street_no};")
    if record.city:
        lines.append(f"城市={record.city};")
    if record.state:
        lines.append(f"州={record.state};")
    postal = record.postal_code or record.zip5
    if postal:
        lines.append(f"邮编={postal};")
    return "\n".join(lines) if lines else "-"


def parse_address_record(text: str, country_mode: str, fc_code: str = "") -> AddressRecord:
    lines = _prepare_address_lines(text)
    normalized_lines = [_normalize_text_for_match(line) for line in lines]
    if country_mode == "DE":
        normalized_lines = [
            _normalize_spaces(re.sub(r"(?<=\d)(?=[A-Z])", " ", re.sub(r"(?<=[A-Z])(?=\d)", " ", line)))
            for line in normalized_lines
        ]
    record = AddressRecord(
        country_mode=country_mode,
        raw_text=str(text or ""),
        fc_code=normalize_fc_code(fc_code),
    )
    if not normalized_lines:
        return record

    used_indexes = set()
    city_line_index: Optional[int] = None

    street_line_index: Optional[int] = None
    if country_mode == "DE":
        for idx, line in enumerate(normalized_lines):
            if "STRASSE" in line and re.search(r"\d+[A-Z]?$", line):
                street_line_index = idx
                break
        if street_line_index is None:
            for idx, line in enumerate(normalized_lines):
                if re.search(r"[A-Z].*\d+[A-Z]?$", line):
                    street_line_index = idx
                    break
    else:
        for idx, line in enumerate(normalized_lines):
            if country_mode in ("US", "UK", "AU") and _is_source_noise_line(line):
                if country_mode == "US" and _US_STATE_ZIP_RE.search(line):
                    pass
                elif country_mode == "UK" and _UK_POSTAL_RE.search(line):
                    pass
                elif country_mode == "AU" and _AU_CITY_STATE_POSTAL_RE.search(line):
                    pass
                else:
                    continue
            contains_road_keyword = any(keyword in line for keyword in _ROAD_KEYWORDS)
            has_number = bool(re.search(r"\d", line))
            if country_mode in ("UK", "AU") and contains_road_keyword:
                street_line_index = idx
                break
            if country_mode == "US" and has_number and contains_road_keyword:
                street_line_index = idx
                break
    if street_line_index is None:
        for idx, line in enumerate(normalized_lines):
            if country_mode in ("US", "UK", "AU") and _is_source_noise_line(line):
                if country_mode == "US" and _US_STATE_ZIP_RE.search(line):
                    pass
                elif country_mode == "UK" and _UK_POSTAL_RE.search(line):
                    pass
                elif country_mode == "AU" and _AU_CITY_STATE_POSTAL_RE.search(line):
                    pass
                else:
                    continue
            if re.search(r"\d", line):
                street_line_index = idx
                break
    if street_line_index is not None:
        used_indexes.add(street_line_index)
        street_segment = _extract_street_segment(normalized_lines[street_line_index], country_mode)
        record.street = _normalize_street_text(street_segment, country_mode)
        record.street_no = _extract_street_no(record.street, country_mode)

    if country_mode == "US":
        for idx, line in enumerate(normalized_lines):
            parsed = _extract_us_city_state_zip(line)
            if not parsed:
                continue
            city_line_index = idx
            used_indexes.add(idx)
            record.city, record.state, record.zip5 = parsed
            record.postal_code = record.zip5
            break

    elif country_mode == "DE":
        for idx, line in enumerate(normalized_lines):
            match = _DE_ZIP_CITY_RE.search(line)
            if not match:
                continue
            city_line_index = idx
            used_indexes.add(idx)
            record.zip5 = match.group(1)
            record.postal_code = record.zip5
            city_raw = _normalize_spaces(match.group(2))
            city_tokens: List[str] = []
            for token in city_raw.split():
                if token in _DE_CITY_STOP_TOKENS:
                    break
                if re.search(r"\d", token):
                    break
                city_tokens.append(token)
                if len(city_tokens) >= 3:
                    break
            record.city = " ".join(city_tokens) if city_tokens else city_raw.split()[0]
            break

    elif country_mode == "UK":
        for idx, line in enumerate(normalized_lines):
            parsed = _extract_uk_city_postal(line)
            if not parsed:
                continue
            city_line_index = idx
            used_indexes.add(idx)
            parsed_city, parsed_postal = parsed
            record.postal_code = parsed_postal
            if parsed_city:
                record.city = parsed_city
            break
        if not record.city:
            start_idx = (city_line_index - 1) if city_line_index is not None else (len(normalized_lines) - 1)
            for idx in range(start_idx, -1, -1):
                candidate = normalized_lines[idx]
                if re.search(r"\d", candidate) or _is_country_line(candidate):
                    continue
                tokens = [t for t in candidate.split() if t not in _UK_REGION_TOKENS and t not in _COUNTRY_WORD_TOKENS]
                if not tokens:
                    continue
                record.city = " ".join(tokens[-2:]) if len(tokens) >= 2 else tokens[0]
                used_indexes.add(idx)
                break
        uk_street = _extract_uk_street(normalized_lines, record.city, record.postal_code)
        if uk_street:
            record.street = uk_street
            record.street_no = _extract_street_no(record.street, country_mode)

    elif country_mode == "AU":
        for idx, line in enumerate(normalized_lines):
            match = _AU_CITY_STATE_POSTAL_RE.search(line)
            if not match:
                continue
            city_line_index = idx
            used_indexes.add(idx)
            record.city = _normalize_spaces(match.group(1))
            record.state = _normalize_au_state(match.group(2))
            record.postal_code = match.group(3)
            record.zip5 = record.postal_code
            break

    company_lines: List[str] = []
    for idx, line in enumerate(normalized_lines):
        if idx in used_indexes:
            continue
        if re.search(r"\d", line):
            continue
        if _is_country_line(line):
            continue
        company_lines.append(line)
    record.company = _normalize_spaces(" ".join(company_lines))
    return record


def score_address_candidate(country_mode: str, source: AddressRecord, candidate: AddressRecord) -> AddressCandidateScore:
    mode = (country_mode or "").upper()
    street_sim = _street_similarity(source.street, candidate.street)
    company_sim = _company_similarity(source.company, candidate.company)
    hard_ok = True
    hard_reasons: List[str] = []
    score = 0.0

    if mode == "US":
        zip_ok = source.zip5 == candidate.zip5 and bool(source.zip5)
        city_ok = _city_matches(source.city, candidate.city)
        state_ok = source.state == candidate.state and bool(source.state)
        street_no_ok = source.street_no == candidate.street_no and bool(source.street_no)
        hard_ok = zip_ok and city_ok and state_ok and street_no_ok
        if not zip_ok:
            hard_reasons.append("zip5")
        if not city_ok:
            hard_reasons.append("city")
        if not state_ok:
            hard_reasons.append("state")
        if not street_no_ok:
            hard_reasons.append("street_no")
        score += 25.0 if zip_ok else 0.0
        score += 20.0 if city_ok else 0.0
        score += 20.0 if state_ok else 0.0
        score += 20.0 if street_no_ok else 0.0
        score += 10.0 * street_sim
        score += 5.0 * company_sim

    elif mode == "DE":
        zip_ok = source.zip5 == candidate.zip5 and bool(source.zip5)
        city_ok = _city_matches(source.city, candidate.city)
        street_no_ok = source.street_no == candidate.street_no and bool(source.street_no)
        street_ok = street_sim >= 0.80
        hard_ok = zip_ok and city_ok and street_no_ok and street_ok
        if not zip_ok:
            hard_reasons.append("zip5")
        if not city_ok:
            hard_reasons.append("city")
        if not street_no_ok:
            hard_reasons.append("street_no")
        if not street_ok:
            hard_reasons.append("street")
        score += 35.0 if zip_ok else 0.0
        score += 25.0 if city_ok else 0.0
        score += 20.0 if street_no_ok else 0.0
        score += 15.0 * street_sim
        score += 5.0 * company_sim

    elif mode == "UK":
        postal_ok = source.postal_code == candidate.postal_code and bool(source.postal_code)
        city_ok = _city_matches(source.city, candidate.city)
        uk_street_coverage = _uk_street_token_coverage(source.street, candidate.street)
        street_ok = street_sim >= 0.60 or uk_street_coverage >= 0.80
        hard_ok = postal_ok and city_ok and street_ok
        if not postal_ok:
            hard_reasons.append("postal_code")
        if not city_ok:
            hard_reasons.append("city")
        if not street_ok:
            hard_reasons.append("street")
        score += 40.0 if postal_ok else 0.0
        score += 25.0 if city_ok else 0.0
        score += 25.0 * max(street_sim, uk_street_coverage)
        score += 10.0 * company_sim

    elif mode == "AU":
        postal_ok = source.postal_code == candidate.postal_code and bool(source.postal_code)
        state_ok = source.state == candidate.state and bool(source.state)
        city_ok = _city_matches(source.city, candidate.city)
        street_ok = street_sim >= 0.75
        hard_ok = postal_ok and state_ok and city_ok and street_ok
        if not postal_ok:
            hard_reasons.append("postal_code")
        if not state_ok:
            hard_reasons.append("state")
        if not city_ok:
            hard_reasons.append("city")
        if not street_ok:
            hard_reasons.append("street")
        score += 35.0 if postal_ok else 0.0
        score += 20.0 if state_ok else 0.0
        score += 20.0 if city_ok else 0.0
        score += 20.0 * street_sim
        score += 5.0 * company_sim

    else:
        hard_ok = False
        hard_reasons.append("unsupported_country")

    return AddressCandidateScore(
        record=candidate,
        score=round(score, 2),
        hard_ok=hard_ok,
        hard_reason=",".join(hard_reasons) if hard_reasons else "",
    )



# Backward-compatible aliases for existing diagnostics/tests that used handler-private names.
_AddressRecord = AddressRecord
_AddressCandidateScore = AddressCandidateScore
_AddressMatchOutcome = AddressMatchOutcome
_detect_country_mode_by_nation = detect_country_mode_by_nation
_dest_code_contains_in_ocr_text = dest_code_contains_in_ocr_text
_extract_destination_block = extract_destination_block
_normalize_fc_code = normalize_fc_code
_has_required_fields = has_required_fields
_missing_required_fields = missing_required_fields
_format_address_record_for_reply = format_address_record_for_reply
_format_ocr_record_for_reply = format_ocr_record_for_reply
_parse_address_record = parse_address_record
_score_address_candidate = score_address_candidate
