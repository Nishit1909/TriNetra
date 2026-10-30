"""Validated case upload: a ZIP (or separate CSVs) becomes a NEW, isolated case.

Safety rules (from BACKEND_TASKS section 7):
- every upload creates a new case; it never writes into an existing case
- identities are taken exactly as given: no fuzzy name matching, no automatic merging
  (a duplicate person_id is an error, two people with the same name stay two people)
- everything is validated before anything is written; one transaction, all or nothing
- size, file-count, row-count and path limits stop ZIP bombs and path tricks
"""
import hashlib
import io
import math
import re
import uuid
import zipfile
from typing import Literal

import pandas as pd
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from app.security import get_principal
from .common import connect, json_safe

router = APIRouter(prefix="/api/case-uploads", tags=["ingestion"])

MAX_UPLOAD_BYTES = 25 * 1024 * 1024          # compressed upload
MAX_UNCOMPRESSED_BYTES = 150 * 1024 * 1024   # sum of CSVs after unzip
MAX_FILES_IN_ZIP = 20
MAX_ROWS = {"persons": 50_000, "relationships": 500_000, "communications": 1_000_000}
MAX_ERRORS = 50
BROADCAST_RECIPIENTS = 10                   # same rule as the derived GAStech layer
ID_RE = re.compile(r"^[A-Za-z0-9_.:\-]{1,64}$")
TYPE_RE = re.compile(r"^[A-Z0-9_&]{1,40}$")

SPEC = {
    "persons": {"required": ["person_id", "display_name"], "optional": ["department", "job_title"]},
    "relationships": {"required": ["person_a", "person_b", "relationship_type"], "optional": ["weight", "evidence_count"]},
    "communications": {"required": ["source_person_id", "target_person_id"],
                       "optional": ["communication_id", "sent_at", "subject", "recipient_count", "communication_type"]},
}


class UploadRejected(Exception):
    def __init__(self, report):
        self.report = report


def _require_creator(principal):
    # Creating a case needs edit rights: investigators and admins (local development counts as admin).
    if not (principal.is_admin or getattr(principal, "can_edit", False)):
        raise HTTPException(403, "Only investigators and administrators can upload cases.")


def _read_csv(name, raw, errors):
    try:
        df = pd.read_csv(io.BytesIO(raw), dtype=str, keep_default_na=False, na_values=[""], skipinitialspace=True)
    except Exception as exc:  # malformed CSV
        errors.append(f"{name}: could not be read as CSV ({type(exc).__name__}).")
        return None
    df.columns = [str(c).strip().lower() for c in df.columns]
    for c in df.columns:
        df[c] = df[c].map(lambda v: v.strip() if isinstance(v, str) else v)
    return df


def collect_files(uploads):
    """Return {logical_name: bytes} from a ZIP and/or individual CSV uploads, enforcing limits."""
    files, errors, total = {}, [], 0
    for name, raw in uploads:
        if len(raw) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, f"{name} is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.")
        if name.lower().endswith(".zip"):
            try:
                zf = zipfile.ZipFile(io.BytesIO(raw))
            except zipfile.BadZipFile:
                raise HTTPException(422, f"{name} is not a valid ZIP file.")
            members = [m for m in zf.infolist() if not m.is_dir()]
            if len(members) > MAX_FILES_IN_ZIP:
                raise HTTPException(422, f"ZIP has {len(members)} files; the limit is {MAX_FILES_IN_ZIP}.")
            for m in members:
                base = m.filename.replace("\\", "/").rsplit("/", 1)[-1]
                if base.startswith(".") or m.filename.startswith("__MACOSX"):
                    continue
                total += m.file_size
                if total > MAX_UNCOMPRESSED_BYTES:
                    raise HTTPException(413, "ZIP contents are too large once uncompressed.")
                key = base.lower().removesuffix(".csv")
                if key in SPEC:
                    with zf.open(m) as fh:
                        data = fh.read(MAX_UNCOMPRESSED_BYTES + 1)
                    if len(data) != m.file_size:   # declared size lied: refuse
                        raise HTTPException(422, f"{base}: size does not match the ZIP header.")
                    files[key] = data
                elif base.lower().endswith(".csv"):
                    errors.append(f"{base}: not a recognised file name (use persons.csv, relationships.csv, communications.csv); ignored.")
        else:
            total += len(raw)
            key = name.rsplit("/", 1)[-1].lower().removesuffix(".csv")
            files[key] = raw
    if total > MAX_UNCOMPRESSED_BYTES:
        raise HTTPException(413, "Upload is too large.")
    return files, errors


