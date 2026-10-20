"""Lossless physical identity rules shared by search, prices and AI selection.

Name search may ignore punctuation; parcel numbers must never do so.
Missing evidence is not evidence that two complexes are the same.
"""
import re
import unicodedata

ID_FIELDS = ("apartmentId", "kaptCode", "complexNo")


def phase_numbers(value):
    """Keep phase, complex and block numbers separate from building/parcel numbers."""
    result = {}
    value = text(value).casefold()
    for match in re.finditer(r"(\d+(?:\s*[-,·]\s*\d+)*)\s*(단지|차|bl|블록)", value):
        numbers, kind = match.groups()
        kind = "bl" if kind == "블록" else kind
        values = re.split(r"[,·]", numbers)
        result.setdefault(kind, set()).update(
            "-".join(str(int(n)) for n in re.split(r"\s*-\s*", v.strip())) for v in values
        )
    return result


def phase_conflicts(left, right):
    a, b = phase_numbers(left), phase_numbers(right)
    return any(a[k].isdisjoint(b[k]) for k in a.keys() & b.keys())


def text(value):
    return unicodedata.normalize("NFKC", str(value or "")).strip()


def parcel_key(value, legal_dong=""):
    value = text(value)
    dong = text(legal_dong)
    if dong and value.startswith(dong + " "):
        value = value[len(dong):].strip()
    value = re.sub(r"[‐‑‒–—−]", "-", value)
    value = re.sub(r"\s+", "", value)
    match = re.fullmatch(r"(산?)(\d+)(?:-(\d+))?", value)
    if match:
        mountain, main, sub = match.groups()
        return mountain + str(int(main)) + ("-" + str(int(sub)) if sub and int(sub) else "")
    # Block/lot identifiers are opaque. Preserve punctuation rather than guessing.
    return value.casefold()


def entity_parcel(entity):
    entity = entity or {}
    dong = text(entity.get("legalDong"))
    direct = text(entity.get("jibun"))
    if direct:
        return parcel_key(direct, dong)
    address = text(entity.get("address"))
    # Only a legal-dong followed by a complete parcel is a parcel address.
    # A road number, apartment building number or substring is never a fallback.
    if dong:
        match = re.search(r"(?:^|\s)" + re.escape(dong) + r"\s+(산?\s*\d+(?:\s*[-‐‑‒–—−]\s*\d+)?)$", address)
        if match:
            return parcel_key(match.group(1))
    return ""


def conflicts(left, right):
    """Reject supplied contradictory ids/locations, including stale dedupe keys."""
    for field in (*ID_FIELDS, "province", "district", "legalDong", "lawdCd"):
        a, b = text(left.get(field)), text(right.get(field))
        if a and b and a != b:
            return True
    a, b = entity_parcel(left), entity_parcel(right)
    return bool(a and b and a != b)


def satisfies(query, candidate):
    """Hard constraints for semantic selection; unknown ids/parcels cannot pass."""
    if conflicts(query, candidate):
        return False
    if phase_conflicts(query.get('name'), candidate.get('name')):
        return False
    if query.get("region") and not region_matches(query["region"], candidate):
        return False
    for field in ID_FIELDS:
        wanted = text(query.get(field))
        if wanted and text(candidate.get(field)) != wanted:
            return False
    wanted = entity_parcel(query)
    if wanted and entity_parcel(candidate) != wanted:
        return False
    dong = text(query.get("legalDong"))
    return not dong or text(candidate.get("legalDong")) == dong


def region_matches(region, entity):
    """Every supplied region token must agree, including the province."""
    def normalize(value):
        value = text(value)
        return re.sub(r"특별자치도|특별자치시|특별시|광역시|[시도](?=\s|$)", "", value)
    available = normalize(" ".join(text(entity.get(field)) for field in
                                    ("province", "city", "district", "legalDong", "address")))
    available = re.sub(r"\s+", "", available)
    return all(token in available for token in normalize(region).split())
