"""The matching engine.

Two-sided by construction. A match is not "A likes B" — it is the
harmonic mean of both directional scores, so one-sided attraction sinks:

    s(A->B) = w_no * cover(A.needs, B.offers) + symmetric parts
    s(B->A) = w_no * cover(B.needs, A.offers) + symmetric parts
    score   = harmonic_mean(s(A->B), s(B->A))

Symmetric parts: ranked-values overlap, trait axes (each axis is declared
'sim' — closeness scores, or 'comp' — complementarity scores — in the
scenario config), interest Jaccard. Hard rules filter before scoring.
Every score ships with a human-readable breakdown: black-box matching
cannot explain itself to the user, so it loses.
"""


def _harmonic(a: float, b: float) -> float:
    if a <= 0 or b <= 0:
        return 0.0
    return 2 * a * b / (a + b)


def cover(needs, offers) -> float:
    """Fraction of `needs` covered by `offers` (canonical tags)."""
    if not needs:
        return 0.5  # no stated needs: neutral, neither rewarded nor punished
    hit = sum(1 for n in needs if n in offers)
    return hit / len(needs)


def values_score(a_vals, b_vals) -> float:
    """Rank-weighted overlap of two ranked value lists, 0..1."""
    if not a_vals or not b_vals:
        return 0.0

    def side(mine, theirs):
        n = len(mine)
        return sum((n - i) / n for i, v in enumerate(mine) if v in theirs) / n

    n = max(len(a_vals), len(b_vals))
    max_side = sum((n - i) / n for i in range(n)) / n  # identical lists
    return (side(a_vals, b_vals) + side(b_vals, a_vals)) / 2 / max_side


def traits_score(a_tr, b_tr, scenario) -> tuple:
    """Per-axis sim/comp scoring. Returns (total, per-axis detail)."""
    total_w, acc, detail = 0.0, 0.0, {}
    for axis in scenario.get("trait_axes", []):
        key, mode, w = axis["key"], axis["mode"], axis.get("weight", 1.0)
        x, y = a_tr.get(key, 0.5), b_tr.get(key, 0.5)
        s = 1 - abs(x - y) if mode == "sim" else 1 - abs(x + y - 1)
        detail[key] = {"a": x, "b": y, "mode": mode, "score": round(s, 3)}
        acc += w * s
        total_w += w
    return (acc / total_w if total_w else 0.0), detail


def interests_score(a_in, b_in) -> float:
    sa, sb = set(a_in), set(b_in)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


_KIDS_OK = {("yes", "yes"), ("no", "no")}
_KIDS_OK |= {(a, b) for a in ("yes", "no") for b in ("open",)}
_KIDS_OK |= {(a, b) for a in ("open",) for b in ("yes", "no", "open")}


def hard_filter(a: dict, b: dict) -> list:
    """Return a list of failed hard rules (empty list = pair passes)."""
    failed = []
    fa, fb = a.get("facts", {}), b.get("facts", {})
    if (fa.get("require_same_city") or fb.get("require_same_city")) and a.get(
        "city"
    ) != b.get("city"):
        failed.append(
            f"异地：{a.get('name')}在{a.get('city')}、{b.get('name')}在{b.get('city')}，而一方要求同城"
        )
    if (fa.get("wants_kids"), fb.get("wants_kids")) not in _KIDS_OK:
        failed.append("生育观冲突：一方明确想要孩子、另一方明确不想要")
    if fa.get("dealbreaker_smoking") and fb.get("smoker"):
        failed.append(f"{b.get('name')}吸烟，触发{a.get('name')}的 dealbreaker")
    if fb.get("dealbreaker_smoking") and fa.get("smoker"):
        failed.append(f"{a.get('name')}吸烟，触发{b.get('name')}的 dealbreaker")
    return failed