def validate_case_files(files):
    """Validate and normalise. Returns (tables, report). Never merges or guesses identities."""
    errors, warnings = [], []
    tables = {}

    def err(msg):
        if len(errors) < MAX_ERRORS:
            errors.append(msg)

    for name in ("persons", "relationships"):
        if name not in files:
            err(f"{name}.csv is required.")
    for name, raw in files.items():
        if name not in SPEC:
            continue
        df = _read_csv(f"{name}.csv", raw, errors)
        if df is None:
            continue
        missing = [c for c in SPEC[name]["required"] if c not in df.columns]
        if missing:
            err(f"{name}.csv is missing column(s): {', '.join(missing)}. Required: {', '.join(SPEC[name]['required'])}.")
            continue
        extra = [c for c in df.columns if c not in SPEC[name]["required"] + SPEC[name]["optional"]]
        if extra:
            warnings.append(f"{name}.csv: extra column(s) ignored: {', '.join(extra[:10])}.")
        if len(df) == 0:
            err(f"{name}.csv has no rows.")
        if len(df) > MAX_ROWS[name]:
            err(f"{name}.csv has {len(df)} rows; the limit is {MAX_ROWS[name]}.")
            continue
        tables[name] = df

    if errors or "persons" not in tables or "relationships" not in tables:
        return None, {"valid": False, "errors": errors, "warnings": warnings}

    # ---- persons: exact identities only
    p = tables["persons"].copy()
    for c in SPEC["persons"]["optional"]:
        if c not in p.columns:
            p[c] = None
    for i, row in p.iterrows():
        line = i + 2
        if not isinstance(row.person_id, str) or not ID_RE.match(row.person_id):
            err(f"persons.csv line {line}: person_id must be 1-64 letters, digits or _ . : - (got {row.person_id!r}).")
        if not isinstance(row.display_name, str) or not row.display_name or len(row.display_name) > 200:
            err(f"persons.csv line {line}: display_name is required (max 200 characters).")
    dup = p.person_id[p.person_id.duplicated(keep=False)].dropna().unique()
    if len(dup):
        err(f"persons.csv: duplicate person_id(s) {', '.join(map(str, dup[:10]))}. Each person needs a unique ID; nothing is merged automatically.")
    same_name = p.display_name[p.display_name.duplicated(keep=False)].dropna().unique()
    if len(same_name):
        warnings.append(f"{len(same_name)} display name(s) are shared by different person IDs (e.g. {same_name[0]!r}). They are kept as separate people; review if they may be the same person.")
    ids = set(p.person_id.dropna())

    # ---- relationships
    r = tables["relationships"].copy()
    r["weight"] = r["weight"] if "weight" in r.columns else "1"
    r["evidence_count"] = r["evidence_count"] if "evidence_count" in r.columns else "1"
    r["weight"] = r["weight"].fillna("1")
    r["evidence_count"] = r["evidence_count"].fillna("1")
    r["relationship_type"] = r["relationship_type"].str.upper().str.replace(" ", "_", regex=False)
    rel_rows = []
    for i, row in r.iterrows():
        line = i + 2
        a, b, t = row.person_a, row.person_b, row.relationship_type
        if a not in ids or b not in ids:
            err(f"relationships.csv line {line}: person {a if a not in ids else b!r} is not in persons.csv.")
            continue
        if a == b:
            err(f"relationships.csv line {line}: a person cannot be linked to themselves ({a}).")
            continue
        if not isinstance(t, str) or not TYPE_RE.match(t):
            err(f"relationships.csv line {line}: relationship_type must be letters/digits/underscore (got {row.relationship_type!r}).")
            continue
        try:
            w = float(row.weight)
            n = int(float(row.evidence_count))
            if not math.isfinite(w) or w < 0 or n < 1:
                raise ValueError
        except (TypeError, ValueError):
            err(f"relationships.csv line {line}: weight must be a number >= 0 and evidence_count a whole number >= 1.")
            continue
        a, b = sorted((a, b))
        rel_rows.append((a, b, t, w, n))
    rel = pd.DataFrame(rel_rows, columns=["person_a", "person_b", "relationship_type", "weight", "evidence_count"])
    if len(rel):
        before = len(rel)
        rel = rel.groupby(["person_a", "person_b", "relationship_type"], as_index=False).agg(weight=("weight", "sum"), evidence_count=("evidence_count", "sum"))
        if len(rel) < before:
            warnings.append(f"{before - len(rel)} repeated relationship row(s) (same pair and type) were combined; weights and evidence counts were added.")

    # ---- communications (optional)
    comm = None
    if "communications" in tables:
        c = tables["communications"].copy()
        for col in SPEC["communications"]["optional"]:
            if col not in c.columns:
                c[col] = None
        rows, seen_ids = [], set()
        for i, row in c.iterrows():
            line = i + 2
            s, t = row.source_person_id, row.target_person_id
            if s not in ids or t not in ids:
                err(f"communications.csv line {line}: person {s if s not in ids else t!r} is not in persons.csv.")
                continue
            if s == t:
                err(f"communications.csv line {line}: sender and recipient are the same person.")
                continue
            cid = row.communication_id if isinstance(row.communication_id, str) and row.communication_id else f"C{i + 1:07d}"
            if not ID_RE.match(cid) or cid in seen_ids:
                err(f"communications.csv line {line}: communication_id {cid!r} is invalid or repeated.")
                continue
            seen_ids.add(cid)
            sent = None
            if isinstance(row.sent_at, str) and row.sent_at:
                sent = pd.to_datetime(row.sent_at, errors="coerce")
                if pd.isna(sent):
                    err(f"communications.csv line {line}: sent_at {row.sent_at!r} is not a date/time.")
                    continue
            rc = None
            if isinstance(row.recipient_count, str) and row.recipient_count:
                try:
                    rc = int(float(row.recipient_count))
                    if rc < 1:
                        raise ValueError
                except ValueError:
                    err(f"communications.csv line {line}: recipient_count must be a whole number >= 1.")
                    continue
            ctype = (row.communication_type or "message") if isinstance(row.communication_type, str) else "message"
            rows.append({"communication_id": cid, "source_person_id": s, "target_person_id": t,
                         "communication_type": ctype.lower()[:40], "sent_at": None if sent is None else sent.to_pydatetime().replace(tzinfo=None),
                         "time_known": sent is not None, "subject": (row.subject or None) if isinstance(row.subject, str) else None,
                         "recipient_count": rc, "is_broadcast": bool(rc is not None and rc >= BROADCAST_RECIPIENTS),
                         "source_row": line})
        comm = pd.DataFrame(rows)
        if len(comm):
            # Communications become EMAILED relationships (one per pair) so the model sees them, with
            # broadcast messages handled by the model's existing broadcast rule.
            pairs = comm.assign(a=comm[["source_person_id", "target_person_id"]].min(axis=1),
                                b=comm[["source_person_id", "target_person_id"]].max(axis=1)).groupby(["a", "b"]).size()
            have = set(zip(rel.person_a, rel.person_b, rel.relationship_type)) if len(rel) else set()
            add = [(a, b, "EMAILED", float(n), int(n)) for (a, b), n in pairs.items() if (a, b, "EMAILED") not in have]
            if add:
                rel = pd.concat([rel, pd.DataFrame(add, columns=rel.columns)], ignore_index=True)
                warnings.append(f"{len(add)} communicating pair(s) were added as EMAILED relationships so the analysis can use them.")
            if comm.is_broadcast.any():
                warnings.append(f"{int(comm.is_broadcast.sum())} message(s) went to {BROADCAST_RECIPIENTS}+ recipients and are treated as broadcasts (no relationship strength).")

    report = {
        "valid": not errors, "errors": errors, "warnings": warnings,
        "counts": {"persons": int(len(p)), "relationships": int(len(rel)),
                   "communications": int(len(comm)) if comm is not None else 0},
        "relationship_types": sorted(rel.relationship_type.unique().tolist()) if len(rel) else [],
    }
    if len(errors) >= MAX_ERRORS:
        report["errors_truncated"] = True
    if errors:
        return None, report
    return {"persons": p, "relationships": rel, "communications": comm}, report


