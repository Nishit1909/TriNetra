"""Entity resolution — threshold tuning (function 8) and new-name resolution.

Threshold tuning (:func:`tune_entity_resolution_threshold`) answers "where
should the cut-offs sit?". It does not, by itself, resolve anything — it
calibrates. The actual glue between "a fresh upload has a raw name" and "the
graph gets a person_id" lives in :func:`resolve_name` /
:func:`resolve_names_batch` below: given a raw name and the current roster of
known persons, find the best match and classify it into the same three tiers
the threshold curve was built to support (auto-merge / human review / new
person), using the thresholds the curve actually recommended by default.

Fuzzy name matching decides whether "Nils Calixto", "N. Calixto" and
"Calixto, Nils" are one person.  Rather than picking a similarity threshold
arbitrarily, :func:`tune_entity_resolution_threshold` measures precision /
recall at every candidate threshold on the labelled
``identity_resolution.csv`` pairs (105 positives, 34 negatives) and returns
the full curve plus a recommendation.

The similarity score is an *ensemble* of three RapidFuzz scorers
(``ratio``, ``token_sort_ratio``, ``token_set_ratio``) — the maximum of the
three — which handles word-order changes ("Calixto, Nils") and initials far
better than plain edit distance.  RapidFuzz is the maintained drop-in
replacement for FuzzyWuzzy (same scorer names, same 0–100 scale).

Three-tier output (the triage the backend should implement):

* ``score >= auto_merge_threshold`` – merge automatically (lowest threshold
  with **zero** false merges on the labelled set);
* ``recommended_threshold <= score < auto_merge_threshold`` – send to a human
  reviewer;
* ``score < recommended_threshold`` – treat as different people.

``recommended_threshold`` is the lowest cut-off whose precision is ≥
``min_precision`` (default 0.98; wrongly merging two different people is the
costlier error).  ``optimize_for="f1"`` uses the F1 maximiser instead.
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional

import numpy as np
import pandas as pd
from rapidfuzz import fuzz, process as rf_process

DEFAULT_THRESHOLDS: List[float] = [50, 55, 60, 65, 70, 75, 80, 85, 90, 95]
DEFAULT_THRESHOLD_HIGH = 80.0   # auto-merge, from the measured curve (zero false merges)
DEFAULT_THRESHOLD_LOW = 55.0    # below this: different person
STATUS_AUTO_MERGED = "auto_merged"
STATUS_NEEDS_REVIEW = "needs_human_review"
STATUS_NEW_PERSON = "created_new"


def match_score(a: str, b: str) -> float:
    """Ensemble similarity in [0, 100] between two name strings."""
    a, b = (a or "").strip().lower(), (b or "").strip().lower()
    if not a or not b:
        return 0.0
    return float(max(fuzz.ratio(a, b), fuzz.token_sort_ratio(a, b), fuzz.token_set_ratio(a, b)))


def tune_entity_resolution_threshold(
    identity_resolution_df: pd.DataFrame,
    candidate_thresholds: Optional[Iterable[float]] = None,
    optimize_for: str = "precision_floor",
    min_precision: float = 0.98,
    canonical_col: str = "canonical_name",
    observed_col: str = "observed_name",
    label_col: str = "match_label",
) -> Dict:
    """Precision / recall / F1 at each threshold on labelled name pairs.

    Parameters
    ----------
    identity_resolution_df
        Rows with ``canonical_name, observed_name, match_label`` (1 = same
        person, 0 = different).
    candidate_thresholds
        Similarity cut-offs (0–100) to evaluate; default 50 … 95 step 5.
    optimize_for
        ``"precision_floor"`` (default) or ``"f1"`` — see module docstring.
    min_precision
        Precision floor used by ``"precision_floor"``.

    Returns
    -------
    dict with ``recommended_threshold``, ``optimize_for``, ``curve`` (list of
    ``{threshold, precision, recall, f1, tp, fp, fn, tn}``), ``n_pairs``,
    ``n_positive``, ``n_negative``, ``auto_merge_threshold`` and
    ``review_band`` — the score range that should go to a human reviewer.
    """
    thresholds = sorted(float(t) for t in (candidate_thresholds or DEFAULT_THRESHOLDS))
    df = identity_resolution_df[[canonical_col, observed_col, label_col]].dropna()
    y = df[label_col].astype(int).values
    s = np.array([match_score(a, b) for a, b in zip(df[canonical_col], df[observed_col])])
    curve = []
    for t in thresholds:
        pred = s >= t
        tp = int((pred & (y == 1)).sum()); fp = int((pred & (y == 0)).sum())
        fn = int((~pred & (y == 1)).sum()); tn = int((~pred & (y == 0)).sum())
        p = tp / (tp + fp) if tp + fp else 0.0
        r = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * p * r / (p + r) if p + r else 0.0
        curve.append({"threshold": t, "precision": round(p, 4), "recall": round(r, 4), "f1": round(f1, 4), "tp": tp, "fp": fp, "fn": fn, "tn": tn})

    if optimize_for == "f1":
        best = max(curve, key=lambda c: (c["f1"], c["precision"]))
    else:
        ok = [c for c in curve if c["precision"] >= min_precision]
        best = min(ok, key=lambda c: c["threshold"]) if ok else max(curve, key=lambda c: (c["precision"], c["f1"]))
    f1_best = max(curve, key=lambda c: (c["f1"], c["precision"]))
    # Auto-merge only where the labelled set shows zero false merges.
    perfect = [c for c in curve if c["fp"] == 0]
    auto = min(perfect, key=lambda c: c["threshold"]) if perfect else max(curve, key=lambda c: (c["precision"], c["threshold"]))
    auto_t = max(auto["threshold"], best["threshold"])
    return {
        "recommended_threshold": best["threshold"],
        "optimize_for": optimize_for,
        "min_precision": min_precision,
        "recommended_metrics": best,
        "f1_optimal_threshold": f1_best["threshold"],
        "auto_merge_threshold": auto_t,
        "auto_merge_metrics": auto,
        "review_band": {"low": best["threshold"], "high": auto_t,
                        "note": "score >= high → auto-merge; low <= score < high → human review; score < low → keep separate"},
        "curve": curve,
        "n_pairs": int(len(y)),
        "n_positive": int(y.sum()),
        "n_negative": int(len(y) - y.sum()),
        "scorer": "max(rapidfuzz ratio, token_sort_ratio, token_set_ratio)",
    }


# --------------------------------------------------------------------------- #
# New-name resolution — the glue between an upload and a person_id
# --------------------------------------------------------------------------- #
def _best_match(name: str, choices: pd.Series) -> tuple:
    """Best (person_id, score, runner_up_score) for ``name`` against ``choices`` (a Series indexed by person_id).

    ``rapidfuzz.process.extract`` on a pandas Series returns the *index label*
    (the person_id) directly as the third element of each result tuple — not
    a positional index — so it is used as-is.
    """
    if choices.empty or not (name or "").strip():
        return None, 0.0, 0.0
    result = rf_process.extract(
        name, choices, scorer=lambda a, b, **_: match_score(a, b), limit=2, score_cutoff=0.0
    )
    if not result:
        return None, 0.0, 0.0
    _, best_score, best_person_id = result[0]
    runner_up = result[1][1] if len(result) > 1 else 0.0
    return best_person_id, float(best_score), float(runner_up)


def resolve_name(
    raw_name: str,
    persons_df: pd.DataFrame,
    threshold_high: float = DEFAULT_THRESHOLD_HIGH,
    threshold_low: float = DEFAULT_THRESHOLD_LOW,
    person_id_col: str = "person_id",
    name_col: str = "display_name",
    ambiguity_margin: float = 3.0,
    new_phone: Optional[str] = None,
    phone_index: Optional[Dict[str, set]] = None,
    uncorroborated_penalty: float = 10.0,
) -> Dict:
    """Resolve one raw name against the known roster of persons.

    This is the function called for every new name a fresh upload introduces
    (e.g. a caller name in a new CDR batch). It scores ``raw_name`` against
    every known person's ``display_name`` (via :func:`match_score`) and
    classifies the best match into the same three tiers
    :func:`tune_entity_resolution_threshold` calibrated:

    * ``score >= effective_threshold_high`` → :data:`STATUS_AUTO_MERGED` —
      treat as that existing person.
    * ``threshold_low <= score < effective_threshold_high`` →
      :data:`STATUS_NEEDS_REVIEW` — likely the same person, but a human
      should confirm before merging.
    * ``score < threshold_low`` → :data:`STATUS_NEW_PERSON` — treat as
      someone not yet in the roster (``matched_person_id`` is ``None``).

    Name similarity alone is genuinely risky ("Rajesh Mishra" vs "Ramesh
    Mishra" scores high but may be two different real people). When
    ``phone_index`` is supplied (see :func:`build_phone_index`) and
    ``new_phone`` is given, the top name candidate is checked for a
    corroborating phone number from ``cdr_records``. **Corroboration only
    raises the bar, it never lowers it or overrides a low name score** — a
    phone match cannot rescue a name that doesn't look similar at all:

    * phone corroborates the top candidate → auto-merge at
      ``threshold_high`` as normal (name evidence is trusted).
    * no phone data available, or the phone contradicts the top candidate →
      require ``threshold_high + uncorroborated_penalty`` to auto-merge
      instead; scores between the original and raised bar fall to human
      review rather than auto-merging on name alone.

    Only the single best-by-name candidate is phone-checked (not every
    candidate) — if a *worse*-scoring candidate happens to have a matching
    phone, that is not surfaced here; that scenario is rare enough that a
    human reviewer catching it in the `needs_human_review` tier is an
    acceptable trade-off for keeping this a single deterministic pass.

    Parameters
    ----------
    raw_name
        The name string as it appeared in the new data (any format/casing).
    persons_df
        Roster of known persons with at least ``person_id_col`` and ``name_col``.
    threshold_high, threshold_low
        The two cut-offs (0–100), used as-is when corroborated. Must satisfy
        ``threshold_high >= threshold_low``.
    ambiguity_margin
        If the best and second-best scores are within this many points of
        each other *and* the best score is below the effective auto-merge
        bar, the result is flagged ``ambiguous=True`` and routed to review
        regardless of tier — two different known persons scored almost
        identically, so picking either would be a guess.
    new_phone
        The phone number associated with this new record, if any (e.g. from
        a CDR row). ``None`` when no phone is available — corroboration is
        then simply skipped, not treated as a failure.
    phone_index
        Precomputed ``{phone: {person_id, ...}}`` lookup from
        :func:`build_phone_index`. Pass the same index across a whole batch
        instead of rebuilding it per name.
    uncorroborated_penalty
        Points added to ``threshold_high`` when corroboration is unavailable
        or contradicts the top name candidate. Default 10 (80 → 90).

    Returns
    -------
    dict
        ``raw_name, matched_person_id, matched_display_name, score,
        runner_up_score, ambiguous, corroboration_available, corroborated,
        effective_threshold_high, status``. ``corroboration_available`` is
        ``False`` when no ``phone_index``/``new_phone`` was given at all
        (nothing to check); ``corroborated`` is ``None`` in that case,
        ``True``/``False`` when a check was actually made. Never raises on
        an empty roster or an empty name — both simply resolve to a new
        person.
    """
    if threshold_high < threshold_low:
        raise ValueError(f"threshold_high ({threshold_high}) must be >= threshold_low ({threshold_low})")
    choices = persons_df.set_index(person_id_col)[name_col] if len(persons_df) else pd.Series(dtype=str)
    person_id, score, runner_up = _best_match(raw_name, choices)

    corroboration_available = bool(phone_index is not None and new_phone is not None and person_id is not None)
    corroborated = (person_id in phone_index.get(new_phone, set())) if corroboration_available else None
    effective_high = threshold_high if corroborated else (threshold_high + uncorroborated_penalty)

    if person_id is None or score < threshold_low:
        status = STATUS_NEW_PERSON
        person_id, matched_name, ambiguous = None, None, False
    else:
        matched_name = choices.get(person_id)
        # Ambiguity only matters here: the top match is close enough to have
        # a shot at auto-merge, but a near-identical runner-up means picking
        # it would be a guess between two *known* persons.
        ambiguous = bool(score < effective_high and (score - runner_up) <= ambiguity_margin)
        status = STATUS_NEEDS_REVIEW if (ambiguous or score < effective_high) else STATUS_AUTO_MERGED
    return {
        "raw_name": raw_name,
        "matched_person_id": person_id,
        "matched_display_name": matched_name,
        "score": round(score, 2),
        "runner_up_score": round(runner_up, 2),
        "ambiguous": ambiguous,
        "corroboration_available": corroboration_available,
        "corroborated": corroborated,
        "effective_threshold_high": effective_high,
        "status": status,
    }


def build_phone_index(
    cdr_df: Optional[pd.DataFrame],
    caller_person_col: str = "caller_person_id",
    caller_phone_col: str = "caller_phone",
    receiver_person_col: str = "receiver_person_id",
    receiver_phone_col: str = "receiver_phone",
) -> Dict[str, set]:
    """Precompute ``{phone_number: {person_id, ...}}`` from CDR records for corroboration.

    Built **once** per batch (not once per candidate person — that would
    rescan the whole CDR table for every name being resolved) and passed to
    :func:`resolve_name` / :func:`resolve_names_batch` as ``phone_index``.
    Covers a phone appearing as either the caller or the receiver, so a
    match is found regardless of which side of past calls a person was on.
    Returns ``{}`` when ``cdr_df`` is ``None`` or empty — corroboration then
    simply never triggers, it does not raise.
    """
    idx: Dict[str, set] = {}
    if cdr_df is None or cdr_df.empty:
        return idx
    for person_col, phone_col in ((caller_person_col, caller_phone_col), (receiver_person_col, receiver_phone_col)):
        if person_col not in cdr_df or phone_col not in cdr_df:
            continue
        sub = cdr_df[[phone_col, person_col]].dropna()
        for phone, pid in zip(sub[phone_col], sub[person_col]):
            idx.setdefault(phone, set()).add(pid)
    return idx


def resolve_names_batch(
    raw_names: Iterable[str],
    persons_df: pd.DataFrame,
    threshold_high: float = DEFAULT_THRESHOLD_HIGH,
    threshold_low: float = DEFAULT_THRESHOLD_LOW,
    person_id_col: str = "person_id",
    name_col: str = "display_name",
    ambiguity_margin: float = 3.0,
    new_person_prefix: str = "NEW",
    phones: Optional[Dict[str, str]] = None,
    cdr_df: Optional[pd.DataFrame] = None,
    phone_index: Optional[Dict[str, set]] = None,
    uncorroborated_penalty: float = 10.0,
) -> pd.DataFrame:
    """Resolve many raw names at once (e.g. every distinct caller in a new CDR upload).

    Runs :func:`resolve_name` for each name against the existing roster (with
    phone corroboration when available — see below), then additionally
    **cross-links names that all resolved to "new person" against each
    other** — so uploading both "Nils Calixto" and "N. Calixto" in the same
    batch (neither close enough to an *existing* roster entry, but obviously
    the same as each other) produces one placeholder person, not two.
    Cross-linking uses ``threshold_high`` (the auto-merge bar) so it never
    merges two batch names on weak evidence.

    Parameters
    ----------
    raw_names
        Distinct raw name strings to resolve (deduplicate upstream if a batch
        has repeats; repeats would just resolve identically).
    persons_df, threshold_high, threshold_low, person_id_col, name_col, ambiguity_margin
        See :func:`resolve_name`.
    new_person_prefix
        Prefix for temporary ids given to names classified as new
        (``"NEW-0001"``, …). These are **not** canonical person ids — the
        backend must mint the real one when a reviewer confirms the merge or
        creation, then remap every row sharing that temporary id together
        (that's exactly what the grouping is for).
    phones
        Optional ``{raw_name: phone_number}`` for corroboration. Names not in
        this dict (or when ``phones`` is ``None`` entirely) simply get no
        corroboration check — the effective auto-merge bar rises for them,
        nothing breaks.
    cdr_df
        CDR rows to build the corroboration index from (via
        :func:`build_phone_index`) — pass this **or** a precomputed
        ``phone_index`` directly, not both.
    phone_index
        Precomputed index; takes precedence over ``cdr_df`` if both given.
    uncorroborated_penalty
        See :func:`resolve_name`.

    Returns
    -------
    pd.DataFrame
        One row per input name: ``raw_name, matched_person_id,
        matched_display_name, score, runner_up_score, ambiguous,
        corroboration_available, corroborated, effective_threshold_high,
        status, new_person_temp_id``. ``new_person_temp_id`` is set (and
        shared across names judged to be the same new person) only when
        ``status == "created_new"``; otherwise ``None``.
    """
    if phone_index is None:
        phone_index = build_phone_index(cdr_df)
    phones = phones or {}
    names = list(dict.fromkeys(raw_names))  # de-dup, preserve order
    rows = [
        resolve_name(
            n, persons_df, threshold_high, threshold_low, person_id_col, name_col, ambiguity_margin,
            new_phone=phones.get(n), phone_index=phone_index, uncorroborated_penalty=uncorroborated_penalty,
        )
        for n in names
    ]
    df = pd.DataFrame(rows)
    df["new_person_temp_id"] = None
    if df.empty:
        return df

    new_mask = df["status"] == STATUS_NEW_PERSON
    new_names = df.loc[new_mask, "raw_name"].tolist()
    if len(new_names) > 1:
        groups: List[List[str]] = []
        assigned: Dict[str, int] = {}
        for i, a in enumerate(new_names):
            if a in assigned:
                continue
            group = [a]
            assigned[a] = len(groups)
            for b in new_names[i + 1 :]:
                if b in assigned:
                    continue
                if match_score(a, b) >= threshold_high:
                    group.append(b)
                    assigned[b] = len(groups)
            groups.append(group)
        temp_ids = {name: f"{new_person_prefix}-{i+1:04d}" for i, group in enumerate(groups) for name in group}
        df.loc[new_mask, "new_person_temp_id"] = df.loc[new_mask, "raw_name"].map(temp_ids)
    elif len(new_names) == 1:
        df.loc[new_mask, "new_person_temp_id"] = f"{new_person_prefix}-0001"
    return df