def pair_score(a: dict, b: dict, scenario: dict) -> dict:
    """Full two-sided score of a pair, with an explainable breakdown."""
    w = scenario.get("weights", {})
    failed = hard_filter(a, b)
    cov_ab = cover(a.get("needs", []), b.get("offers", []))  # B covers A
    cov_ba = cover(b.get("needs", []), a.get("offers", []))  # A covers B
    vs = values_score(a.get("values", []), b.get("values", []))
    ts, tdetail = traits_score(a.get("traits", {}), b.get("traits", {}), scenario)
    ins = interests_score(a.get("interests", []), b.get("interests", []))
    sym = w.get("values", 0.25) * vs + w.get("traits", 0.2) * ts + w.get(
        "interests", 0.1
    ) * ins
    s_ab = w.get("needs_offers", 0.45) * cov_ab + sym  # how well B fits A
    s_ba = w.get("needs_offers", 0.45) * cov_ba + sym  # how well A fits B
    score = 0.0 if failed else _harmonic(s_ab, s_ba)

    reasons = []
    if failed:
        reasons.extend(failed)
    else:
        got = [n for n in a.get("needs", []) if n in b.get("offers", [])]
        if got:
            reasons.append(f"{b.get('name')}能给你：{'、'.join(got)}")
        gave = [n for n in b.get("needs", []) if n in a.get("offers", [])]
        if gave:
            reasons.append(f"你能给{b.get('name')}：{'、'.join(gave)}")
        shared = [v for v in a.get("values", []) if v in b.get("values", [])]
        if shared:
            reasons.append(f"共同看重：{'、'.join(shared[:3])}")
        best_axis = max(tdetail.items(), key=lambda kv: kv[1]["score"], default=None)
        if best_axis and best_axis[1]["score"] >= 0.85:
            ax = next(
                x for x in scenario["trait_axes"] if x["key"] == best_axis[0]
            )
            kind = "很合拍" if best_axis[1]["mode"] == "sim" else "恰好互补"
            reasons.append(
                f"{ax['label']}{kind}（{best_axis[1]['a']:.2f} / {best_axis[1]['b']:.2f}）"
            )
        shared_in = [i for i in a.get("interests", []) if i in b.get("interests", [])]
        if shared_in:
            reasons.append(f"共同爱好：{'、'.join(shared_in)}")

    return {
        "candidate_id": b.get("id"),
        "score": round(score, 3),
        "score_a_to_b": round(s_ab, 3),
        "score_b_to_a": round(s_ba, 3),
        "passed": not failed,
        "failed_rules": failed,
        "breakdown": {
            "needs_covered_by_candidate": round(cov_ab, 3),
            "needs_covered_by_protagonist": round(cov_ba, 3),
            "values": round(vs, 3),
            "traits": round(ts, 3),
            "interests": round(ins, 3),
        },
        "reasons": reasons,
    }


def rank_pool(protagonist: dict, pool: list, scenario: dict) -> list:
    """Score the whole pool against one protagonist, best first.

    Hard-filtered candidates stay in the list (score 0, passed=False) —
    the demo *shows* them being rejected, with the reason attached.
    """
    results = []
    for cand in pool:
        if cand.get("id") == protagonist.get("id"):
            continue
        r = pair_score(protagonist, cand, scenario)
        r["candidate"] = {
            k: cand.get(k)
            for k in ("id", "name", "age", "city", "job", "essence", "traits")
        }
        results.append(r)
    results.sort(key=lambda r: r["score"], reverse=True)
    return results


def apply_feedback(rankings: list, trait_min: dict, penalty: float = 0.45) -> list:
    """Turn user feedback into a threshold preference and re-rank.

    Example: the user says the winner is 'too quiet' -> feedback
    {"extroversion": 0.55} demotes every candidate below that bar.
    The demotion is explicit and explainable, never a hidden re-roll.
    """
    out = []
    for r in rankings:
        r2 = dict(r)
        traits = (r.get("candidate") or {}).get("traits", {})
        demoted = [
            k for k, bar in trait_min.items() if traits.get(k, 0.5) < bar
        ]
        if r["passed"] and demoted:
            r2["score"] = round(r["score"] * penalty, 3)
            r2["demoted_by_feedback"] = demoted
        out.append(r2)
    out.sort(key=lambda r: r["score"], reverse=True)
    return out