def _slug(text):
    s = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").upper()
    return s[:30] or "CASE"


def _write(conn, case_id, name, description, role, is_synthetic, source, tables, principal):
    p, rel, comm = tables["persons"], tables["relationships"], tables["communications"]
    with conn.transaction():
        conn.execute("""INSERT INTO inv.cases (case_id,name,description,source,is_synthetic,role)
                        VALUES (%s,%s,%s,%s,%s,%s)""", (case_id, name, description, source, is_synthetic, role))
        with conn.cursor() as cur:
            with cur.copy("COPY inv.persons (case_id,person_id,display_name,department,job_title,source_entity_id,identity_basis) FROM STDIN") as cp:
                for row in p.itertuples(index=False):
                    cp.write_row((case_id, row.person_id, row.display_name, row.department, row.job_title, row.person_id, "uploaded_as_given"))
            with cur.copy("COPY inv.relationships (case_id,person_a,person_b,relationship_type,weight,evidence_count,source_table,source_note) FROM STDIN") as cp:
                for row in rel.itertuples(index=False):
                    cp.write_row((case_id, row.person_a, row.person_b, row.relationship_type, float(row.weight), int(row.evidence_count),
                                  "upload", "uploaded relationships.csv" if row.relationship_type != "EMAILED" or comm is None else "uploaded"))
            if comm is not None and len(comm):
                with cur.copy("""COPY inv.communication_events (case_id,communication_id,source_person_id,target_person_id,communication_type,
                                 sent_at,time_known,subject,recipient_count,is_broadcast,source_file,source_row,source_dataset) FROM STDIN""") as cp:
                    for row in comm.itertuples(index=False):
                        cp.write_row((case_id, row.communication_id, row.source_person_id, row.target_person_id, row.communication_type,
                                      row.sent_at, row.time_known, row.subject, row.recipient_count, row.is_broadcast,
                                      "communications.csv", row.source_row, "upload"))
        if not principal.local:
            conn.execute("""INSERT INTO inv.case_members (case_id,user_id,access_level) VALUES (%s,%s,'editor')
                            ON CONFLICT DO NOTHING""", (case_id, uuid.UUID(principal.user_id)))


