"""Gene library version rule (E04): a released (geneId, version) is immutable.

compare_stores(prev, new) checks a new library against the previous release:
  - a (geneId, version) present in both must be identical, field for field (changing content without a version
    bump is the error seen in v5, where one gene went from soft to hard and stayed 1.0.0);
  - a geneId of the previous release may not disappear (retire it with lifecycle.state instead);
  - every (geneId, version) of the new library that the previous release does not have, for a geneId the previous
    release does have, must be strictly higher than every released version of that geneId and must differ from the
    highest released record (no bump without a content change); this holds whether the released version is kept
    alongside it or replaced by it;
  - every version string is MAJOR.MINOR.PATCH with non-negative integers.
Adding an `activation` field to a gene is a content change and needs a bump like any other.
"""


def parse_version(v):
    parts = str(v).split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        raise ValueError(f"version {v!r} is not MAJOR.MINOR.PATCH")
    return tuple(int(p) for p in parts)


def _content(g):
    return {k: v for k, v in g.items() if k != "version"}


def compare_stores(prev, new):
    """Returns {"ok", "problems", "bumped", "added", "unchanged"}; lists are sorted."""
    problems, bumped, added, unchanged = [], [], [], []
    by_prev, by_new = {}, {}
    for label, store, index in (("previous", prev, by_prev), ("new", new, by_new)):
        for g in store:
            try:
                parse_version(g["version"])
            except ValueError as e:
                problems.append(f"{label} {g['geneId']}: {e}")
                continue
            index[(g["geneId"], g["version"])] = g
    new_ids = {gid for gid, _ in by_new}
    prev_top = {}
    for gid, ver in by_prev:
        if gid not in prev_top or parse_version(ver) > parse_version(prev_top[gid]):
            prev_top[gid] = ver
    for (gid, ver), g in sorted(by_prev.items()):
        if (gid, ver) in by_new:
            if by_new[(gid, ver)] != g:
                changed = sorted(k for k in set(g) | set(by_new[(gid, ver)]) if g.get(k) != by_new[(gid, ver)].get(k))
                problems.append(f"{gid} {ver}: content changed ({', '.join(changed)}) without a version bump")
            else:
                unchanged.append(f"{gid}@{ver}")
        elif gid not in new_ids:
            problems.append(f"{gid}: removed from the library; retire it with lifecycle.state instead")
    for (gid, ver), g in sorted(by_new.items()):
        if (gid, ver) in by_prev:
            continue
        if gid not in prev_top:
            added.append(f"{gid}@{ver}")
            continue
        top = prev_top[gid]
        if parse_version(ver) <= parse_version(top):
            problems.append(f"{gid}: new version {ver} is not higher than the released version {top}")
        elif _content(g) == _content(by_prev[(gid, top)]):
            problems.append(f"{gid}: version bumped {top} -> {ver} without a content change")
        else:
            bumped.append(f"{gid}@{top}->{ver}")
    return {"ok": not problems, "problems": problems, "bumped": sorted(bumped), "added": added,
            "unchanged": sorted(unchanged)}