async def _gather(file, persons, relationships, communications):
    named, raws = [], []
    for field, f in (("file", file), ("persons", persons), ("relationships", relationships), ("communications", communications)):
        if f is None:
            continue
        raw = await f.read(MAX_UPLOAD_BYTES + 1)
        raws.append(raw)
        named.append(((f.filename or "upload.zip") if field == "file" else f"{field}.csv", raw))
    if not named:
        raise HTTPException(422, "Send a ZIP as 'file', or CSVs as 'persons' and 'relationships' (and optionally 'communications').")
    return named, hashlib.sha256(b"".join(raws)).hexdigest()


@router.get("/template")
def upload_template():
    """What to upload. The frontend can show this as help text."""
    return {
        "files": {k: {"required_columns": v["required"], "optional_columns": v["optional"],
                      "required_file": k != "communications"} for k, v in SPEC.items()},
        "how": "Upload one ZIP containing persons.csv and relationships.csv (communications.csv optional), or the CSVs separately.",
        "rules": [
            "Each upload creates a new case; existing cases are never changed.",
            "person_id must be unique. People are never merged automatically, even with the same name.",
            "relationship_type examples: MEETINGS, FRIENDSHIP, KINSHIP, OPERATIONS, LOGISTICS, EMAILED, INTERCEPTED_COMMUNICATION.",
            f"Messages with {BROADCAST_RECIPIENTS}+ recipients count as broadcasts and add no relationship strength.",
            f"Limits: {MAX_UPLOAD_BYTES // (1024 * 1024)} MB upload, {MAX_UNCOMPRESSED_BYTES // (1024 * 1024)} MB unzipped, "
            f"{MAX_ROWS['persons']:,} people, {MAX_ROWS['relationships']:,} relationships.",
        ],
        "example": {
            "persons.csv": "person_id,display_name,department\nP1,Asha Rao,Finance\nP2,Vikram Shetty,Security",
            "relationships.csv": "person_a,person_b,relationship_type,weight\nP1,P2,MEETINGS,1",
        },
    }


@router.post("/validate")
async def validate_upload(request: Request,
                          file: UploadFile | None = File(None), persons: UploadFile | None = File(None),
                          relationships: UploadFile | None = File(None), communications: UploadFile | None = File(None),
                          principal=Depends(get_principal)):
    """Dry run: checks the files and returns the report. Writes nothing."""
    _require_creator(principal)
    named, digest = await _gather(file, persons, relationships, communications)
    files, file_errors = collect_files(named)
    _, report = validate_case_files(files)
    report["warnings"] = file_errors + report["warnings"]
    report["sha256"] = digest
    return json_safe(report)


@router.post("")
async def create_case_from_upload(request: Request,
                                  name: str = Form(..., min_length=3, max_length=200),
                                  description: str = Form("", max_length=2000),
                                  role: Literal["investigation", "benchmark", "centrality_example"] = Form("investigation"),
                                  is_synthetic: bool = Form(False),
                                  file: UploadFile | None = File(None), persons: UploadFile | None = File(None),
                                  relationships: UploadFile | None = File(None), communications: UploadFile | None = File(None),
                                  principal=Depends(get_principal)):
    """Validate, then create a NEW case. On any validation error nothing is written and the report is returned (422)."""
    _require_creator(principal)
    named, digest = await _gather(file, persons, relationships, communications)
    files, file_errors = collect_files(named)
    tables, report = validate_case_files(files)
    report["warnings"] = file_errors + report["warnings"]
    report["sha256"] = digest
    if tables is None:
        raise HTTPException(422, {"message": "Upload rejected; nothing was saved.", "report": json_safe(report)})
    case_id = f"CASE_UPLOAD_{_slug(name)}_{uuid.uuid4().hex[:8].upper()}"
    source = f"upload sha256={digest[:16]} by {'local' if principal.local else principal.user_id}"
    with connect() as conn:
        _write(conn, case_id, name, description or None, role, is_synthetic, source, tables, principal)
    report["case_id"] = case_id
    report["next"] = {"run_analysis": f"POST /api/cases/{case_id}/analysis",
                      "summary": f"GET /api/cases/{case_id}/summary"}
    return json_safe(report)
