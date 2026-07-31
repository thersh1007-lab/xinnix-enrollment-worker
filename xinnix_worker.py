"""XINNIX Enrollment Worker (standalone).

Serves ONLY the /xinnix/* enrollment endpoints, extracted from the shared ATJ webhook.
Deploy as a Flask web service (Render, Railway, Fly, or any host).

  Env var (required):  XINNIX_GHL_TOKEN  = the GHL Private Integration Token (PIT)
  Start (production):  gunicorn xinnix_worker:app
  Start (local):       python xinnix_worker.py
  Health:              GET /health   ,   GET /xinnix/version   ,   GET /debug-logs
"""
import os, re, sys, json, time, threading, traceback
import urllib.request, urllib.parse
from datetime import datetime, timezone, timedelta
import collections as _col
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)
_debug_log = _col.deque(maxlen=50)

def _log_debug(source, msg):
    entry = "[%s] [%s] %s" % (datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"), source, msg)
    _debug_log.append(entry)
    try:
        print(entry, flush=True)
    except Exception:
        pass

@app.route("/health")
def _health():
    return jsonify({"ok": True, "service": "xinnix-enrollment-worker"})

@app.route("/debug-logs")
def _debug_logs():
    return jsonify({"entries": list(reversed(_debug_log)), "count": len(_debug_log)})


# ==================== XINNIX enrollment code (extracted verbatim) ====================

XINNIX_GHL_TOKEN = os.environ.get("XINNIX_GHL_TOKEN", "")


XINNIX_LOCATION_ID = "Q9bdjGSsuJ4q8xRHgC0Z"


XINNIX_GHL_BASE = "https://services.leadconnectorhq.com"


XINNIX_GHL_HEADERS = {
    "Version": "2021-07-28",
    "Accept": "application/json",
    "Content-Type": "application/json",
}


XINNIX_ENROLLMENT_PROGRAM_ASSOC = "697cc782d6aaff8c5c29e218"  # enrollment <-> program


XINNIX_ENROLLMENT_OPP_ASSOC = "69bb15c7a3e8f526d9ea6eb5"      # enrollment <-> opportunity


XINNIX_CONTACT_ENROLLMENT_ASSOC = "697cc5d3a0a5dae44e7a9ecc"  # contact  <-> enrollment (student_enrollments)


XINNIX_CONTACT_PROGRAM_ASSOC = "697cb20ca9b9f99ada9b4448"     # contact  <-> program (contact_to_program)


XINNIX_OPP_PROGRAM_ASSOC = "697cb2c2d6aaffa10c263440"         # program  <-> opportunity (first=program, second=opp)


XINNIX_ENROLLMENT_OBJKEY = "custom_objects.xinnix_enrollment"


XINNIX_PROGRAM_MAP = {
    "ORIGINATOR": "69b9d44b792a419835bd8242",
    "ORIGINATOR DIRECT": "69b9d44cbec0f512db2a663b",
    "ORIGINATOR ASSIST": "69b9d44d9025749e59190d61",
    "GROUND SCHOOL": "6982dc02894f3231524f312f",
    "FLIGHT SCHOOL": "6a4fad759947120df5143dd6",
    "OFFICER SCHOOL": "6a4fad752e222eedd3d451f2",
    "LEADX": "69b9d44f18d46cc49b83bbc9",
    "ELITE": "69b9d4502a6c5787f80cb7e4",
    "EDGE": "69b9d451263a5e11b3aa8802",
    "ASCEND": "69b9d4534c569f203cddf654",
    "LEADERSHIP LESSONS": "69b9d45482bd86860b99da5b",
    "ADVANTAGE": "69b9d45582bd8653c599da62",
    "SOAR": "69b9d457b88a487e76d35bd3",
    "IGNITE": "69b9d459597e6d076979fece",
    "ENERGY": "69b9d45ad9d8f4bcf0de2254",
    "OWN IT LEADERSHIP": "69b9d45c82bd867dda99da81",
    "THE PERFORMANCE ACCELERATOR": "69b9d45dd9d8f40b6dde227b",
    "LEAD CONVERSION": "69b9d45eb982408ee4037972",
    "LINKEDIN FOR LOAN OFFICERS": "69b9d45fd9d8f4dfbcde227c",
    "FHA MASTERCLASS": "69b9d460cdd250732d77abf2",
    "THE COMPLETE LOAN APPLICATION": "69b9d461a8f1720901079cc5",
    "POWERFUL PRESENTATIONS": "69b9d4626eaa14003bc06346",
    "POWER (COMMUNICATION & PARTNERSHIPS)": "69b9d46431448f52b30d1dcd",
    "POWER": "69b9d46431448f52b30d1dcd",  # bare "POWER" product -> Power program (longest-match keeps POWERFUL PRESENTATIONS distinct)
    "P&L MASTERY": "69b9d465b4e2b95df6f58679",
    "RAPID COACHING": "69b9d46626ccb6171f6302b0",
    "BUSINESS DEVELOPMENT WORKSHOP": "69b9d4682bc20b5ce42234e9",
    "RECRUITING EXPRESS": "69b9d46944bcda747d80578d",
    "RECRUITING WORKSHOP": "69b9d46a49d9aaf817fc63a0",
    "XINNIXSPEAKS HALF-DAY": "69b9d46c61671dd2c6380244",
    "KEYNOTE": "69b9d46da8f172f890079cc6",
    "XTALKS": "69b9d46ef5d2c2010e6d00c5",
    "90 MIN": "69b9d46f23351852bf61cf18",
    "ENGAGEX": "69b9d4715b13b67edc80b9e5",
    "BREAKTHROUGH ACADEMY (GUILD MORTGAGE)": "69b9d472d9d8f46b06de228a",
    "THE BREAKTHROUGH ACADEMY": "69b9d472d9d8f46b06de228a",  # BTA funnel product (info.xinnix.com checkout) -> same Guild Mortgage program record. Its new price 6a5851022f4e2532670aaad7 resolves to name "The Breakthrough Academy" but had no record link; point it here. (Tim Jul 22)
}


def _xinnix_norm_program(s):
    """Normalize a program/product name for matching: uppercase, drop trademark marks
    and punctuation, collapse spaces. So 'ORIGINATOR ASSIST(tm)' == 'ORIGINATOR ASSIST'."""
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9& ]", " ", (s or "").upper())).strip()


def _xinnix_program_records_index():
    """Build (once, cached) a normalized-name -> record_id index of the LIVE program
    records, so any product that matches an existing program auto-links even if it was
    never added to XINNIX_PROGRAM_MAP. Skips 'mashup' records (a comma OUTSIDE parens =
    several programs joined) so we never resolve to sim/junk records. Prefers the
    earliest-created record for a given name. (Tim Jul 17: 'ensure every program is handled'.)"""
    global _xinnix_prog_record_index
    if _xinnix_prog_record_index is not None:
        return _xinnix_prog_record_index
    idx = {}
    headers = {**XINNIX_GHL_HEADERS, "Authorization": f"Bearer {XINNIX_GHL_TOKEN}", "Content-Type": "application/json"}
    for page in range(1, 4):
        try:
            r = requests.post(f"{XINNIX_GHL_BASE}/objects/custom_objects.xinnix_program/records/search",
                              headers=headers, json={"locationId": XINNIX_LOCATION_ID, "page": page, "pageLimit": 100}, timeout=20)
            recs = r.json().get("records", []) if r.status_code == 200 else []
        except Exception:
            recs = []
        if not recs:
            break
        for x in recs:
            pp = x.get("properties", {}) or {}
            nm = pp.get("name") or pp.get("program_name") or ""
            if "," in re.sub(r"\([^)]*\)", "", nm):  # mashup / junk record -> skip
                continue
            key = _xinnix_norm_program(nm)
            created = x.get("createdAt") or ""
            if key and (key not in idx or created < idx[key][1]):
                idx[key] = (x.get("id"), created)
    _xinnix_prog_record_index = {k: v[0] for k, v in idx.items()}
    return _xinnix_prog_record_index


def _xinnix_resolve_program(program_name):
    """Map a program/product name (possibly with a ™ or a description suffix) to a
    Program record ID. Order: exact map match, then exact match to a live program record
    (dynamic fallback so new programs self-handle), then longest fuzzy map match so
    'ORIGINATOR ASSIST' wins over the shorter 'ORIGINATOR' prefix."""
    if not program_name:
        return None
    target = _xinnix_norm_program(program_name)
    if not target:
        return None
    best_id, best_len = None, 0
    for key, record_id in XINNIX_PROGRAM_MAP.items():
        nk = _xinnix_norm_program(key)
        if target == nk:
            return record_id  # exact normalized map match wins immediately
        if target.startswith(nk) or nk in target:
            if len(nk) > best_len:
                best_id, best_len = record_id, len(nk)
    # dynamic fallback: exact match to an existing (clean) program record
    rec_id = _xinnix_program_records_index().get(target)
    if rec_id:
        return rec_id
    # tolerant pass (only if nothing above matched): ignore spacing and a leading "THE"
    # so product-name variants still link to their program record — e.g. product
    # "Performance Accelerator" vs map "THE PERFORMANCE ACCELERATOR", or "FHA Master
    # Class" vs map "FHA MASTERCLASS". Longest match keeps specificity. Purely additive:
    # it fires ONLY when the exact + fuzzy + record-index passes all found nothing, so it
    # can add a link but never change an existing one. Same class of bug as BTA. (Jul 23)
    if not best_id:
        _sig = lambda s: re.sub(r"^THE ", "", s).replace(" ", "")
        tsig = _sig(target)
        for key, record_id in XINNIX_PROGRAM_MAP.items():
            ks = _sig(_xinnix_norm_program(key))
            if ks and (tsig == ks or tsig.startswith(ks) or ks in tsig) and len(ks) > best_len:
                best_id, best_len = record_id, len(ks)
    return best_id  # else the best fuzzy map match (may be None -> enrolls unlinked, never blocks)


def _xinnix_create_relation(association_id, first_record_id, second_record_id):
    """Create a relation between two GHL custom object records."""
    headers = {**XINNIX_GHL_HEADERS, "Authorization": f"Bearer {XINNIX_GHL_TOKEN}"}
    payload = {
        "locationId": XINNIX_LOCATION_ID,
        "associationId": association_id,
        "firstRecordId": first_record_id,
        "secondRecordId": second_record_id,
    }
    resp = requests.post(f"{XINNIX_GHL_BASE}/associations/relations", headers=headers, json=payload)
    return resp.status_code, resp.json() if resp.status_code in [200, 201] else resp.text


@app.route("/xinnix/enrollment-program-link", methods=["POST"])
def xinnix_enrollment_program_link():
    """AUTO-18 webhook: link Enrollment record to Program + Opportunity.

    Expected JSON body from GHL workflow:
    {
        "enrollment_record_id": "{{custom_object.id}}",
        "program_name": "{{opportunity.program_names_text}}",
        "opportunity_id": "{{opportunity.id}}"  (optional)
    }
    """
    data = request.get_json(force=True, silent=True)
    if not data:
        _log_debug("xinnix", "Empty/invalid JSON body received")
        return jsonify({"error": "Invalid JSON body"}), 400

    enrollment_id = (data.get("enrollment_record_id") or "").strip()
    program_name = (data.get("program_name") or "").strip()
    opportunity_id = (data.get("opportunity_id") or "").strip()

    _log_debug("xinnix", f"Received: enrollment={enrollment_id}, program={program_name}, opp={opportunity_id}")

    if not XINNIX_GHL_TOKEN:
        _log_debug("xinnix", "XINNIX_GHL_TOKEN env var not set")
        return jsonify({"error": "Server misconfigured — missing XINNIX_GHL_TOKEN"}), 500

    if not enrollment_id:
        return jsonify({"error": "enrollment_record_id is required"}), 400
    if not program_name:
        return jsonify({"error": "program_name is required"}), 400

    results = {}

    # Link Enrollment -> Program
    program_record_id = _xinnix_resolve_program(program_name)
    if not program_record_id:
        _log_debug("xinnix", f"Could not resolve program: '{program_name}'")
        return jsonify({"error": f"Unknown program: '{program_name}'"}), 422

    _log_debug("xinnix", f"Resolved '{program_name}' -> {program_record_id}")

    status, resp = _xinnix_create_relation(XINNIX_ENROLLMENT_PROGRAM_ASSOC, enrollment_id, program_record_id)
    results["enrollment_program"] = {"status": status, "response": resp}
    _log_debug("xinnix", f"Enrollment-Program: {status} -> {resp if isinstance(resp, str) else resp.get('id', '?')}")

    # Link Enrollment -> Opportunity (if provided)
    if opportunity_id:
        status2, resp2 = _xinnix_create_relation(XINNIX_ENROLLMENT_OPP_ASSOC, enrollment_id, opportunity_id)
        results["enrollment_opportunity"] = {"status": status2, "response": resp2}
        _log_debug("xinnix", f"Enrollment-Opp: {status2} -> {resp2 if isinstance(resp2, str) else resp2.get('id', '?')}")

    success = results.get("enrollment_program", {}).get("status") in [200, 201]
    return jsonify({"success": success, "results": results}), 200 if success else 502


def _xinnix_create_record(object_key, properties):
    """Create a custom-object record. Returns (status, json|text)."""
    headers = {**XINNIX_GHL_HEADERS, "Authorization": f"Bearer {XINNIX_GHL_TOKEN}"}
    payload = {"locationId": XINNIX_LOCATION_ID, "properties": properties}
    resp = requests.post(f"{XINNIX_GHL_BASE}/objects/{object_key}/records", headers=headers, json=payload)
    return resp.status_code, (resp.json() if resp.status_code in [200, 201] else resp.text)


def _xinnix_find_existing_enrollment(contact_id, program_name):
    """Idempotency guard: does this contact already have an enrollment for this program?
    Returns the enrollment record id if found, else None. Best-effort (never blocks create)."""
    try:
        pn = (program_name or "").strip().upper()
        for e in _xinnix_contact_enrollments(contact_id):
            if (e.get("program_name") or "").strip().upper() == pn:
                return e.get("enrollment_id")
    except Exception:
        return None
    return None


def _xinnix_split_programs(raw):
    """Multi-select field serializes as comma-separated; also accept a real list."""
    if isinstance(raw, list):
        items = raw
    else:
        items = str(raw or "").split(",")
    return [p.strip() for p in items if p and p.strip()]


XINNIX_OPP_PROGRAMS_FIELD = "4whpMs6i0uKrxIPVRklq"   # Program(s) / Products multi-select


XINNIX_OPP_SEATS_FIELD = "JBFLBb6pkii8R3gNl3oh"      # Number of Seats (NUMBER)


XINNIX_OPP_COMPANY_FIELD = "6oeHle7XoQ1ixSzGWqWz"    # Company Name (kept in sync w/ contact.companyName)


XINNIX_OPP_TOTALINV_FIELD = "L19TYGeduLGWKl0sDUTg"   # Total Investment (deal value)


XINNIX_OPP_ENROLLTYPE_FIELD = "eGCaYTN3Q4wtpOsCnC6v" # Enrollment Type of Opportunity


XINNIX_OPP_HEADCOUNT_FIELD = "amHBFzyro2lxlrBdoBXY"  # Student Headcount (NUMBER) — students assigned


XINNIX_OPP_ALLOTMENT_FIELD = "HriaQm0K539g5aq4PwHM"  # Seat Allotment (NUMBER) — seats purchased/allotted


XINNIX_OPP_STUDENT_FIELD = "EKvYYQFvpvScSjfVTBgZ"    # Student (TEXT) — roster: one "Name (email)" per line


XINNIX_ROSTER_READY_TAG = "xinnix-roster-ready"      # tagged on the manager when the picker is done ->


XINNIX_MORTGAGE_PIPELINE_ID = "4WBwVbSlk67zCamDg2io" # "Mortgage Team" — the enrollment pipeline.


XINNIX_CM_PIPELINE_ID = "Irm5AjzU9FzvYSL49iT9"       # "Customer Management" (onboarding)


XINNIX_CONTRACT_PIPELINE_ID = "dgWid7yxRPs5AuPus5Ca" # "Contract & Invoicing"


XINNIX_ENROLL_PIPELINES = {XINNIX_MORTGAGE_PIPELINE_ID, XINNIX_CM_PIPELINE_ID, XINNIX_CONTRACT_PIPELINE_ID}


def _xinnix_get_opportunity(opp_id):
    """Fetch a full opportunity WITH customFields + relations.
    The single GET /opportunities/{id} omits those; the search endpoint includes them,
    so we read the lean record for its contactId, then pull the rich record via search."""
    headers = {**XINNIX_GHL_HEADERS, "Authorization": f"Bearer {XINNIX_GHL_TOKEN}"}
    r = requests.get(f"{XINNIX_GHL_BASE}/opportunities/{opp_id}", headers=headers, timeout=25)
    if r.status_code != 200:
        return None
    lean = (r.json() or {}).get("opportunity") or r.json()
    cid = lean.get("contactId")
    if cid:
        s = requests.get(f"{XINNIX_GHL_BASE}/opportunities/search", headers=headers,
                         params={"location_id": XINNIX_LOCATION_ID, "contact_id": cid}, timeout=25)
        if s.status_code == 200:
            for o in s.json().get("opportunities", []):
                if o.get("id") == opp_id:
                    # the search record can omit the top-level contactId; carry it
                    # from the lean read so the order-fallback always has a contact.
                    o["contactId"] = o.get("contactId") or cid
                    return o
    return lean


def _xinnix_opp_programs(opp):
    """Programs selected on the opp's multi-select field. GHL stores this as
    fieldValueArray on some opps and fieldValue on others - read either."""
    for cf in (opp.get("customFields") or []):
        if cf.get("id") == XINNIX_OPP_PROGRAMS_FIELD:
            vals = cf.get("fieldValueArray") or cf.get("fieldValue") or []
            if isinstance(vals, str):
                vals = [vals]
            return [p for p in vals if p and str(p).strip()]
    return []


def _xinnix_opp_seats(opp):
    for cf in (opp.get("customFields") or []):
        if cf.get("id") == XINNIX_OPP_SEATS_FIELD:
            try:
                return int(cf.get("fieldValueNumber") or 0)
            except (TypeError, ValueError):
                return 0
    return 0


XINNIX_OPP_PURCHASED_FIELD = "2HbPZGBrjh1SVPdNAJFv"  # "Program Purchased Quantities (JSON)", LARGE_TEXT


def _xinnix_opp_purchased(opp):
    """Read the per-program purchased caps off the opp. Returns {program_name: int}.
    A missing/0 cap means no limit for that program."""
    for cf in (opp.get("customFields") or []):
        if cf.get("id") == XINNIX_OPP_PURCHASED_FIELD:
            raw = cf.get("fieldValueString") or cf.get("fieldValue") or ""
            try:
                d = json.loads(raw) if raw else {}
            except (ValueError, TypeError):
                return {}
            out = {}
            for k, v in (d or {}).items():
                try:
                    n = int(v)
                except (TypeError, ValueError):
                    continue
                if n > 0:
                    out[k] = n
            return out
    return {}


def _xinnix_set_opp_purchased(opp_id, caps):
    """Persist the per-program purchased caps ({program: int}) to the opp JSON field."""
    headers = {**XINNIX_GHL_HEADERS, "Authorization": f"Bearer {XINNIX_GHL_TOKEN}"}
    clean = {k: int(v) for k, v in (caps or {}).items()
             if str(v).strip() != "" and str(v).isdigit() and int(v) > 0}
    body = {"customFields": [{"id": XINNIX_OPP_PURCHASED_FIELD, "value": json.dumps(clean)}]}
    r = requests.put(f"{XINNIX_GHL_BASE}/opportunities/{opp_id}", headers=headers, json=body, timeout=25)
    return r.status_code, clean


XINNIX_CONTACT_ROLE_FIELD = "BwKPlyndHsXzzXK80Zhr"      # Role: Decision Maker/Manager/Student/Influencer/Other


XINNIX_CONTACT_ISSTUDENT_FIELD = "uCCFVOeys2LB4s0y56Z8"  # Is Student: Yes/No


def _xinnix_contact_role(cid):
    """Read a contact's Role + Is Student fields. Returns (role_lower, is_student_bool)."""
    headers = {**XINNIX_GHL_HEADERS, "Authorization": f"Bearer {XINNIX_GHL_TOKEN}"}
    try:
        r = requests.get(f"{XINNIX_GHL_BASE}/contacts/{cid}", headers=headers, timeout=20)
        if r.status_code != 200:
            return "", False
        c = (r.json() or {}).get("contact") or {}
    except Exception:
        return "", False
    role, isstu = "", False
    for cf in (c.get("customFields") or []):
        if cf.get("id") == XINNIX_CONTACT_ROLE_FIELD:
            role = str(cf.get("value") or "").strip().lower()
        if cf.get("id") == XINNIX_CONTACT_ISSTUDENT_FIELD:
            isstu = str(cf.get("value") or "").strip().lower() == "yes"
    return role, isstu


def _xinnix_contact_meta(cid):
    """Return {name, email, company} for a contact, cached per request-lifetime.
    Feeds the enrollment record's Student / Company fields so the "Ready to Onboard"
    notification can merge them (Casey, Jul 17: company + student were blank).
    Best-effort: returns {} and never raises on a failed lookup."""
    if not cid:
        return {}
    if cid in _xinnix_contact_meta_cache:
        return _xinnix_contact_meta_cache[cid]
    headers = {**XINNIX_GHL_HEADERS, "Authorization": f"Bearer {XINNIX_GHL_TOKEN}"}
    meta = {}
    try:
        r = requests.get(f"{XINNIX_GHL_BASE}/contacts/{cid}", headers=headers, timeout=20)
        if r.status_code == 200:
            c = (r.json() or {}).get("contact") or {}
            nm = (c.get("contactName")
                  or f"{c.get('firstName', '')} {c.get('lastName', '')}").strip()
            meta = {"name": nm, "email": c.get("email") or "",
                    "company": c.get("companyName") or "",
                    "phone": c.get("phone") or ""}
    except Exception:
        meta = {}
    _xinnix_contact_meta_cache[cid] = meta
    return meta


def _xinnix_find_or_create_contact(first, last, email, phone=""):
    """Find a contact by email, or create one (DND-safe) tagged as a picker-added student,
    with Role=Student + Is Student=Yes so the enrollment classification is correct. Used by
    the picker so a rep can enter the real student on a manager purchase instead of the buyer
    landing in the student slot. Returns (contact_id, created_bool); (None, False) on failure.
    Email required. DND=True so no marketing/automation message fires on create. (Bryn Jul 30.)"""
    email = (email or "").strip()
    if not email or not XINNIX_GHL_TOKEN:
        return None, False
    headers = {**XINNIX_GHL_HEADERS, "Authorization": f"Bearer {XINNIX_GHL_TOKEN}"}
    body = {
        "locationId": XINNIX_LOCATION_ID,
        "firstName": (first or "").strip(),
        "lastName": (last or "").strip(),
        "email": email,
        "dnd": True,
        "tags": ["picker-added-student"],
        "source": "Enrollment Picker",
        "customFields": [
            {"id": XINNIX_CONTACT_ROLE_FIELD, "field_value": "Student"},
            {"id": XINNIX_CONTACT_ISSTUDENT_FIELD, "field_value": "Yes"},
        ],
    }
    if (phone or "").strip():
        body["phone"] = phone.strip()
    try:
        r = requests.post(f"{XINNIX_GHL_BASE}/contacts/", headers=headers, json=body, timeout=25)
        if r.status_code in (200, 201):
            c = (r.json() or {}).get("contact") or {}
            return c.get("id"), True
        # Duplicate email: GHL returns 400 with the existing contact id in meta — reuse it
        # (never create a second contact for the same person). (see contact-dedup memory)
        if r.status_code in (400, 422):
            try:
                j = r.json()
            except Exception:
                j = {}
            existing = (j.get("meta") or {}).get("contactId") or (j.get("meta") or {}).get("id")
            if existing:
                return existing, False
        _log_debug("xinnix", f"find_or_create_contact {email}: HTTP {r.status_code} {r.text[:140]}")
    except Exception as _e:
        _log_debug("xinnix", f"find_or_create_contact failed: {_e}")
    return None, False


def _xinnix_students_for_manager(manager_email):
    """ESM-style reverse lookup for a cart/website MANAGER purchase. The checkout form, when the
    buyer says 'I'm a manager purchasing for someone else', creates the STUDENT as its own contact
    and stamps the buyer as that student's Manager (Manager Email = the buyer's email). So given the
    buyer's email, find the student(s) whose Manager Email points back at them. Returns
    [(contact_id, name)]. This lets a cart order placed by a manager enroll the STUDENT they listed
    instead of the buyer, with no form change. (Tim Jul 31: treat like ESM deals.)"""
    email = (manager_email or "").strip()
    if not email or not XINNIX_GHL_TOKEN:
        return []
    headers = {**XINNIX_GHL_HEADERS, "Authorization": f"Bearer {XINNIX_GHL_TOKEN}",
               "Content-Type": "application/json"}
    body = {"locationId": XINNIX_LOCATION_ID, "pageLimit": 20,
            "filters": [{"field": "customFields.jzD9Ft1k2bl9VRDLF9mJ",   # contact Manager Email
                         "operator": "eq", "value": email}]}
    try:
        r = requests.post(f"{XINNIX_GHL_BASE}/contacts/search", headers=headers, json=body, timeout=25)
        cts = r.json().get("contacts", []) if r.status_code == 200 else []
    except Exception as _e:
        _log_debug("xinnix", f"students_for_manager search failed: {_e}")
        return []
    import datetime as _dt
    _cut = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=3)
    out = []
    for c in cts:
        cid = c.get("id")
        if not cid:
            continue
        # Scope to students the modal touched for THIS purchase: a reused buyer email would
        # otherwise pull in every student ever linked to that manager. Keep only recently updated.
        _du = c.get("dateUpdated") or c.get("dateAdded") or ""
        try:
            if _du and _dt.datetime.fromisoformat(_du.replace("Z", "+00:00")) < _cut:
                continue
        except Exception:
            pass
        nm = (f"{c.get('firstName','')} {c.get('lastName','')}").strip() or c.get("email") or ""
        out.append((cid, nm))
    return out


def _xinnix_opp_contacts(opp, enroll_unclassified=False):
    """Classify the opp's related contacts by the contact-level Role field.
    ONLY contacts whose Role = Student (or Is Student = Yes) get enrolled. Role = Manager
    is the manager (also enrolled if Is Student). Decision Maker / Influencer / Other (the
    'leads that are neither') are left alone. Unclassified contacts are skipped unless
    enroll_unclassified is set, except a primary unclassified contact defaults to manager.
    Returns (manager_relation_or_None, [student_relations], [skipped_dicts])."""
    rels = [r for r in (opp.get("relations") or []) if r.get("objectKey") == "contact"]
    if not rels:
        return None, [], []
    manager, students, skipped = None, [], []
    for r in rels:
        cid = r.get("recordId")
        name = r.get("fullName") or ""
        role, isstu = _xinnix_contact_role(cid)
        if role == "manager":
            if not manager:
                manager = r
            if isstu:
                students.append(r)
        elif role == "student" or isstu:
            students.append(r)
        elif role in ("decision maker", "influencer", "other"):
            skipped.append({"contact_id": cid, "name": name, "role": role})
        elif r.get("primary"):
            if not manager:
                manager = r
        elif enroll_unclassified:
            students.append(r)
        else:
            skipped.append({"contact_id": cid, "name": name, "role": "unclassified"})
    if not manager:
        manager = next((r for r in rels if r.get("primary")), rels[0])
    return manager, students, skipped


XINNIX_WEBHOOK_VERSION = "wh-2026-07-31-payment-guard"  # bump each deploy; GET /xinnix/version to confirm live


@app.route("/xinnix/version", methods=["GET"])
def xinnix_version():
    """Confirm exactly which webhook build is live (ends deploy-guessing)."""
    return jsonify({"version": XINNIX_WEBHOOK_VERSION})


XINNIX_CONTACT_PROGRAM_FIELDS = [
    "6hUeEgcMw2Nhk1v9Epgx",   # Partner Registration Program (partner form; ALL-CAPS/dash form)
    "QLDVm7H6eXWIwx5aK6Sn",   # Program / Course (B2B / sales-team form; already opp-format)
]


XINNIX_OPP_PROGRAM_OPTIONS = [
    "ASCEND™", "Business Development Workshop", "EDGE™", "ELITE™", "FHA Master Class™",
    "IGNITE™", "Lead Conversion™", "LinkedIn for LOs™",
    "ORIGINATOR™ (Ground School & Flight School)", "ORIGINATOR™ (Ground School)",
    "ORIGINATOR™ (Ground School, Flight School & Officer School)", "ORIGINATOR™ Assist",
    "ORIGINATOR™ Direct", "POWER", "Powerful Presentations™", "Recruiting Workshop",
    "SOAR™", "The Complete Loan Application™", "OWN IT Leadership", "LEADx",
    "Mortgage Mastery Blueprint", "MANAGEx", "ELEVATEx", "LEADERSHIP Series", "The Breakthrough Academy",
    "Reverse Mortgage Bundle",
]


def _xinnix_norm_prog(s):
    s = (s or "").lower().replace("&", " and ")
    s = re.sub(r"[™®]", "", s)
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = re.sub(r"\bonly\b", " ", s)          # partner "Ground School ONLY" == opp "(Ground School)"
    return re.sub(r"\s+", " ", s).strip()


_XINNIX_OPP_PROG_BY_NORM = {_xinnix_norm_prog(o): o for o in XINNIX_OPP_PROGRAM_OPTIONS}


XINNIX_PARTNER_PROGRAM_OVERRIDES = {          # normalized partner value -> exact opp option
    "fha mortgage master class": "FHA Master Class™",
    "linked in for loan officers": "LinkedIn for LOs™",
    "leadership": "LEADERSHIP Series",
}


def _xinnix_map_partner_program(raw):
    """Map one Partner-Registration-Program value to the exact opp Programs option, or None."""
    n = _xinnix_norm_prog(raw)
    if not n:
        return None
    return XINNIX_PARTNER_PROGRAM_OVERRIDES.get(n) or _XINNIX_OPP_PROG_BY_NORM.get(n)


def _xinnix_partner_program_from_contact(contact_id):
    """Read the partner form's program field off the contact and map it to the opp Program
    option(s). Single-select, so returns 0 or 1 program (list) - a value with commas inside
    (the ORIGINATOR options) is treated as ONE value, never comma-split."""
    if not contact_id or not XINNIX_GHL_TOKEN:
        return []
    headers = {**XINNIX_GHL_HEADERS, "Authorization": f"Bearer {XINNIX_GHL_TOKEN}"}
    try:
        r = requests.get(f"{XINNIX_GHL_BASE}/contacts/{contact_id}", headers=headers, timeout=20)
        c = (r.json().get("contact") or {}) if r.status_code == 200 else {}
    except Exception:
        return []
    cvals = {cf.get("id"): (cf.get("value") if cf.get("value") is not None else cf.get("fieldValue"))
             for cf in (c.get("customFields") or [])}
    out, seen_raw = [], []
    for fid in XINNIX_CONTACT_PROGRAM_FIELDS:
        raw = cvals.get(fid)
        if raw:
            seen_raw.append(raw)
        for part in (raw if isinstance(raw, list) else ([raw] if raw else [])):
            m = _xinnix_map_partner_program(part)
            if m and m not in out:
                out.append(m)
    if seen_raw and not out:
        _log_debug("xinnix", f"partner/B2B program {seen_raw!r} did not map to an opp option")
    return out


@app.route("/xinnix/create-program-enrollment", methods=["POST"])
def xinnix_create_program_enrollment():
    """Thin route wrapper: parse the request, then respond 200 INSTANTLY and run the heavy
    enrollment + multi-deal stamping in a background thread so GHL's Custom Webhook action
    never waits (and never shows a false 'failed'). The work is idempotent — find-existing
    blocks duplicate real enrollments and the phantom guard blocks blanks — so a GHL
    auto-retry is harmless. dry_run resolves synchronously so the caller still gets the
    plan. (Tim Jul 18.)"""
    data = request.get_json(force=True, silent=True) or {}
    if not XINNIX_GHL_TOKEN:
        return jsonify({"error": "Server misconfigured — missing XINNIX_GHL_TOKEN"}), 500
    # GHL's Custom Webhook action nests the key/values you add under "customData".
    # Lift them to the top level (only filling blanks) so opportunity_id/source/etc. are read.
    _cd = data.get("customData")
    if isinstance(_cd, dict):
        for _k, _v in _cd.items():
            # GHL Custom Data keys can carry stray whitespace (a "opportunity_id " row with a
            # trailing space slipped through 06.5 and made the webhook miss the opp id entirely,
            # so it fell back to guessing the deal from the contact and grabbed the wrong old opp
            # for repeat buyers). Normalize the key so data.get("opportunity_id") always resolves.
            if isinstance(_k, str):
                _k = _k.strip()
            if _v not in (None, "", [], {}) and data.get(_k) in (None, "", [], {}):
                data[_k] = _v
    if data.get("dry_run") or request.args.get("dry_run"):
        data["dry_run"] = True
        return _xinnix_enroll_worker(data)
    data["dry_run"] = False
    def _bg(_d):
        with app.app_context():
            try:
                _xinnix_enroll_worker(_d)
            except Exception as _e:
                _log_debug("xinnix", f"async enroll worker crashed: {_e}")
    threading.Thread(target=_bg, args=(data,), daemon=True).start()
    return jsonify({"accepted": True, "async": True, "version": XINNIX_WEBHOOK_VERSION}), 200


def _xinnix_enroll_worker(data):
    """Generic enrollment engine (v2). Two ways to call it:

    A) Opportunity-driven (preferred — one fire per paid path):
       { "opportunity_id": "{{opportunity.id}}", "source": "Website Purchase" }
       The engine reads the opp's Program(s)/Products, its related contacts (primary =
       manager, others = students), and Number of Seats, then enrolls every student in
       every selected program and links the manager for roll-up.
       Optional "link_opportunity_id": read programs/contacts/seats from opportunity_id
       (the sales opp) but ATTACH the created enrollment records to this opp instead
       (e.g. the onboarding / Customer Management opp). Defaults to opportunity_id.

    B) Explicit (back-compat / online single purchase):
       { "contact_id": "...", "programs": "A,B", "opportunity_id": "...", "source": "...",
         "students": ["cid1","cid2"], "manager_contact_id": "cid", "manager_email": "..." }

    Flag "dry_run": true -> resolves + reports what it WOULD create, creates nothing.
    (request already parsed + customData lifted by the route wrapper; this runs either
    synchronously for dry_run or in a background thread for real orders.)
    """
    opportunity_id = (data.get("opportunity_id") or "").strip()
    source = (data.get("source") or "").strip() or "GHL Workflow"
    dry_run = bool(data.get("dry_run"))

    # Contact-triggered workflow (no opportunity in context): GHL still sends contact_id.
    # Recover the opportunity from the contact so the engine can read its programs/seats.
    if not opportunity_id and (data.get("contact_id") or "").strip():
        _cid = data["contact_id"].strip()
        try:
            _s = requests.get(f"{XINNIX_GHL_BASE}/opportunities/search",
                              headers={**XINNIX_GHL_HEADERS, "Authorization": f"Bearer {XINNIX_GHL_TOKEN}"},
                              params={"location_id": XINNIX_LOCATION_ID, "contact_id": _cid}, timeout=20)
            _cands = _s.json().get("opportunities", []) if _s.status_code == 200 else []
            # a contact can carry Sales/Contract/Leads deals too; only cycle the
            # Mortgage Team pipeline's deals for enrollment so we never attach to
            # the wrong deal (Tim, Jul 17). If none there, leave opp empty rather
            # than grabbing an unrelated-pipeline deal.
            _pool = [o for o in _cands if o.get("pipelineId") == XINNIX_MORTGAGE_PIPELINE_ID]
            # prefer a deal that actually has programs selected; else the first/most-recent
            _best = next((o for o in _pool if any(
                c.get("id") == XINNIX_OPP_PROGRAMS_FIELD and c.get("fieldValueArray")
                for c in (o.get("customFields") or []))), None) or (_pool[0] if _pool else None)
            if _best:
                opportunity_id = _best.get("id") or ""
                _log_debug("xinnix", f"resolved opp {opportunity_id} from contact {_cid}")
        except Exception as _e:
            _log_debug("xinnix", f"contact->opp resolve failed: {_e}")

    # Where to ATTACH the created enrollments. Default = the same opp we read from,
    # but pass link_opportunity_id to read from the sales opp while hanging the
    # enrollment records off a different opp (e.g. the onboarding / Customer Mgmt opp).
    link_opp = (data.get("link_opportunity_id") or "").strip() or opportunity_id

    # ---- resolve programs + student contacts + manager (explicit overrides opp read) ----
    programs = _xinnix_split_programs(data.get("programs"))
    students = list(data.get("students") or [])                     # list of contact_ids
    manager_id = (data.get("manager_contact_id") or "").strip()
    seats = int(data.get("seats") or data.get("quantity") or 0)
    contact_names = {}                                              # cid -> name for enrollment labels
    skipped_contacts = []                                           # leads/others not enrolled
    enroll_unclassified = bool(data.get("enroll_unclassified"))
    opp = None

    if opportunity_id and (not programs or not students):
        opp = _xinnix_get_opportunity(opportunity_id)
        if opp:
            if not programs:
                programs = _xinnix_opp_programs(opp)
            if not seats:
                seats = _xinnix_opp_seats(opp)
            mgr_rel, stu_rels, skipped_contacts = _xinnix_opp_contacts(opp, enroll_unclassified)
            if not manager_id and mgr_rel:
                manager_id = mgr_rel.get("recordId")
                contact_names[manager_id] = mgr_rel.get("fullName") or ""
            if not students:
                students = [r.get("recordId") for r in stu_rels if r.get("recordId")]
                for r in stu_rels:
                    contact_names[r.get("recordId")] = r.get("fullName") or ""

    # Cart / website MANAGER purchase: when the buyer is enrolling someone else, the checkout
    # captures the STUDENT as separate fields (student_email + name). Create/find that student
    # contact and enroll THEM, with the buyer as the manager, so the buyer is never enrolled in
    # place of the trainee (Comet bought ORIGINATOR for Raven but the buyer landed in the student
    # slot). This is the cart-side twin of the enrollment picker's Add-student. Only fires when a
    # student_email is passed and it differs from the buyer (a self-serve order has no student_*),
    # so normal buyer=student orders are untouched. 06.5 must send student_email / student_first_name
    # / student_last_name / student_phone in the webhook Custom Data. (Bryn Jul 30.)
    _stu_email = (data.get("student_email") or "").strip()
    if not students and _stu_email:
        _buyer_id = (data.get("contact_id") or "").strip() or manager_id \
                    or ((opp.get("contactId") or (opp.get("contact") or {}).get("id")) if opp else "")
        _buyer_email = (_xinnix_contact_meta(_buyer_id).get("email") or "").strip().lower() if _buyer_id else ""
        if _stu_email.lower() != _buyer_email:
            _sfirst = (data.get("student_first_name") or data.get("student_first") or "").strip()
            _slast = (data.get("student_last_name") or data.get("student_last") or "").strip()
            if not (_sfirst or _slast) and (data.get("student_name") or "").strip():
                _p = data["student_name"].strip().split(None, 1)
                _sfirst, _slast = _p[0], (_p[1] if len(_p) > 1 else "")
            _scid, _screated = _xinnix_find_or_create_contact(_sfirst, _slast, _stu_email,
                                                              data.get("student_phone") or "")
            if _scid:
                students = [_scid]
                contact_names[_scid] = f"{_sfirst} {_slast}".strip() or _stu_email
                if not manager_id and _buyer_id and _buyer_id != _scid:
                    manager_id = _buyer_id            # buyer is the manager, not a student
                _log_debug("xinnix", f"cart student capture: enrolling {_stu_email} "
                                     f"(created={_screated}) manager={manager_id}")

    # Cart/website MANAGER purchase (no explicit student in the payload): the xinnix.com checkout
    # modal already created the student contact in GHL and stamped THIS buyer as their Manager
    # before handing off to the payment link. So reverse-look-up the student(s) by Manager Email ==
    # the buyer's email (ESM-style) and enroll THEM, with the buyer as manager. If none are found
    # it is a self-serve order and the buyer is the student (handled by the back-compat below).
    # This bridges the modal->payment-link handoff with no form change. (Tim + Bryn Jul 31:
    # "if the manager and student info is filled out that is the student, otherwise it's the buyer".)
    if not students and data.get("contact_id") and (not seats or int(seats) <= 1):
        _byr = data["contact_id"].strip()
        _byr_email = (_xinnix_contact_meta(_byr).get("email") or "").strip()
        if _byr_email:
            _linked = [(c, n) for c, n in _xinnix_students_for_manager(_byr_email) if c != _byr]
            if _linked:
                students = [c for c, _ in _linked]
                for c, n in _linked:
                    contact_names[c] = n
                if not manager_id:
                    manager_id = _byr            # the buyer is the manager, not the student
                _log_debug("xinnix", f"cart manager purchase: buyer {_byr_email} -> "
                                     f"{len(students)} linked student(s), manager={manager_id}")
                # The modal saved Company + Preferred Start Date on the STUDENT, but the Ready-to-
                # Onboard reads them off the manager/buyer, so carry them over (Casey's test showed
                # both blank). Only fills when the buyer's are empty. (Jul 31.)
                try:
                    _hh = {**XINNIX_GHL_HEADERS, "Authorization": f"Bearer {XINNIX_GHL_TOKEN}"}
                    _sc = requests.get(f"{XINNIX_GHL_BASE}/contacts/{students[0]}", headers=_hh, timeout=20)
                    _sj = (_sc.json().get("contact") or {}) if _sc.status_code == 200 else {}
                    _sstart = ""
                    for _cf in (_sj.get("customFields") or []):
                        if _cf.get("id") == "qNlU1Q0zmwG00h7lX8SO":       # Preferred Start Date
                            _sstart = _cf.get("value") or _cf.get("fieldValue") or ""
                            break
                    _put, _cfp = {}, []
                    _bc = _xinnix_contact_meta(_byr)
                    if _sj.get("companyName") and not _bc.get("company"):
                        _put["companyName"] = _sj.get("companyName")
                    if _sstart:
                        _cfp.append({"id": "qNlU1Q0zmwG00h7lX8SO", "field_value": _sstart})
                    if _cfp:
                        _put["customFields"] = _cfp
                    if _put:
                        requests.put(f"{XINNIX_GHL_BASE}/contacts/{_byr}", headers=_hh, json=_put, timeout=20)
                except Exception as _e:
                    _log_debug("xinnix", f"cart company/start carry failed: {_e}")

    # back-compat: a bare contact_id acts as the sole student - but ONLY for single-seat orders.
    # On a MULTI-SEAT deal the students come from the enrollment picker; defaulting to the buyer
    # here would make the payment path (6.5) enroll the buyer and CLOBBER the picker's roster.
    # With no students on a multi-seat deal it falls through to the picker-defer below. (Tim Jul 18.)
    if not students and data.get("contact_id") and (not seats or int(seats) <= 1):
        students = [data["contact_id"].strip()]
        contact_names[data["contact_id"].strip()] = (data.get("contact_name") or "").strip()

    manager_fields = {k: data.get(k) for k in ("manager_email", "manager_first_name",
                      "manager_last_name", "manager_phone_number") if data.get(k)}

    # Enrollments belong on the ONBOARDING (Customer Management) deal — that is where the
    # enrollment picker and the Ready-to-Onboard notification live. The webhook usually
    # fires off the Mortgage deal, so without this the enrollment records hang off the
    # Mortgage card and never show on the onboarding deal (Tim Jul 17: "I don't see the
    # enrollments on the Customer Management deal"). Unless link_opportunity_id was passed
    # explicitly, re-point link_opp to the contact's Customer Management opp.
    if not (data.get("link_opportunity_id") or "").strip():
        _link_cid = (manager_id or (students[0] if students else None)
                     or ((opp.get("contactId") or (opp.get("contact") or {}).get("id")) if opp else None)
                     or (data.get("contact_id") or "").strip())
        if _link_cid:
            # GHL's opportunity SEARCH is eventually-consistent: a Customer Management opp
            # created seconds earlier may not be indexed yet, which would make us fall back
            # to the Mortgage deal and hang enrollments off the wrong card (Tim Jul 17:
            # "landing on the sales record instead of onboarding"). Retry a few times so the
            # freshly-created onboarding deal is found before we give up.
            _cm = None
            for _try in range(5):
                try:
                    _ls = requests.get(f"{XINNIX_GHL_BASE}/opportunities/search",
                                       headers={**XINNIX_GHL_HEADERS, "Authorization": f"Bearer {XINNIX_GHL_TOKEN}"},
                                       params={"location_id": XINNIX_LOCATION_ID, "contact_id": _link_cid}, timeout=20)
                    _cands = _ls.json().get("opportunities", []) if _ls.status_code == 200 else []
                    _cm = next((o for o in _cands if o.get("pipelineId") == XINNIX_CM_PIPELINE_ID), None)
                except Exception as _e:
                    _log_debug("xinnix", f"CM link_opp resolve attempt {_try} failed: {_e}")
                    _cands = []
                if _cm or dry_run:
                    break
                time.sleep(1.3)  # wait for the search index to catch up, then retry
            if _cm and _cm.get("id"):
                link_opp = _cm.get("id")
                _log_debug("xinnix", f"link_opp -> Customer Management opp {link_opp}")
            else:
                _log_debug("xinnix", f"CM opp not found for {_link_cid} after retries; enrollments will attach to {link_opp}")

    _log_debug("xinnix", f"create-program-enrollment: opp={opportunity_id} progs={programs} "
                         f"students={students} mgr={manager_id} seats={seats} dry={dry_run}")

    # Website/Stripe purchase: opp field empty but the order carries the product.
    # Resolve programs from the completed order and stamp the field so downstream works.
    if not programs:
        _cid = ((opp.get("contactId") or (opp.get("contact") or {}).get("id")) if opp else None) or (students[0] if students else None) or (data.get("contact_id") or "").strip()
        _op, _os = _xinnix_order_programs(_cid)
        if _op:
            programs = _op
            if not seats:
                seats = _os or 1
            if opportunity_id:
                _xinnix_stamp_opp_programs(opportunity_id, programs, seats)
            _log_debug("xinnix", f"filled programs from order for {_cid}: {programs} seats={seats}")
    # Partner-form fallback: the program lives on the "Partner Registration Program" CONTACT
    # field in an ALL-CAPS/dash format that does not match the deal's Program options, so map
    # it to the real option(s). This is why partner deals showed a blank program. (Tim Jul 18.)
    if not programs:
        _pcid = ((opp.get("contactId") or (opp.get("contact") or {}).get("id")) if opp else None) \
                or manager_id or (students[0] if students else None) or (data.get("contact_id") or "").strip()
        _pp = _xinnix_partner_program_from_contact(_pcid)
        if _pp:
            programs = _pp
            _log_debug("xinnix", f"filled programs from partner form for {_pcid}: {programs}")
    if not programs:
        return jsonify({"error": "no programs (empty on request and on the opportunity)"}), 400
    # Stamp the resolved Program(s) onto ALL THREE of the contact's enrollment-pipeline opps
    # (Mortgage Team + Customer Management + Contract & Invoicing) so every deal card shows it.
    if not dry_run:
        _stamp_cid = ((opp.get("contactId") or (opp.get("contact") or {}).get("id")) if opp else None) \
                     or (students[0] if students else None) or (data.get("contact_id") or "").strip()
        if _stamp_cid:
            _xinnix_stamp_contact_opps(_stamp_cid, programs, seats)
            # Also stamp the resolved program onto the CONTACT's "Enrolled Program" field. The
            # notification fires on a contact tag, where GHL can't resolve {{opportunity.*}}, so
            # the email reads {{contact.enrolled_program}} instead. Seat is always 1 (hardcoded in
            # the template). (Tim Jul 18.)
            if programs:
                # Seat rule: a salesperson order carries the real seat count on the opp (>1);
                # partner + website orders are always a single seat (buyer = the student). Keyed on
                # the opp seat count, not source, since the sales workflow may not pass one. (Tim Jul 18.)
                try:
                    _seat_display = int(seats) if (seats and int(seats) > 1) else 1
                except Exception:
                    _seat_display = 1
                # Resolve the contact's ATTACHED BUSINESS name so the Ready-to-Onboard email
                # shows the real business instead of a blank Company. The notification reads
                # {{contact.company_name}}, so mirror the linked Business object's name onto the
                # contact's Company field. (Casey Jul 28: "show the business they are attached to".)
                _biz_name = ""
                _cc = None
                try:
                    _cc = requests.get(f"{XINNIX_GHL_BASE}/contacts/{_stamp_cid}",
                        headers={**XINNIX_GHL_HEADERS, "Authorization": f"Bearer {XINNIX_GHL_TOKEN}"}, timeout=15)
                    _bid = ((_cc.json().get("contact") or {}).get("businessId") or "") if _cc.status_code == 200 else ""
                    if _bid:
                        _bb = requests.get(f"{XINNIX_GHL_BASE}/objects/business/records/{_bid}",
                            headers={**XINNIX_GHL_HEADERS, "Authorization": f"Bearer {XINNIX_GHL_TOKEN}"},
                            params={"locationId": XINNIX_LOCATION_ID}, timeout=15)
                        if _bb.status_code == 200:
                            _biz_name = (((_bb.json().get("record") or {}).get("properties") or {}).get("name") or "").strip()
                except Exception as _e:
                    _log_debug("xinnix", f"business-name resolve failed: {_e}")
                # Course start: mirror the opp's "Student Start Date" onto the contact so the
                # email's {{contact.program__course_start_date}} fills in. (Casey Jul 28: "the
                # start date is on the opportunity, right under the program name".)
                _start = ""
                try:
                    _opp_for_start = opp or (_xinnix_get_opportunity(opportunity_id or link_opp) if (opportunity_id or link_opp) else None)
                    for _c in ((_opp_for_start or {}).get("customFields") or []):
                        if _c.get("id") == "Djt6YNA5wPmftLuWD6ae":   # Student Start Date (DATE field)
                            # GHL date custom fields return epoch-millis under fieldValueDate,
                            # NOT fieldValue. Convert to YYYY-MM-DD for the contact stamp.
                            _sv = (_c.get("fieldValueDate") or _c.get("fieldValue")
                                   or _c.get("fieldValueString") or _c.get("value"))
                            if _sv not in (None, ""):
                                try:
                                    _start = datetime.utcfromtimestamp(int(_sv) / 1000).strftime("%Y-%m-%d")
                                except (ValueError, TypeError):
                                    _start = str(_sv)
                            break
                except Exception as _e:
                    _log_debug("xinnix", f"student-start-date resolve failed: {_e}")
                _put_body = {"customFields": [
                    {"id": "nx3cvF2rUrLrRA02NpC8", "field_value": ", ".join(programs)},   # Enrolled Program
                    {"id": "22YJLuAyOXuXKhlTuKGY", "field_value": str(_seat_display)},      # Enrolled Seats
                ]}
                if _start:
                    # Preferred Start Date (DATE field, id qNlU) is what the enrollment
                    # notification now reads, so mirror the opp Student Start Date there so
                    # rep/ESM deals show a full date like the web/partner forms do. Keep the
                    # legacy month field write during the transition so nothing goes blank.
                    _put_body["customFields"].append(
                        {"id": "qNlU1Q0zmwG00h7lX8SO", "field_value": _start})              # Preferred Start Date (DATE) - notification source
                    _put_body["customFields"].append(
                        {"id": "4LHILPGqgwMclcTPjUp8", "field_value": _start})              # legacy Course start date (transitional)
                if _biz_name:
                    _put_body["companyName"] = _biz_name                                    # Company = attached Business
                # Manager auto-stamp: when the purchasing contact is enrolling a DIFFERENT
                # student (a manager buying seats for someone else), populate the Manager
                # fields with the buyer so the Ready-to-Onboard shows who bought it. Only
                # fill when Manager 1 is blank, so a form-provided manager is never
                # overwritten. (Taylor Jul 30: Patti Hale bought for Daniel Wetmore but the
                # Manager field came through empty.)
                try:
                    _buyer = (_cc.json().get("contact") or {}) if (_cc is not None and _cc.status_code == 200) else {}
                    _buyer_is_student = _stamp_cid in (students or [])
                    _cur_mgr1 = ""
                    for _c in (_buyer.get("customFields") or []):
                        if _c.get("id") == "vJmUbMdMuTlGLycpKObe":                            # manager_first_name
                            _cur_mgr1 = (_c.get("value") or _c.get("fieldValue") or "")
                            break
                    if students and (not _buyer_is_student) and not _cur_mgr1:
                        for _fid, _val in (
                            ("vJmUbMdMuTlGLycpKObe", _buyer.get("firstName")),                # manager_first_name
                            ("sZPlYyWp20YBWxbAN9Mb", _buyer.get("lastName")),                 # manager_last_name
                            ("jzD9Ft1k2bl9VRDLF9mJ", _buyer.get("email")),                    # manager_email
                            ("aNYYAUR99Y76DFVcvvKC", _buyer.get("phone")),                    # manager_phone
                        ):
                            if _val:
                                _put_body["customFields"].append({"id": _fid, "field_value": _val})
                        _log_debug("xinnix", f"manager auto-stamped {_buyer.get('email')} on {_stamp_cid}")
                except Exception as _e:
                    _log_debug("xinnix", f"manager auto-stamp failed: {_e}")
                try:
                    requests.put(f"{XINNIX_GHL_BASE}/contacts/{_stamp_cid}",
                        headers={**XINNIX_GHL_HEADERS, "Authorization": f"Bearer {XINNIX_GHL_TOKEN}"},
                        json=_put_body, timeout=20)
                except Exception as _e:
                    _log_debug("xinnix", f"enrolled_program/seats/company contact stamp failed: {_e}")
    # Contract gate: tag the buyer xinnix-needs-contract ONLY when this deal needs a signed
    # agreement (a contract-trigger product, multi-seat, or a partner opp type). Taylor's
    # "Ready for Contract" email fires on THIS tag instead of on every order, so a single
    # self-serve B2C purchase never reaches her with a blank email. Runs before the multi-seat
    # defer so partner/bulk deals still get tagged. (Tim Jul 18.)
    _has_manager = False
    if not dry_run:
        _ct_cid = (manager_id or (students[0] if students else None)
                   or ((opp.get("contactId") or (opp.get("contact") or {}).get("id")) if opp else None)
                   or (data.get("contact_id") or "").strip())
        # A filled Manager means this is a partner/B2B agreement: the buyer is NOT a student,
        # the students come from the picker. An EMPTY manager means it's a single self-serve
        # order and the buyer IS the student, seats 1. (Tim Jul 18.)
        _mgr_cfs = _xinnix_manager_cfs_from_contact(_ct_cid) if _ct_cid else []
        _has_manager = any(c.get("id") == XINNIX_OPP_PRIMARY_MGR_FIELD for c in _mgr_cfs)
        # Stamp managers + course start onto all 3 deals NOW so they show even if we defer to
        # the picker below (before _xinnix_stamp_roster runs).
        if _mgr_cfs and _ct_cid:
            _xinnix_stamp_managers_on_deals(_ct_cid, _mgr_cfs)
        # Contract gate: tag xinnix-needs-contract when the deal needs a signed agreement, a
        # manager (partner/B2B), a contract-trigger product, multi-seat, or a partner opp type.
        # A single self-serve B2C order (no manager) never gets it, so Taylor never gets a
        # blank email.
        _pj = " ".join(programs).lower()
        _needs_contract = bool(
            _has_manager or (seats and seats > 1)
            or any(p in _pj for p in XINNIX_CONTRACT_PRODUCT_PATTERNS)
            or (opp is not None and _xinnix_opp_type(opp).strip().lower() in XINNIX_PARTNER_OPP_TYPES))
        if _needs_contract and _ct_cid:
            try:
                requests.post(f"{XINNIX_GHL_BASE}/contacts/{_ct_cid}/tags",
                    headers={**XINNIX_GHL_HEADERS, "Authorization": f"Bearer {XINNIX_GHL_TOKEN}"},
                    json={"tags": ["xinnix-needs-contract"]}, timeout=15)
                _log_debug("xinnix", f"tagged xinnix-needs-contract on {_ct_cid} (mgr={_has_manager} seats={seats})")
            except Exception as _e:
                _log_debug("xinnix", f"contract tag failed: {_e}")
    # Multi-seat deals are assigned person-by-person via the enrollment picker, not auto-created
    # here (prevents orphan seat placeholders alongside the picker's real assignments). Single-seat
    # deals auto-create. Passing explicit "students" in the request overrides the gate. (Tim Jul 16.)
    # Defer to the picker ONLY when it's multi-seat AND no students are known yet. If the opp
    # already has students associated (salesperson assigned them), enroll those - don't defer.
    # Single orders (buyer = the student) also fall through. (Tim Jul 18.)
    if seats > 1 and not students:
        return jsonify({"deferred": True, "seats": seats, "has_manager": _has_manager,
                        "programs_count": len(programs),
                        "reason": "multi-seat deal, no students assigned yet - use the picker"}), 200
    if not students and not seats:
        return jsonify({"error": "no student contacts and no seat count — nothing to enroll"}), 400

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out = []

    def _enroll(contact_id, prog, program_record_id, unidentified=False, seat_no=None):
        """Create one enrollment for one contact (or one unidentified seat) in one program."""
        cname = contact_names.get(contact_id, "")
        label = f"SEAT {seat_no}" if unidentified else cname
        item = {"program": prog, "contact_id": contact_id, "unidentified_seat": unidentified,
                "program_record_id": program_record_id}
        if not unidentified:
            existing = _xinnix_find_existing_enrollment(contact_id, prog)
            if existing:
                item["skipped"] = f"enrollment already exists ({existing})"
                return item
        if dry_run:
            item["would_create"] = True
            return item
        props = {"enrollment_date": today, "program_name": prog, "source": source,
                 "enrollment_id": (f"{label} {prog}".strip())[:250]}
        props.update(manager_fields)
        # Student / Company / Seats on the record so the "Ready to Onboard" notification
        # merges them (were blank: enrollment obj had no field, Casey Jul 17).
        meta = {} if unidentified else _xinnix_contact_meta(contact_id)
        company = meta.get("company") or ""
        if not company and manager_id:
            company = _xinnix_contact_meta(manager_id).get("company") or ""
        if not unidentified:
            props["student_name"] = cname or meta.get("name") or ""
            if meta.get("email"):
                props["student_email"] = meta["email"]
        if company:
            props["company_legal_name"] = company
        props["seats"] = seats if seats else 1
        st, resp = _xinnix_create_record(XINNIX_ENROLLMENT_OBJKEY, props)
        if st not in (200, 201):
            item["error"] = f"enrollment create failed ({st}): {str(resp)[:160]}"
            return item
        enr_id = (resp.get("record") or resp).get("id")
        item["enrollment_id"] = enr_id
        item["links"] = {}
        if contact_id:
            s, _ = _xinnix_create_relation(XINNIX_CONTACT_ENROLLMENT_ASSOC, contact_id, enr_id)
            item["links"]["contact"] = s
        if program_record_id:
            s, _ = _xinnix_create_relation(XINNIX_ENROLLMENT_PROGRAM_ASSOC, enr_id, program_record_id)
            item["links"]["program"] = s
            if contact_id:
                s, _ = _xinnix_create_relation(XINNIX_CONTACT_PROGRAM_ASSOC, contact_id, program_record_id)
                item["links"]["contact_program"] = s
            # link the manager to the program too, for roll-up dashboards
            if manager_id and manager_id != contact_id:
                _xinnix_create_relation(XINNIX_CONTACT_PROGRAM_ASSOC, manager_id, program_record_id)
        if link_opp:
            s, _ = _xinnix_create_relation(XINNIX_ENROLLMENT_OPP_ASSOC, enr_id, link_opp)
            item["links"]["opportunity"] = s
            # also link that opportunity directly to the program (harmless if it already exists)
            if program_record_id:
                _xinnix_create_relation(XINNIX_OPP_PROGRAM_ASSOC, program_record_id, link_opp)
        return item

    for prog in programs:
        program_record_id = _xinnix_resolve_program(prog)
        if students:
            for cid in students:
                r = _enroll(cid, prog, program_record_id)
                if not program_record_id:
                    r["warning"] = "program not in map — enrollment created but not linked to a Program record"
                out.append(r)
        else:
            # No student resolved on a single-seat order = a premature/duplicate fire (the real
            # enrollment arrives on the fire that carries the buyer as student). Multi-seat already
            # deferred to the picker above, so this branch is only ever reached single-seat with no
            # student yet — never drop a phantom placeholder here (it just becomes a blank orphan the
            # monitor has to sweep). (Tim Jul 18.)
            _log_debug("xinnix", f"no student for {prog} (seats={seats}) yet — skip phantom placeholder")
            continue

    created = [o for o in out if o.get("enrollment_id")]
    # Single-seat / explicit-student enrollment completes here (multi-seat deferred above to
    # the picker). Stamp the roster + fire the notification on the opp the enrollments hang off.
    roster = {}
    if not dry_run and created and students:
        roster = _xinnix_stamp_roster(link_opp, student_cids=students,
                                      manager_cid=manager_id or None, seats=seats, fire=True)
    return jsonify({"success": True, "dry_run": dry_run,
                    "read_opp": opportunity_id, "attached_to_opp": link_opp,
                    "programs_count": len(programs), "students_count": len(students),
                    "seats": seats, "created": len(created), "roster": roster,
                    "skipped_contacts": skipped_contacts, "results": out}), 200


def _xinnix_contact_enrollments(cid):
    """Return [{enrollment_id, program_name, relation_id}] for a contact's enrollments.
    Uses GET /associations/relations/{recordId} (no associationId param), then reads each
    linked enrollment record for its program_name."""
    headers = {**XINNIX_GHL_HEADERS, "Authorization": f"Bearer {XINNIX_GHL_TOKEN}"}
    try:
        r = requests.get(f"{XINNIX_GHL_BASE}/associations/relations/{cid}?locationId={XINNIX_LOCATION_ID}",
                         headers=headers, timeout=20)
        if r.status_code != 200:
            return []
        rels = r.json().get("relations", [])
    except Exception:
        return []
    out = []
    for rel in rels:
        if rel.get("secondObjectKey") != XINNIX_ENROLLMENT_OBJKEY:
            continue
        enr_id = rel.get("secondRecordId")
        pname = None
        try:
            er = requests.get(f"{XINNIX_GHL_BASE}/objects/{XINNIX_ENROLLMENT_OBJKEY}/records/{enr_id}"
                              f"?locationId={XINNIX_LOCATION_ID}", headers=headers, timeout=15)
            if er.status_code == 200:
                pname = ((er.json().get("record") or {}).get("properties") or {}).get("program_name")
        except Exception:
            pass
        out.append({"enrollment_id": enr_id, "program_name": pname, "relation_id": rel.get("id")})
    return out


def _xinnix_create_one_enrollment(contact_id, prog, opp_id, contact_name="", source="Picker"):
    """Create one enrollment (contact in program) + link contact/program/opportunity."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    program_record_id = _xinnix_resolve_program(prog)
    props = {"enrollment_date": today, "program_name": prog, "source": source,
             "enrollment_id": (f"{contact_name} {prog}".strip())[:250]}
    # Student / Company so the "Ready to Onboard" notification can merge them.
    meta = _xinnix_contact_meta(contact_id)
    props["student_name"] = contact_name or meta.get("name") or ""
    if meta.get("email"):
        props["student_email"] = meta["email"]
    if meta.get("company"):
        props["company_legal_name"] = meta["company"]
    props["seats"] = 1
    st, resp = _xinnix_create_record(XINNIX_ENROLLMENT_OBJKEY, props)
    if st not in (200, 201):
        return {"error": f"create failed ({st})"}
    enr_id = (resp.get("record") or resp).get("id")
    _xinnix_create_relation(XINNIX_CONTACT_ENROLLMENT_ASSOC, contact_id, enr_id)
    if program_record_id:
        _xinnix_create_relation(XINNIX_ENROLLMENT_PROGRAM_ASSOC, enr_id, program_record_id)
        _xinnix_create_relation(XINNIX_CONTACT_PROGRAM_ASSOC, contact_id, program_record_id)
    if opp_id:
        _xinnix_create_relation(XINNIX_ENROLLMENT_OPP_ASSOC, enr_id, opp_id)
        if program_record_id:
            _xinnix_create_relation(XINNIX_OPP_PROGRAM_ASSOC, program_record_id, opp_id)
    return {"enrollment_id": enr_id}


def _xinnix_delete_enrollment(enr_id):
    headers = {**XINNIX_GHL_HEADERS, "Authorization": f"Bearer {XINNIX_GHL_TOKEN}"}
    # NOTE: this endpoint rejects a locationId query param (422)
    r = requests.delete(f"{XINNIX_GHL_BASE}/objects/{XINNIX_ENROLLMENT_OBJKEY}/records/{enr_id}",
                        headers=headers, timeout=20)
    return r.status_code


XINNIX_PRODUCT_CATALOG = {
    '90 MIN (Virtual)': {"productId": "6904c9be5b70df84893d6005", "priceId": "6904c9be5b70df5b2d3d600a", "amount": 5500},
    'ADVANTAGE': {"productId": "6904ca11471e6ece0f6f2809", "priceId": "6904ca11471e6e182a6f280e", "amount": 1799},
    'ASCEND': {"productId": "6904ca3d019fb018bc38f0bf", "priceId": "6a56f75552340155aa418cf6", "amount": 1799},
    'Additional Coaching Hours': {"productId": "6a56f773b76fa21973c7dd37", "priceId": "6a56f773824b1a36985577e7", "amount": 300},
    'BUSINESS DEVELOPMENT WORKSHOP': {"productId": "6904ca6bc319ff1989268c3a", "priceId": "6a56f75fb76fa2642dc7dc64", "amount": 1699},
    'Blades Inner Circle': {"productId": "6a56f76b2f4e256eddfdc3b0", "priceId": "6a56f76bb76fa22153c7dce6", "amount": 99},
    'Breakthrough Academy (Guild Mortgage)': {"productId": "697965a3b10e0b376f045130", "priceId": "697965a3b10e0b03e2045135", "amount": 1597},
    'Custom Content Design': {"productId": "6a56f77352340146bf418ece", "priceId": "6a56f77403821e2016f61792", "amount": 300},
    'DRIVE Test': {"productId": "6a56f768b76fa2d070c7dcbe", "priceId": "6a56f769824b1a242f55775d", "amount": 225},  # 2 price options (entry default)
    'EDGE': {"productId": "6904ca9559c9632266f7bb39", "priceId": "6a56f75703821e05fcf615a0", "amount": 1799},
    'ELEVATEx': {"productId": "6a56f76603821e3b25f61695", "priceId": "6a56f7665234011fb5418e28", "amount": 997},
    'ELITE': {"productId": "6904cab8b774805937596e47", "priceId": "6a56f7582f4e25cdbdfdc287", "amount": 2499},
    'ENERGY': {"productId": "6904cb3f89a1cb413d88f782", "priceId": "6a56f75a5234018326418d70", "amount": 199},  # 3 price options (entry default)
    'ENGAGEx (Virtual)': {"productId": "6904cbb52c718a174a1b83f3", "priceId": "6a56f7662f4e2592f0fdc371", "amount": 999},
    'EXPLOREx': {"productId": "6a56f76cb76fa2697fc7dceb", "priceId": "6a56f76c2f4e256dcefdc3bd", "amount": 10000},  # 4 price options (entry default)
    'Executive Coaching / Consulting (Casey)': {"productId": "6a56f7742f4e25f07dfdc42f", "priceId": "6a56f7745234013b83418edc", "amount": 500},
    'Extended DISC': {"productId": "6a56f7672f4e25f4d2fdc381", "priceId": "6a56f7672f4e2567fffdc389", "amount": 150},  # 2 price options (entry default)
    'Extended DISC + Consult': {"productId": "6a56f76852340131ad418e49", "priceId": "6a56f7682f4e250c41fdc394", "amount": 200},  # 2 price options (entry default)
    'FHA MASTERCLASS': {"productId": "6904cbd410b2db0e41c2ec1a", "priceId": "6a56f75e03821e2158f6161f", "amount": 499},
    'IGNITE': {"productId": "6904cbf5ad915e09540b04c0", "priceId": "6a56f75703821e018df615ab", "amount": 1999},
    'KEYNOTE (Virtual)': {"productId": "6904cc18782b3a7ddb1a3eca", "priceId": "6904cc18782b3a00f21a3ecf", "amount": 5500},
    'LEAD CONVERSION': {"productId": "6904ccc06deae670df0422ab", "priceId": "6a56f75b2f4e252a9efdc2d4", "amount": 399},
    'LEADERSHIP LESSONS': {"productId": "6904ccdfb774804ae459a3eb", "priceId": "6904ccdfb77480685259a3f0", "amount": 599},
    'LEADERSHIP Series': {"productId": "6a56f766b76fa233e4c7dcaa", "priceId": "6a56f766523401381c418e1d", "amount": 2999},
    'LEADx': {"productId": "6a56f761b76fa28154c7dc8a", "priceId": "6a56f7622f4e2592a6fdc342", "amount": 3997},
    'LEADx (Virtual)': {"productId": "6904cd0af143b2e0c13a65dc", "priceId": "6904cd0af143b2782d3a65e1", "amount": 3500},
    'LINKEDIN FOR LOAN OFFICERS': {"productId": "6904cd2989a1cbbc4389246e", "priceId": "6a56f75cb76fa2acf5c7dc32", "amount": 199},
    'MANAGEx: Build Capability': {"productId": "69f25b3d40511242b24ca63c", "priceId": "6a56f7612f4e251eb6fdc33a", "amount": 1997},
    'Mortgage Mastery Blueprint': {"productId": "6a42984cf88f4894ffb030f2", "priceId": "6a42984cbcb9d877c90fa0f3", "amount": 1597},  # 3 price options (entry default)
    # ORIGINATOR family, keyed to the clean opp/enrollment "Program / Course" values so each
    # phase combo maps to the correct product PRICE variant (Tim + Kevin confirmed Jul 16).
    'ORIGINATOR™ (Ground School)': {"productId": "6903ed271e88f05a8941c556", "priceId": "6a56f7505234012ddf418c8c", "amount": 1799},
    'ORIGINATOR™ (Ground School & Flight School)': {"productId": "6903ed271e88f05a8941c556", "priceId": "6a56f7502f4e2526affdc205", "amount": 2999},
    'ORIGINATOR™ (Ground School, Flight School & Officer School)': {"productId": "6903ed271e88f05a8941c556", "priceId": "6a56f7512f4e25eb75fdc20d", "amount": 3999},
    'ORIGINATOR™ Direct': {"productId": "69933a1781abab6713529c9c", "priceId": "6a56f7535234016352418cc2", "amount": 2999},
    'ORIGINATOR™ Assist': {"productId": "697fb0f79a99ed1e479c9fe3", "priceId": "6a56f754824b1ac88d5575f1", "amount": 2999},
    # legacy bare product-name keys (order/payment webhooks that read raw product names)
    'ORIGINATOR ASSIST': {"productId": "697fb0f79a99ed1e479c9fe3", "priceId": "6a56f754824b1ac88d5575f1", "amount": 2999},   # Phase I & II
    'ORIGINATOR DIRECT': {"productId": "69933a1781abab6713529c9c", "priceId": "6a56f7535234016352418cc2", "amount": 2999},   # Phase I & II
    'ORIGINATOR PLUS': {"productId": "6a56f76f5234012d06418e99", "priceId": "6a56f7702f4e25c7befdc3e7", "amount": 10000},  # bulk (min 5 starts)
    'ORIGINATOR': {"productId": "6903ed271e88f05a8941c556", "priceId": "6a56f7512f4e25eb75fdc20d", "amount": 3999},  # bare = full package
    'OWN IT Foundations': {"productId": "6a56f767824b1aee0655774c", "priceId": "6a56f7672f4e2547b1fdc37f", "amount": 497},
    'OWN IT Leadership': {"productId": "69a5e9e1e4eaa17a04e839a2", "priceId": "69a5e9e2e4eaa135e0e839b1", "amount": 997},  # 2 price options (entry default)
    'On-Site Program Add-On': {"productId": "6a56f76d5234017c8a418e8e", "priceId": "6a56f76d03821e1fecf6172c", "amount": 2500},
    'P&L MASTERY (Virtual)': {"productId": "6904cd78e44580560108789a", "priceId": "6a56f7635234015498418de3", "amount": 1899},
    'POWER (COMMUNICATION & PARTNERSHIPS)': {"productId": "6904cd93719c83b39a1e8229", "priceId": "6a56f756b76fa2025ac7dc12", "amount": 399},
    'POWERFUL PRESENTATIONS': {"productId": "6904cdb3f72f5f68c1d527d3", "priceId": "6a56f75d523401f1a4418d9c", "amount": 199},
    'RAPID COACHING': {"productId": "6904cdde7e8ace2728738ce3", "priceId": "6a56f7602f4e25121cfdc32c", "amount": 999},
    'RECRUITING EXPRESS (Virtual)': {"productId": "6904cdfc770d7a6d80dcf848", "priceId": "6904cdfc770d7ac330dcf84d", "amount": 399},
    'RECRUITING WORKSHOP': {"productId": "6904ce1f5daf7281327e097c", "priceId": "6a56f75f2f4e2570ddfdc324", "amount": 1699},
    'SOAR': {"productId": "6904ce3db77480410b59c289", "priceId": "6a56f7555234010c4d418cd9", "amount": 1799},
    'SPEAKx Keynote / X Talk (In Person)': {"productId": "6a56f771824b1a8dd75577ce", "priceId": "6a56f7712f4e25227dfdc41f", "amount": 14500},
    'SPEAKx Virtual Workshop (up to 60 min)': {"productId": "6a56f772b76fa209f5c7dd32", "priceId": "6a56f773523401258a418ec9", "amount": 4500},
    'SPEAKx Workshop (90 min to Half Day)': {"productId": "6a56f7722f4e255cd2fdc421", "priceId": "6a56f77203821e8dc2f61784", "amount": 6500},
    'SPEAKx Workshop (Full Day)': {"productId": "6a56f772824b1a27ae5577d9", "priceId": "6a56f7725234016c53418ec1", "amount": 9500},
    'SPQ + Consult': {"productId": "6a56f76ab76fa2dcd0c7dcd2", "priceId": "6a56f76a824b1a2ff5557779", "amount": 350},  # 2 price options (entry default)
    'SPQ Assessment': {"productId": "6a56f76903821e2e06f616f7", "priceId": "6a56f7695234013a9e418e63", "amount": 299},  # 2 price options (entry default)
    'STRATEGIC PARTNER (Per Seat)': {"productId": "6a56f76e2f4e259786fdc3c5", "priceId": "6a56f76e824b1a415d5577a6", "amount": 1500},  # 3 price options (entry default)
    'Secret Shopper (per person) + Consult': {"productId": "6a56f76a824b1a4f27557783", "priceId": "6a56f76b03821ef2b9f61702", "amount": 599},  # 2 price options (entry default)
    'THE COMPLETE LOAN APPLICATION': {"productId": "6904ce6f5b70df06813dd15f", "priceId": "6a56f75b03821e507df615ff", "amount": 199},
    'The Breakthrough Academy': {"productId": "69dff92e9f1c7117aa59c78d", "priceId": "6a56f76403821e9d20f61675", "amount": 1597},  # 2 price options (entry default)
    'The Breakthrough Academy (Paul)': {"productId": "69de78b3cfa84c84aa09341d", "priceId": "69de78b3cfa84c10a0093422", "amount": 99},
    'The Legacy Circle': {"productId": "6a56f76c2f4e250b08fdc3b2", "priceId": "6a56f76c03821e899ff6171b", "amount": 25000},
    'The Performance Accelerator': {"productId": "697a5f709a99ed914fd520be", "priceId": "697a5f709a99ed530fd520c3", "amount": 3903},  # 2 price options (entry default)
    'XINNIX Care': {"productId": "6a56f76f03821e42d2f6174b", "priceId": "6a56f76f03821eda74f61753", "amount": 25000},
    'XINNIX Unlimited': {"productId": "6a56f76fb76fa20dc3c7dd0a", "priceId": "6a56f76fb76fa215bac7dd18", "amount": 1000},
    'XINNIXSpeaks HALF-DAY (Virtual)': {"productId": "6904ce8df143b210493a8687", "priceId": "6904ce8df143b2231a3a868c", "amount": 7500},
    'XTALKS (Virtual)': {"productId": "6904ceb560b036a22a88cb29", "priceId": "6904ceb560b036808288cb2e", "amount": 3500},
}


XINNIX_PRICE_TO_PROGRAM = {
    "6a56f75552340155aa418cf6": "ASCEND™",
    "6a56f75fb76fa2642dc7dc64": "Business Development Workshop",
    "6a56f75703821e05fcf615a0": "EDGE™",
    "6a56f7665234011fb5418e28": "ELEVATEx",
    "6a56f7582f4e25cdbdfdc287": "ELITE™",
    "6a56f75e03821e2158f6161f": "FHA Master Class™",
    "6a56f75703821e018df615ab": "IGNITE™",
    "6a56f766523401381c418e1d": "LEADERSHIP Series",
    "6a56f7622f4e2592a6fdc342": "LEADx",
    "6904cd0af143b2782d3a65e1": "LEADx",
    "6a56f75b2f4e252a9efdc2d4": "Lead Conversion™",
    "6a56f7612f4e251eb6fdc33a": "MANAGEx",
    "6a42984cbcb9d877c90fa0f3": "Mortgage Mastery Blueprint",
    "6a42984cb9259ef6da3e252e": "Mortgage Mastery Blueprint",
    "6a429a76b9259e04013e84ea": "Mortgage Mastery Blueprint",
    "6a56f7502f4e25d47ffdc1fd": "ORIGINATOR™ (Ground School & Flight School)",
    "6a56f7502f4e2526affdc205": "ORIGINATOR™ (Ground School & Flight School)",
    "6a56f7525234015a50418cba": "ORIGINATOR™ (Ground School)",
    "6a56f754b76fa24e3ec7dbf5": "ORIGINATOR™ (Ground School)",
    "6a56f7505234012ddf418c8c": "ORIGINATOR™ (Ground School)",
    "6a56f7702f4e25c7befdc3e7": "ORIGINATOR™ (Ground School, Flight School & Officer School)",
    "6a56f7702f4e25b6f8fdc3f2": "ORIGINATOR™ (Ground School, Flight School & Officer School)",
    "6a56f7705234010cd6418ead": "ORIGINATOR™ (Ground School, Flight School & Officer School)",
    "6a56f7702f4e253d63fdc3fa": "ORIGINATOR™ (Ground School, Flight School & Officer School)",
    "6a56f7712f4e254454fdc402": "ORIGINATOR™ (Ground School, Flight School & Officer School)",
    "6a56f77103821e8686f61776": "ORIGINATOR™ (Ground School, Flight School & Officer School)",
    "6a56f771824b1a45d15577cc": "ORIGINATOR™ (Ground School, Flight School & Officer School)",
    "6a56f7505234014b93418c94": "ORIGINATOR™ (Ground School, Flight School & Officer School)",
    "6a56f7512f4e25eb75fdc20d": "ORIGINATOR™ (Ground School, Flight School & Officer School)",
    "6a56f754824b1a208f5575dd": "ORIGINATOR™ Assist",
    "6a56f754824b1ac88d5575f1": "ORIGINATOR™ Assist",
    "6a56f753b76fa2d67fc7dbd2": "ORIGINATOR™ Direct",
    "6a56f7535234016352418cc2": "ORIGINATOR™ Direct",
    "69a5e9e2e4eaa135e0e839b1": "OWN IT Leadership",
    "69a5ea57d04dea0b12151c3a": "OWN IT Leadership",
    "6a56f756b76fa2025ac7dc12": "POWER",
    "6a56f75d523401f1a4418d9c": "Powerful Presentations™",
    "6a56f75f2f4e2570ddfdc324": "Recruiting Workshop",
    "6a56f7555234010c4d418cd9": "SOAR™",
    "6a5851022f4e2532670aaad7": "The Breakthrough Academy",
    "6a56f76403821e9d20f61675": "The Breakthrough Academy",
    "6a56f7655234013fed418e06": "The Breakthrough Academy",
    "69de78b3cfa84c10a0093422": "The Breakthrough Academy",
    "6a56f75b03821e507df615ff": "The Complete Loan Application™",
}


XINNIX_CLEAN_PROGRAMS = [
    "ASCEND™", "Business Development Workshop", "EDGE™", "ELITE™", "FHA Master Class™",
    "IGNITE™", "Lead Conversion™", "LinkedIn for LOs™",
    "ORIGINATOR™ (Ground School & Flight School)", "ORIGINATOR™ (Ground School)",
    "ORIGINATOR™ (Ground School, Flight School & Officer School)", "ORIGINATOR™ Assist",
    "ORIGINATOR™ Direct", "POWER", "Powerful Presentations™", "Recruiting Workshop",
    "SOAR™", "The Complete Loan Application™", "OWN IT Leadership", "LEADx",
    "Mortgage Mastery Blueprint", "MANAGEx", "ELEVATEx", "LEADERSHIP Series", "The Breakthrough Academy",
    "Reverse Mortgage Bundle",
]


def _xinnix_program_from_line(price_id, product_name):
    """Resolve a purchased line to a clean program: exact price-ID map first
    (handles Originator phase variants), then product-NAME match against the
    clean program list (handles multi-price products like EDGE, where any price
    resolves to the same program)."""
    if price_id and price_id in XINNIX_PRICE_TO_PROGRAM:
        return XINNIX_PRICE_TO_PROGRAM[price_id]
    tn = re.sub(r"[^a-z0-9]", "", (product_name or "").lower())
    if not tn:
        return None
    best, blen = None, 0
    for cp in XINNIX_CLEAN_PROGRAMS:
        core = re.sub(r"[^a-z0-9]", "", re.sub(r"\(.*?\)", "", cp).lower())
        if core and (tn.startswith(core) or core in tn or tn in core) and len(core) > blen:
            best, blen = cp, len(core)
    if best:
        return best
    # Fallback 1: match the store product name against the canonical program-map
    # names, whose store SKUs can differ from the short clean name (e.g. product
    # "LINKEDIN FOR LOAN OFFICERS ..." vs clean name "LinkedIn for LOs"). Longest
    # normalized match wins so "ORIGINATOR DIRECT" beats "ORIGINATOR".
    tnorm = _xinnix_norm_program(product_name)
    for k in sorted(XINNIX_PROGRAM_MAP, key=len, reverse=True):
        nk = _xinnix_norm_program(k)
        if nk and (tnorm.startswith(nk) or nk in tnorm):
            return k
    # Fallback 2: never hard-fail a real purchase. Use the base product name
    # (drop any " - descriptor" suffix and parentheticals) so an enrollment is
    # still created and the pipeline continues; naming can be cleaned up after.
    base = re.split(r"\s+[-–—]\s+", (product_name or "").strip())[0].strip()
    base = re.sub(r"\s*\(.*?\)\s*", "", base).strip()
    return base or None


def _xinnix_order_programs(contact_id):
    """Resolve a contact's PAID purchases to clean Program(s)/Products values.
    Covers BOTH website/store orders AND invoice payments (sales-rep / direct).
    Returns (programs list, total qty/seats)."""
    if not contact_id:
        return [], 0
    headers = {**XINNIX_GHL_HEADERS, "Authorization": f"Bearer {XINNIX_GHL_TOKEN}"}
    progs, seats = [], 0

    def _add(price_id, name, qty):
        nonlocal seats
        seats += qty
        prog = _xinnix_program_from_line(price_id, name)
        if prog and prog not in progs:
            progs.append(prog)

    # A. website / store orders
    try:
        r = requests.get(f"{XINNIX_GHL_BASE}/payments/orders",
                         params={"altId": XINNIX_LOCATION_ID, "altType": "location",
                                 "contactId": contact_id, "limit": 20}, headers=headers, timeout=20)
        for o in ((r.json().get("data") or []) if r.status_code == 200 else []):
            if (o.get("status") or "").lower() not in ("completed", "paid", "success", "succeeded"):
                continue
            # the order LIST omits line items; fetch the order detail to get them
            items = o.get("items") or o.get("lineItems") or []
            if not items:
                oid = o.get("_id") or o.get("id")
                dr = requests.get(f"{XINNIX_GHL_BASE}/payments/orders/{oid}",
                                  params={"altId": XINNIX_LOCATION_ID, "altType": "location"},
                                  headers=headers, timeout=20)
                od = (dr.json().get("order") or dr.json()) if dr.status_code == 200 else {}
                items = od.get("items") or od.get("lineItems") or []
            for li in items:
                price = li.get("price") or {}
                _add(price.get("_id") or price.get("id") or li.get("priceId"),
                     li.get("name") or li.get("productName"),
                     int(li.get("qty") or li.get("quantity") or 1))
    except Exception as _e:
        _log_debug("xinnix", f"order read failed: {_e}")

    # B. invoice payments (sales-rep / direct) -> read the paid invoice's line items
    try:
        r = requests.get(f"{XINNIX_GHL_BASE}/payments/transactions",
                         params={"altId": XINNIX_LOCATION_ID, "altType": "location",
                                 "contactId": contact_id, "limit": 20}, headers=headers, timeout=20)
        seen_inv = set()
        for t in ((r.json().get("data") or []) if r.status_code == 200 else []):
            st = (t.get("status") or t.get("paymentStatus") or "").lower()
            if st not in ("succeeded", "success", "paid", "completed"):
                continue
            if (t.get("entityType") or "").lower() != "invoice":
                continue
            inv_id = t.get("entityId")
            if not inv_id or inv_id in seen_inv:
                continue
            seen_inv.add(inv_id)
            ir = requests.get(f"{XINNIX_GHL_BASE}/invoices/{inv_id}",
                              params={"altId": XINNIX_LOCATION_ID, "altType": "location"},
                              headers=headers, timeout=20)
            inv = (ir.json().get("invoice") or ir.json()) if ir.status_code == 200 else {}
            for li in (inv.get("invoiceItems") or inv.get("items") or []):
                price = li.get("price") or {}
                _add(li.get("priceId") or price.get("_id") or li.get("entityId"),
                     li.get("name") or li.get("productName"),
                     int(li.get("qty") or li.get("quantity") or 1))
    except Exception as _e:
        _log_debug("xinnix", f"invoice read failed: {_e}")

    return progs, seats


def _xinnix_stamp_opp_programs(opp_id, programs, seats=0):
    """Write resolved programs (+ seats) onto the opp's Program(s)/Products field
    so the picker, workflow 8.1, and reporting all see them."""
    headers = {**XINNIX_GHL_HEADERS, "Authorization": f"Bearer {XINNIX_GHL_TOKEN}"}
    cfs = [{"id": XINNIX_OPP_PROGRAMS_FIELD, "field_value": programs}]
    if seats:
        cfs.append({"id": XINNIX_OPP_SEATS_FIELD, "field_value": int(seats)})
    try:
        requests.put(f"{XINNIX_GHL_BASE}/opportunities/{opp_id}", headers=headers,
                     json={"customFields": cfs}, timeout=20)
    except Exception as _e:
        _log_debug("xinnix", f"stamp opp programs failed: {_e}")


def _xinnix_stamp_contact_opps(contact_id, programs, seats=0):
    """Stamp the resolved Program(s)/Products (+ seats) onto EVERY one of the contact's
    opps in the three enrollment pipelines (Mortgage Team, Customer Management, and
    Contract & Invoicing), so all three deal cards show what they bought — not just the
    one that fired the webhook. (Tim Jul 17.)"""
    if not contact_id or not programs:
        return []
    headers = {**XINNIX_GHL_HEADERS, "Authorization": f"Bearer {XINNIX_GHL_TOKEN}"}
    try:
        r = requests.get(f"{XINNIX_GHL_BASE}/opportunities/search", headers=headers,
                         params={"location_id": XINNIX_LOCATION_ID, "contact_id": contact_id}, timeout=20)
        opps = r.json().get("opportunities", []) if r.status_code == 200 else []
    except Exception as _e:
        _log_debug("xinnix", f"stamp-all opp search failed: {_e}")
        return []
    # Shared deal fields to propagate onto all 3 cards (so the notifications show them):
    #  - Company Name kept in sync with the CONTACT's companyName (Tim Jul 17)
    #  - Enrollment Type + Deal Value copied from whichever opp already carries them
    company, contact_addr = None, None
    try:
        cr = requests.get(f"{XINNIX_GHL_BASE}/contacts/{contact_id}", headers=headers, timeout=20)
        _c = (cr.json().get("contact") or {}) if cr.status_code == 200 else {}
        company = _c.get("companyName")
        contact_addr = ", ".join([p for p in (_c.get("address1"), _c.get("city"),
                                              _c.get("state"), _c.get("postalCode")) if p]) or None
    except Exception:
        company = None
    enroll_type, deal_value = None, None
    for o in opps:
        if o.get("pipelineId") not in XINNIX_ENROLL_PIPELINES:
            continue
        for c in (o.get("customFields") or []):
            if c.get("id") == XINNIX_OPP_ENROLLTYPE_FIELD and not enroll_type:
                enroll_type = c.get("fieldValueString") or c.get("fieldValue")
            if c.get("id") == XINNIX_OPP_TOTALINV_FIELD and not deal_value:
                deal_value = c.get("fieldValueString") or c.get("fieldValue")
        if not deal_value and o.get("monetaryValue"):
            deal_value = o.get("monetaryValue")
    # Enrollment type: if no opp carries it, infer from a completed store order
    # (self-serve online purchase = B2C Shopping Cart). Rep/invoice deals leave blank.
    if not enroll_type:
        try:
            orr = requests.get(f"{XINNIX_GHL_BASE}/payments/orders", headers=headers,
                               params={"altId": XINNIX_LOCATION_ID, "altType": "location",
                                       "contactId": contact_id, "limit": 5}, timeout=15)
            if orr.status_code == 200 and any(
                    (o.get("status") or "").lower() in ("completed", "paid", "success", "succeeded")
                    for o in (orr.json().get("data") or [])):
                enroll_type = "B2C Shopping Cart"
        except Exception:
            pass
    cfs = [{"id": XINNIX_OPP_PROGRAMS_FIELD, "field_value": programs}]
    # a single enrollment is always at least 1 seat — never leave it blank
    cfs.append({"id": XINNIX_OPP_SEATS_FIELD, "field_value": int(seats or 1)})
    if company:
        cfs.append({"id": XINNIX_OPP_COMPANY_FIELD, "field_value": company})
        cfs.append({"id": "AisxzgZFufVhHxXud0vd", "field_value": company})  # Company Legal Name (fallback = company)
    if contact_addr:
        cfs.append({"id": "LLVpjSwaoWUhGXq7NR5v", "field_value": contact_addr})  # Company Address (from contact)
    cfs.append({"id": XINNIX_OPP_ALLOTMENT_FIELD, "field_value": int(seats or 1)})  # Seat Allotment
    if enroll_type:
        cfs.append({"id": XINNIX_OPP_ENROLLTYPE_FIELD, "field_value": enroll_type})
    if deal_value:
        cfs.append({"id": XINNIX_OPP_TOTALINV_FIELD, "field_value": deal_value})
    stamped = []
    for o in opps:
        if o.get("pipelineId") not in XINNIX_ENROLL_PIPELINES:
            continue
        # MERGE the Programs field so each card shows the FULL set the contact has bought —
        # union the programs already on the deal with this purchase's programs, never dropping
        # what was there. A contact can hold several distinct programs (EDGE / Ground School /
        # O+); merging shows them all instead of clobbering or skipping. (Tim Jul 18.)
        existing = []
        for c in (o.get("customFields") or []):
            if c.get("id") == XINNIX_OPP_PROGRAMS_FIELD:
                ev = c.get("fieldValueArray") or c.get("fieldValueString")
                existing = ev if isinstance(ev, list) else _xinnix_split_programs(ev)
        merged, seen = [], set()
        for p in list(existing) + list(programs):
            k = (p or "").strip().upper()
            if k and k not in seen:
                seen.add(k); merged.append(p)
        if existing:
            # Established deal: only refresh the Programs union — leave its seats/company/value
            # alone so we never corrupt a separate prior deal's counts.
            put_cfs = [{"id": XINNIX_OPP_PROGRAMS_FIELD, "field_value": merged}]
        else:
            # Fresh deal: set the full field set, with programs = this purchase.
            put_cfs = [c for c in cfs if c.get("id") != XINNIX_OPP_PROGRAMS_FIELD]
            put_cfs.append({"id": XINNIX_OPP_PROGRAMS_FIELD, "field_value": merged})
        try:
            requests.put(f"{XINNIX_GHL_BASE}/opportunities/{o.get('id')}", headers=headers,
                         json={"customFields": put_cfs}, timeout=20)
            stamped.append(o.get("id"))
        except Exception as _e:
            _log_debug("xinnix", f"stamp-all put failed for {o.get('id')}: {_e}")
    _log_debug("xinnix", f"stamped programs on {len(stamped)} opps for contact {contact_id}")
    return stamped


XINNIX_NOTIFY_TO = [e.strip() for e in os.environ.get("XINNIX_NOTIFY_TO", "tim@atj.digital").split(",") if e.strip()]


XINNIX_SMTP_HOST = os.environ.get("XINNIX_SMTP_HOST", "")


XINNIX_SMTP_PORT = int(os.environ.get("XINNIX_SMTP_PORT", "587") or "587")


XINNIX_SMTP_USER = os.environ.get("XINNIX_SMTP_USER", "")


XINNIX_SMTP_PASS = os.environ.get("XINNIX_SMTP_PASS", "")


XINNIX_SMTP_FROM = os.environ.get("XINNIX_SMTP_FROM", "") or XINNIX_SMTP_USER


XINNIX_OPP_STARTDATE_FIELD = "Djt6YNA5wPmftLuWD6ae"


def _xinnix_send_notification(subject, html_body, to_list=None):
    """Send the notification email via SMTP. No-op (logged) if SMTP env vars are unset, so
    the roster stamp + tag still work even before creds are added."""
    import smtplib, ssl
    from email.mime.text import MIMEText
    to_list = to_list or XINNIX_NOTIFY_TO
    if not (XINNIX_SMTP_HOST and XINNIX_SMTP_USER and XINNIX_SMTP_PASS and to_list):
        _log_debug("xinnix", "notification email skipped (SMTP not configured)")
        return False
    try:
        msg = MIMEText(html_body, "html", "utf-8")
        msg["Subject"] = subject
        msg["From"] = XINNIX_SMTP_FROM
        msg["To"] = ", ".join(to_list)
        with smtplib.SMTP(XINNIX_SMTP_HOST, XINNIX_SMTP_PORT, timeout=25) as s:
            s.starttls(context=ssl.create_default_context())
            s.login(XINNIX_SMTP_USER, XINNIX_SMTP_PASS)
            s.sendmail(XINNIX_SMTP_FROM, to_list, msg.as_string())
        _log_debug("xinnix", f"notification email sent -> {to_list}: {subject[:60]}")
        return True
    except Exception as _e:
        _log_debug("xinnix", f"notification email failed: {_e}")
        return False


def _xinnix_render_onboard_email(opp, manager_cid, roster_lines, headcount, seats):
    """Build (subject, html) for the Ready-to-Onboard email from this deal's data."""
    import html as _html

    def cf(fid):
        for c in (opp.get("customFields") or []):
            if c.get("id") == fid:
                return c.get("fieldValueArray") or c.get("fieldValueString") or c.get("fieldValueNumber") or c.get("fieldValue")
        return None
    progs = cf(XINNIX_OPP_PROGRAMS_FIELD) or []
    progs_str = ", ".join(progs) if isinstance(progs, list) else str(progs)
    company = cf(XINNIX_OPP_COMPANY_FIELD) or ""
    etype = cf(XINNIX_OPP_ENROLLTYPE_FIELD) or ""
    start = cf(XINNIX_OPP_STARTDATE_FIELD) or ""
    dv = cf(XINNIX_OPP_TOTALINV_FIELD) or opp.get("monetaryValue") or ""
    try:
        dv = "${:,.2f}".format(float(dv)) if dv not in ("", None) else ""
    except Exception:
        pass
    meta = _xinnix_contact_meta(manager_cid) if manager_cid else {}
    cname, cemail = meta.get("name", ""), meta.get("email", "")
    roster_html = "<br>".join(_html.escape(l) for l in roster_lines) if roster_lines else "(none assigned yet)"

    def row(k, v):
        return f'<tr><td style="padding:3px 0;color:#6b7683;width:150px">{k}</td><td>{_html.escape(str(v or ""))}</td></tr>'
    body = f"""<div style="font-family:Arial,Helvetica,sans-serif;max-width:640px;margin:0 auto;color:#1c2733;font-size:15px;line-height:1.55">
<div style="background:#0a1f44;color:#fff;padding:18px 22px;border-radius:8px 8px 0 0">
<div style="font-size:13px;letter-spacing:.08em;color:#efab1f;text-transform:uppercase">Ready to Onboard</div>
<div style="font-size:20px;font-weight:bold;margin-top:4px">New Enrollment: {_html.escape(company)}</div>
<div style="font-size:14px;margin-top:2px;color:#c7d2e2">{_html.escape(progs_str)}</div></div>
<div style="border:1px solid #e4e8ee;border-top:none;border-radius:0 0 8px 8px;padding:6px 22px 22px">
<h3 style="color:#0a1f44;border-bottom:2px solid #efab1f;padding-bottom:4px;margin-top:20px">Customer</h3>
<table style="width:100%;border-collapse:collapse;font-size:14px"><tbody>
{row("Contact", cname)}{row("Email", cemail)}{row("Company", company)}</tbody></table>
<h3 style="color:#0a1f44;border-bottom:2px solid #efab1f;padding-bottom:4px;margin-top:20px">What They Purchased</h3>
<table style="width:100%;border-collapse:collapse;font-size:14px"><tbody>
{row("Program(s)", progs_str)}{row("Type", etype)}{row("Seats purchased", seats)}{row("Students assigned", headcount)}{row("Student start", start)}</tbody></table>
<h3 style="color:#0a1f44;border-bottom:2px solid #efab1f;padding-bottom:4px;margin-top:20px">Students to Enroll</h3>
<div style="background:#f4f7fb;border:1px solid #e4e8ee;border-radius:6px;padding:12px 14px;font-size:14px;word-break:break-word">{roster_html}</div>
<h3 style="color:#0a1f44;border-bottom:2px solid #efab1f;padding-bottom:4px;margin-top:20px">Deal Reference</h3>
<table style="width:100%;border-collapse:collapse;font-size:14px"><tbody>
{row("Deal name", opp.get("name"))}{row("Deal value", dv)}</tbody></table>
<p style="margin-top:22px;color:#6b7683;border-top:1px solid #e4e8ee;padding-top:12px">Move this deal to <strong>In Progress</strong> once onboarding is scheduled.</p></div></div>"""
    subject = f"New Enrollment Ready to Onboard: {etype + ' - ' if etype else ''}({progs_str}){' - ' + cemail if cemail else ''}"
    return subject, body


XINNIX_OPP_PRIMARY_MGR_FIELD = "CQczFMQZvqbXyIzgqBHd"    # opportunity.primary_manager


XINNIX_OPP_SECONDARY_MGR_FIELD = "n0ddKwN5GqLZI81LfwaS"  # opportunity.secondary_manager


XINNIX_OPP_MANAGER3_FIELD = "FvNlZkC28rWgXrhm2JVs"       # opportunity.manager_3


_XINNIX_C_MGR = {
    "m1_first": "vJmUbMdMuTlGLycpKObe", "m1_last": "sZPlYyWp20YBWxbAN9Mb",
    "m1_email": "jzD9Ft1k2bl9VRDLF9mJ", "m1_phone": "aNYYAUR99Y76DFVcvvKC",
    "m2_first": "wDbmiNZnj8nbw6Z9Pnn6", "m2_last": "Lq7nc8Cd5Dk0ctUyuhRD",
    "m2_email": "2SKZWfuBPlEZWpXhCzjM", "m2_phone": "CkYsw2e0yVUjPvyqVxwH",
    "m3_full": "hY1pAQXF9Xb3hJA3GfDq", "m3_email": "oF9nY9yL5SFr8NXyGxVS", "m3_phone": "gsgqHyvk1YPAvsvFH5HA",
    "start": "4LHILPGqgwMclcTPjUp8",
}


def _xinnix_manager_cfs_from_contact(contact_id):
    """Read the partner-form Manager(s) + Program/Course Start Date off the CONTACT and return
    opportunity customFields that MIRROR them onto the deal, so Taylor, ops, and the rep all see
    the same info on every card and email:
      opportunity.primary_manager   = "Name (email, phone)"  (Manager 1)
      opportunity.secondary_manager = "Name (email, phone)"  (Manager 2)
      opportunity.manager_3         = "Name (email, phone)"  (Manager 3)
      opportunity.student_start_date = the June/July/August cohort they picked
    Blank on website / B2C orders (no managers filled), so nothing is stamped there. (Tim Jul 18.)"""
    if not contact_id or not XINNIX_GHL_TOKEN:
        return []
    headers = {**XINNIX_GHL_HEADERS, "Authorization": f"Bearer {XINNIX_GHL_TOKEN}"}
    try:
        r = requests.get(f"{XINNIX_GHL_BASE}/contacts/{contact_id}", headers=headers, timeout=20)
        c = (r.json().get("contact") or {}) if r.status_code == 200 else {}
    except Exception:
        return []
    v = {}
    for cf in (c.get("customFields") or []):
        val = cf.get("value")
        v[cf.get("id")] = val if val is not None else cf.get("fieldValue")
    def gv(k):
        return str(v.get(_XINNIX_C_MGR[k]) or "").strip()
    def fmt(name, email, phone):
        name = (name or "").strip()
        tail = ", ".join([x for x in [(email or "").strip(), (phone or "").strip()] if x])
        return (f"{name} ({tail})" if name and tail else (name or tail or "")).strip()
    m1 = fmt(f"{gv('m1_first')} {gv('m1_last')}".strip(), gv("m1_email"), gv("m1_phone"))
    m2 = fmt(f"{gv('m2_first')} {gv('m2_last')}".strip(), gv("m2_email"), gv("m2_phone"))
    m3 = fmt(gv("m3_full"), gv("m3_email"), gv("m3_phone"))
    start = gv("start")
    out = []
    if m1:    out.append({"id": XINNIX_OPP_PRIMARY_MGR_FIELD, "field_value": m1})
    if m2:    out.append({"id": XINNIX_OPP_SECONDARY_MGR_FIELD, "field_value": m2})
    if m3:    out.append({"id": XINNIX_OPP_MANAGER3_FIELD, "field_value": m3})
    if start: out.append({"id": XINNIX_OPP_STARTDATE_FIELD, "field_value": start})
    return out


def _xinnix_stamp_managers_on_deals(contact_id, cfs=None):
    """Stamp the Manager(s) + course start (from the contact's partner-form fields) onto ALL
    of the contact's enrollment-pipeline deals immediately, so they show even when the order
    defers to the picker (before _xinnix_stamp_roster runs). (Tim Jul 18.)"""
    cfs = cfs if cfs is not None else _xinnix_manager_cfs_from_contact(contact_id)
    if not cfs or not contact_id or not XINNIX_GHL_TOKEN:
        return 0
    headers = {**XINNIX_GHL_HEADERS, "Authorization": f"Bearer {XINNIX_GHL_TOKEN}"}
    try:
        r = requests.get(f"{XINNIX_GHL_BASE}/opportunities/search", headers=headers,
                         params={"location_id": XINNIX_LOCATION_ID, "contact_id": contact_id}, timeout=20)
        opps = r.json().get("opportunities", []) if r.status_code == 200 else []
    except Exception:
        return 0
    n = 0
    for o in opps:
        if o.get("pipelineId") in XINNIX_ENROLL_PIPELINES:
            try:
                requests.put(f"{XINNIX_GHL_BASE}/opportunities/{o.get('id')}", headers=headers,
                             json={"customFields": cfs}, timeout=20)
                n += 1
            except Exception:
                pass
    return n


def _xinnix_stamp_roster(opp_id, student_cids=None, manager_cid=None, seats=0, fire=False):
    """After seats are ASSIGNED, stamp the onboarding opp so the Ready-to-Onboard email
    can show who to enroll (Casey/Bryn Jul 17: student emails, headcount, allotment blank):
      - Student Headcount  = number of students assigned
      - Seat Allotment     = seats purchased/allotted
      - Student (roster)   = one "Name (email)" per line, every student's address
    When fire=True, tag the manager contact with XINNIX_ROSTER_READY_TAG so the GHL
    "roster ready" workflow sends the notification. This fires on picker COMPLETION, not
    at deal creation (before assignment the roster would be empty). (Tim Jul 17.)
    Pass student_cids explicitly (create-program-enrollment path) or leave None to derive
    the students/manager/seats from the opp's related contacts (enrollment-picker path)."""
    if not opp_id or not XINNIX_GHL_TOKEN:
        return {}
    headers = {**XINNIX_GHL_HEADERS, "Authorization": f"Bearer {XINNIX_GHL_TOKEN}"}
    if student_cids is None:
        opp = _xinnix_get_opportunity(opp_id)
        if not opp:
            return {}
        mgr_rel, stu_rels, _ = _xinnix_opp_contacts(opp, enroll_unclassified=True)
        student_cids = [r.get("recordId") for r in stu_rels if r.get("recordId")]
        if manager_cid is None and mgr_rel:
            manager_cid = mgr_rel.get("recordId")
        caps = _xinnix_opp_purchased(opp)
        seats = (sum(caps.values()) if caps else 0) or seats or _xinnix_opp_seats(opp)
    roster = []
    for cid in student_cids:
        meta = _xinnix_contact_meta(cid)
        email, name = (meta.get("email") or "").strip(), (meta.get("name") or "").strip()
        phone = (meta.get("phone") or "").strip()
        if not (email or name):
            continue
        # roster line = "Name (email, phone)" so onboarding can call, not just email (Tim Jul 19)
        contact_bits = ", ".join([b for b in (email, phone) if b])
        roster.append(f"{name} ({contact_bits})" if name and contact_bits else (contact_bits or name))
    headcount = len(roster)
    cfs = []
    if headcount:
        cfs.append({"id": XINNIX_OPP_HEADCOUNT_FIELD, "field_value": headcount})
    if seats:
        cfs.append({"id": XINNIX_OPP_ALLOTMENT_FIELD, "field_value": int(seats)})
    if roster:
        cfs.append({"id": XINNIX_OPP_STUDENT_FIELD, "field_value": "\n".join(roster)})
    # Stamp the roster fields (students / headcount / allotment) onto ALL THREE of the
    # contact's enrollment-pipeline deals (Mortgage, Customer Management, Contract) so the
    # sales rep, Jess (onboarding), and Taylor (contract) all see the same students the
    # notification shows. This replaces the GHL "Find Opportunity" steps that used to copy
    # fields between the deals (removed to kill the index race). (Tim Jul 18.)
    target_opps = [opp_id]
    try:
        _o = _xinnix_get_opportunity(opp_id)
        _buyer = ((_o.get("contactId") or (_o.get("contact") or {}).get("id")) if _o else None) \
                 or manager_cid or (student_cids[0] if student_cids else None)
        if _buyer:
            _sr = requests.get(f"{XINNIX_GHL_BASE}/opportunities/search", headers=headers,
                               params={"location_id": XINNIX_LOCATION_ID, "contact_id": _buyer}, timeout=20)
            for _o2 in (_sr.json().get("opportunities", []) if _sr.status_code == 200 else []):
                if _o2.get("id") != opp_id and _o2.get("pipelineId") in XINNIX_ENROLL_PIPELINES:
                    target_opps.append(_o2.get("id"))
    except Exception as _e:
        _log_debug("xinnix", f"roster sibling-deal resolve failed: {_e}")
    # Mirror the partner-form Manager(s) + course start date onto the deals too (blank on B2C),
    # read off the buyer/manager contact who filled the form. (Tim Jul 18.)
    try:
        _mgr_src = manager_cid
        if not _mgr_src:
            _ob = _xinnix_get_opportunity(opp_id)
            _mgr_src = (_ob.get("contactId") or (_ob.get("contact") or {}).get("id")) if _ob else None
        if _mgr_src:
            cfs = cfs + _xinnix_manager_cfs_from_contact(_mgr_src)
            # Stamp the FULL student roster onto the buyer's contact so the tag-triggered email
            # lists every student via {{contact.enrolled_students}} (not just the buyer). (Tim Jul 18.)
            if roster:
                try:
                    requests.put(f"{XINNIX_GHL_BASE}/contacts/{_mgr_src}", headers=headers,
                        json={"customFields": [{"id": "Npdr3Y5O82sS3fXw893x", "field_value": "\n".join(roster)}]},
                        timeout=20)
                except Exception as _e:
                    _log_debug("xinnix", f"enrolled_students contact stamp failed: {_e}")
    except Exception as _e:
        _log_debug("xinnix", f"manager stamp resolve failed: {_e}")
    if cfs:
        for _tid in target_opps:
            try:
                requests.put(f"{XINNIX_GHL_BASE}/opportunities/{_tid}", headers=headers,
                             json={"customFields": cfs}, timeout=20)
            except Exception as _e:
                _log_debug("xinnix", f"roster stamp put failed {_tid}: {_e}")
    if fire and manager_cid and headcount:
        # remove + re-add the tag so a repeat completion (rep edits the grid) re-fires the email
        try:
            requests.delete(f"{XINNIX_GHL_BASE}/contacts/{manager_cid}/tags", headers=headers,
                            json={"tags": [XINNIX_ROSTER_READY_TAG]}, timeout=15)
        except Exception:
            pass
        try:
            requests.post(f"{XINNIX_GHL_BASE}/contacts/{manager_cid}/tags", headers=headers,
                          json={"tags": [XINNIX_ROSTER_READY_TAG]}, timeout=15)
        except Exception as _e:
            _log_debug("xinnix", f"roster tag failed {manager_cid}: {_e}")
    # BULLETPROOF: send the Ready-to-Onboard email straight from here, with this deal's
    # data baked in (no GHL trigger / merge-field ambiguity). Only when there's a roster.
    if fire and roster:
        try:
            _fresh = _xinnix_get_opportunity(opp_id)
            if _fresh:
                subj, body = _xinnix_render_onboard_email(_fresh, manager_cid, roster, headcount, seats)
                _xinnix_send_notification(subj, body)
        except Exception as _e:
            _log_debug("xinnix", f"onboard email render/send failed {opp_id}: {_e}")
    _log_debug("xinnix", f"roster stamped opp={opp_id} headcount={headcount} allotment={seats} fire={fire}")
    return {"headcount": headcount, "allotment": int(seats or 0), "roster": headcount}


def _xinnix_resolve_product(name):
    """Map a program/product name to its catalog entry (longest normalized match).
    Matches against both the full catalog name and its parenthetical-stripped core, so
    'LEADx' resolves to 'LEADx (Virtual)' and 'POWER' to 'POWER (Communication...)'."""
    if not name:
        return None
    target = _xinnix_norm_program(name)
    best, best_len = None, 0
    for key, entry in XINNIX_PRODUCT_CATALOG.items():
        for variant in (key, re.sub(r"\(.*?\)", "", key)):
            nk = _xinnix_norm_program(variant)
            if not nk:
                continue
            if target == nk:
                return {**entry, "name": key}
            if (target.startswith(nk) or nk in target) and len(nk) > best_len:
                best, best_len = {**entry, "name": key}, len(nk)
    return best


def _xinnix_build_estimate_items(opp):
    """Merge an opp's Program(s)/Products selection into estimate line items with real
    catalog prices. Returns (items, subtotal, matched_names, unmatched_names)."""
    items, matched, unmatched = [], [], []
    for p in _xinnix_opp_programs(opp):
        cat = _xinnix_resolve_product(p)
        if not cat:
            unmatched.append(p)
            continue
        matched.append(cat["name"])
        items.append({"name": cat["name"], "productId": cat["productId"],
                      "priceId": cat["priceId"], "currency": "USD",
                      "amount": cat["amount"], "qty": 1})
    subtotal = sum(i["amount"] for i in items)
    return items, subtotal, matched, unmatched


XINNIX_OPP_TYPE_FIELD = "QHzbGnEMaYdqIR8wkQdw"          # Opportunity Type (SINGLE_OPTIONS)


XINNIX_PARTNER_OPP_TYPES = {"strategic partner", "strategic partner seat usage"}


XINNIX_CONTRACT_PRODUCT_PATTERNS = (
    "unlimited", "strategic partner", "platinum", "originator plus",
    "speakx", "xinnixspeaks", "xinnix speaks", "speaks",
    "keynote", "xtalks", "engagex", "90 min",
)


def _xinnix_opp_type(opp):
    for cf in (opp.get("customFields") or []):
        if cf.get("id") == XINNIX_OPP_TYPE_FIELD:
            return (cf.get("fieldValueString") or cf.get("fieldValue") or "").strip()
    return ""


def _xinnix_program_qty(name, caps):
    """Best-effort purchased quantity for a program: a '(xN)' suffix on the name, else the
    per-program caps JSON (loose name match), else 1."""
    m = re.search(r"\(x\s*(\d+)\)", name or "", re.I)
    if m:
        return int(m.group(1))
    tn = _xinnix_norm_program(re.sub(r"\(.*?\)", "", name or ""))
    for k, v in (caps or {}).items():
        if _xinnix_norm_program(re.sub(r"\(.*?\)", "", k)) == tn:
            return int(v)
    return 1


def _xinnix_proposal_path(opp):
    """Estimate vs signed agreement, decided by PRODUCT (Taylor + Tim, Jul 13 call;
    supersedes the Jul-9 opp-type-only rule). An agreement/contract is required when ANY
    selected product is a contract product (ZINX Unlimited, SPEAKx/XINNIXSpeaks, Strategic
    Partnership, Platinum Partnership, ORIGINATOR Plus) OR when a product is bought as a
    bundle / multiple seats (qty > 1 - those expire and always need a contract + statement
    of work). A single non-contract product uses an estimate + T&Cs. Partner opp type is
    kept as a final fallback. Returns (path, reason)."""
    caps = _xinnix_opp_purchased(opp)
    for name in _xinnix_opp_programs(opp):
        n = (name or "").lower()
        for pat in XINNIX_CONTRACT_PRODUCT_PATTERNS:
            if pat in n:
                return "agreement", f"contract product: '{name}' (matched '{pat}')"
        if _xinnix_program_qty(name, caps) > 1:
            return "agreement", f"bundle/seats: {name} x{_xinnix_program_qty(name, caps)} (expires -> contract + SOW)"
    if _xinnix_opp_seats(opp) > 1:
        return "agreement", f"multi-seat purchase ({_xinnix_opp_seats(opp)} seats -> contract + SOW)"
    if _xinnix_opp_type(opp).lower() in XINNIX_PARTNER_OPP_TYPES:
        return "agreement", "opportunity type = partner"
    return "estimate", "single product, no contract trigger"


def _xinnix_create_draft_estimate(opp, items_raw):
    """Create a DRAFT estimate on the opp's contact with the merged line items.
    Does NOT send it. Returns (status_code, estimate_id, status_or_error)."""
    import datetime
    headers = {**XINNIX_GHL_HEADERS, "Authorization": f"Bearer {XINNIX_GHL_TOKEN}"}
    cid = opp.get("contactId")
    contact = {}
    if cid:
        cr = requests.get(f"{XINNIX_GHL_BASE}/contacts/{cid}", headers=headers, timeout=20)
        if cr.status_code == 200:
            contact = cr.json().get("contact", {})
    items = [{"name": i["name"], "description": "", "type": "one_time",
              "priceType": "one_time", "currency": "USD", "amount": i["amount"],
              "qty": 1, "productId": i["productId"], "priceId": i["priceId"],
              "taxes": [], "taxInclusive": False} for i in items_raw]
    # Use the LOCATION's timezone (America/New_York), not the server's UTC, or GHL
    # rejects the estimate as "issue date in the future" after midnight UTC.
    try:
        from zoneinfo import ZoneInfo
        today = datetime.datetime.now(ZoneInfo("America/New_York")).date()
    except Exception:
        today = (datetime.datetime.utcnow() - datetime.timedelta(hours=5)).date()
    body = {
        "altId": XINNIX_LOCATION_ID, "altType": "location",
        "name": ("Proposal - " + str(opp.get("name") or ""))[:40],
        "title": "Proposal", "currency": "USD", "items": items,
        "discount": {"type": "percentage", "value": 0},
        "liveMode": True, "frequencySettings": {"enabled": False},
        "estimateNumberPrefix": "EST-",
        "issueDate": today.isoformat(),
        "expiryDate": (today + datetime.timedelta(days=30)).isoformat(),
        "businessDetails": {"name": "XINNIX", "phoneNo": "+16783253500",
            "website": "www.XINNIX.com",
            "address": {"addressLine1": "44 Milton Ave, Ste 1050", "countryCode": "US",
                        "state": "GA", "city": "Alpharetta", "postalCode": "30009"}},
        "contactDetails": {"id": cid,
            "name": f"{contact.get('firstName','')} {contact.get('lastName','')}".strip(),
            "email": contact.get("email", ""), "phoneNo": contact.get("phone", "")},
        "termsNotes": (
            "Thank you for your interest in XINNIX training programs. This proposal is valid "
            "for 30 days from the date of issue. Payment is due upon acceptance unless otherwise "
            "specified. All programs include access to the XINNIX learning platform and dedicated "
            "support from your assigned coach. CANCELLATION POLICY: Full refund if cancelled within "
            "7 days of enrollment. After 7 days, a prorated refund may be issued at XINNIX's "
            "discretion. Program start dates are subject to availability and minimum enrollment "
            "requirements. Seat counts and pricing are based on the programs selected in this "
            "proposal and may be adjusted prior to acceptance."
        ),
    }
    r = requests.post(f"{XINNIX_GHL_BASE}/invoices/estimate", headers=headers, json=body, timeout=30)
    if r.status_code in (200, 201):
        est = r.json()
        return r.status_code, est.get("_id"), est.get("estimateStatus")
    return r.status_code, None, r.text[:300]


@app.route("/xinnix/proposal-estimate", methods=["POST", "OPTIONS"])
def xinnix_proposal_estimate():
    """Draft an estimate for an opportunity from its selected Program(s)/Products.
    Body: {opportunity_id, dry_run?}. dry_run (or no matched products) returns the
    merged line items + subtotal WITHOUT creating anything - this proves the merge.
    Live DRAFT-estimate creation + Taylor task is gated until the Payments API path
    is verified with Tim (build-spec Part 1)."""
    if request.method == "OPTIONS":
        return ("", 204)
    if not XINNIX_GHL_TOKEN:
        return jsonify({"error": "Server misconfigured - missing XINNIX_GHL_TOKEN"}), 500
    data = request.get_json(force=True, silent=True) or {}
    # GHL's Custom Webhook nests the Custom Data key/values under "customData" - lift to top level.
    _cd = data.get("customData")
    if isinstance(_cd, dict):
        for _k, _v in _cd.items():
            # GHL Custom Data keys can carry stray whitespace (a "opportunity_id " row with a
            # trailing space slipped through 06.5 and made the webhook miss the opp id entirely,
            # so it fell back to guessing the deal from the contact and grabbed the wrong old opp
            # for repeat buyers). Normalize the key so data.get("opportunity_id") always resolves.
            if isinstance(_k, str):
                _k = _k.strip()
            if _v not in (None, "", [], {}) and data.get(_k) in (None, "", [], {}):
                data[_k] = _v
    opp_id = (data.get("opportunity_id") or data.get("opp") or "").strip()
    dry_run = bool(data.get("dry_run"))
    if not opp_id:
        return jsonify({"error": "opportunity_id required"}), 400
    opp = _xinnix_get_opportunity(opp_id)
    if not opp:
        return jsonify({"error": "opportunity not found"}), 404
    items, subtotal, matched, unmatched = _xinnix_build_estimate_items(opp)
    path, path_reason = _xinnix_proposal_path(opp)
    summary = {"opportunity_id": opp_id, "opp_name": opp.get("name"),
               "path": path, "path_reason": path_reason,
               "items": items, "item_count": len(items), "subtotal": subtotal,
               "matched": matched, "unmatched": unmatched, "dry_run": True}
    if dry_run or not items:
        if not items:
            summary["note"] = "no catalog products matched on the opportunity - nothing to draft"
        return jsonify(summary)
    # BOTH paths now draft a DRAFT estimate (never sent) and stamp its link onto the opp, so
    # {{opportunity.proposal_link}} always populates for the note/task. Agreement/contract deals
    # ALSO need a signed agreement + invoice drafted in Contract & Invoicing (handled downstream);
    # the estimate here is the viewable proposal document + working link. (Option A, Tim Jul 16.)
    sc, est_id, info = _xinnix_create_draft_estimate(opp, items)
    summary["dry_run"] = False
    if est_id:
        summary["estimate_id"] = est_id
        summary["estimate_status"] = info
        summary["estimate_edit_url"] = (
            f"https://app.gohighlevel.com/v2/location/{XINNIX_LOCATION_ID}"
            f"/payments/v2/estimates/edit/{est_id}")
        # Stamp the edit link onto the opp's "Proposal Link" field (Proposal Details folder)
        # so the rep opens the opp and one-clicks straight into the draft to edit/send.
        try:
            requests.put(f"{XINNIX_GHL_BASE}/opportunities/{opp_id}",
                headers={**XINNIX_GHL_HEADERS, "Authorization": f"Bearer {XINNIX_GHL_TOKEN}"},
                json={"customFields": [{"id": "iWLnm5oR4a24yOSGocyl",         # Proposal Link (legacy)
                                        "field_value": summary["estimate_edit_url"]},
                                       {"id": "QcQPGLFh0spGvvVGAFnc",         # Estimate Link (dedicated)
                                        "field_value": summary["estimate_edit_url"]}]},
                timeout=20)
        except Exception as _e:
            _log_debug("xinnix", f"proposal-link stamp failed: {_e}")
        # Post the estimate link as a NOTE on the deal's contact directly. GHL has no
        # opportunity-notes API, and a workflow "Add Note" step resolves the
        # {{opportunity.estimate_link}} merge field BEFORE this webhook stamps it, so that
        # note came out empty. Baking the live link into the note here means it is never
        # blank. Remove the GHL "Add Note" step so there is no empty duplicate. (Tim Jul 18.)
        _note_cid = opp.get("contactId") or (opp.get("contact") or {}).get("id")
        if _note_cid:
            _lines = "\n".join(f"  - {i['name']} x{i['qty']}  (${i['amount']})" for i in items) or "  (see estimate)"
            _note_body = (f"XINNIX estimate ready ({path}).\n{_lines}\n"
                          f"Subtotal: ${subtotal}\n"
                          f"Open / edit / send the estimate: {summary['estimate_edit_url']}")
            try:
                requests.post(f"{XINNIX_GHL_BASE}/contacts/{_note_cid}/notes",
                    headers={**XINNIX_GHL_HEADERS, "Authorization": f"Bearer {XINNIX_GHL_TOKEN}"},
                    json={"body": _note_body}, timeout=20)
                summary["note_posted"] = True
            except Exception as _e:
                _log_debug("xinnix", f"estimate note post failed: {_e}")
        if path == "agreement":
            summary["note"] = (f"agreement path ({path_reason}): draft estimate created as the "
                               f"proposal doc and Proposal Link stamped. Also draft the contract "
                               f"+ invoice in Contract & Invoicing. products={matched}")
        else:
            summary["note"] = f"draft estimate created (status={info}); path={path}"
        return jsonify(summary), 201
    summary["error"] = f"estimate create failed (HTTP {sc})"
    summary["detail"] = info
    return jsonify(summary), 502


@app.route("/xinnix/enroll-grid", methods=["GET", "OPTIONS"])
def xinnix_enroll_grid_get():
    """Return the grid data for an opportunity: student rows x program columns,
    with each student's currently-assigned programs."""
    if request.method == "OPTIONS":
        return ("", 204)
    if not XINNIX_GHL_TOKEN:
        return jsonify({"error": "Server misconfigured — missing XINNIX_GHL_TOKEN"}), 500
    opp_id = (request.args.get("opp") or "").strip()
    if not opp_id:
        return jsonify({"error": "opp query param required"}), 400
    opp = _xinnix_get_opportunity(opp_id)
    if not opp:
        return jsonify({"error": "opportunity not found"}), 404
    programs = _xinnix_opp_programs(opp)
    purchased = _xinnix_opp_purchased(opp)
    # Prefill each program's purchased cap from the deal's Seats when no explicit cap is
    # stored yet, so the rep starts from the seats they sold instead of a blank box.
    seats = _xinnix_opp_seats(opp)
    if seats > 0:
        for p in programs:
            purchased.setdefault(p, seats)
    mgr, students, _ = _xinnix_opp_contacts(opp, enroll_unclassified=True)
    rows = []
    for r in students:
        cid = r.get("recordId")
        enr = _xinnix_contact_enrollments(cid)
        assigned = [e["program_name"] for e in enr if e.get("program_name") in programs]
        rows.append({"contact_id": cid, "name": r.get("fullName") or "", "assigned": assigned})
    return jsonify({"opp_id": opp_id, "opp_name": opp.get("name"),
                    "manager": ({"contact_id": mgr.get("recordId"), "name": mgr.get("fullName")} if mgr else None),
                    "programs": programs, "purchased": purchased, "students": rows})


@app.route("/xinnix/enroll-grid", methods=["POST"])
def xinnix_enroll_grid_post():
    """Reconcile enrollments to a desired grid state.
    Body: { "opp": "<id>", "assignments": { "<contact_id>": ["ProgA","ProgB"], ... } }
    Creates enrollments for newly-checked cells, deletes for unchecked ones."""
    data = request.get_json(force=True, silent=True) or {}
    if not XINNIX_GHL_TOKEN:
        return jsonify({"error": "Server misconfigured — missing XINNIX_GHL_TOKEN"}), 500
    opp_id = (data.get("opp") or "").strip()
    assignments = data.get("assignments") or {}
    purchased_in = data.get("purchased")  # {program: qty} typed by the rep, optional
    dry_run = bool(data.get("dry_run"))
    if not opp_id:
        return jsonify({"error": "opp required"}), 400
    names = {}
    opp = _xinnix_get_opportunity(opp_id)
    if opp:
        _, students, _ = _xinnix_opp_contacts(opp, enroll_unclassified=True)
        names = {s.get("recordId"): s.get("fullName") or "" for s in students}

    # Payment guard: the picker is meant to run AFTER payment. 06.5 moves a deal to
    # Won on payment success, so status != "won" means no payment is recorded yet.
    # Block the apply (which also fires the onboarding roster email) on an unpaid deal
    # unless the rep explicitly overrides with force:true. Prevents the "enrolled with
    # no payment" case (Bryan Bergjans, flagged by Bryn Jul 30). dry_run previews and
    # explicit overrides pass through.
    if not dry_run and not data.get("force") and opp:
        _status = (opp.get("status") or "").lower()
        if _status != "won":
            return jsonify({"error": "payment_required",
                            "opp_status": _status or "unknown",
                            "opp_name": opp.get("name"),
                            "message": "This deal is not marked Won, so no payment is "
                                       "recorded yet. Enrolling now sends onboarding "
                                       "before payment. Confirm to enroll anyway."}), 409

    # Persist the purchased-quantity caps (rep-entered), then enforce them.
    if purchased_in is not None and not dry_run:
        _xinnix_set_opp_purchased(opp_id, purchased_in)
    if purchased_in is not None:
        caps = {k: int(v) for k, v in purchased_in.items()
                if str(v).strip() != "" and str(v).isdigit() and int(v) > 0}
    else:
        caps = _xinnix_opp_purchased(opp) if opp else {}
    # Count desired enrollments per program across all students; block any that exceed the cap.
    desired_counts = {}
    for _cid, _want in assignments.items():
        for _p in set(_want or []):
            desired_counts[_p] = desired_counts.get(_p, 0) + 1
    violations = [{"program": p, "requested": desired_counts[p], "purchased": caps[p]}
                  for p in desired_counts if p in caps and desired_counts[p] > caps[p]]
    if violations:
        return jsonify({"error": "over_capacity", "violations": violations,
                        "message": "One or more programs exceed the purchased quantity. "
                                   "No enrollments were changed."}), 409

    changes = []
    for cid, want_list in assignments.items():
        want = set(want_list or [])
        existing = _xinnix_contact_enrollments(cid)
        have = {e["program_name"]: e["enrollment_id"] for e in existing if e.get("program_name")}
        for prog in want:
            if prog not in have:
                if dry_run:
                    changes.append({"contact": cid, "program": prog, "action": "would_create"})
                else:
                    res = _xinnix_create_one_enrollment(cid, prog, opp_id, names.get(cid, ""))
                    changes.append({"contact": cid, "program": prog, "action": "created", "result": res})
        for prog, enr_id in have.items():
            if prog not in want:
                if dry_run:
                    changes.append({"contact": cid, "program": prog, "action": "would_delete"})
                else:
                    sc = _xinnix_delete_enrollment(enr_id)
                    changes.append({"contact": cid, "program": prog, "action": "deleted", "status": sc})
    # Manager stamp (picker): if the deal's buyer (primary contact) is NOT among the enrolled
    # students, they're the manager who bought seats for someone else, so stamp their name /
    # email / phone into the Manager 1 fields on their own contact. _xinnix_stamp_roster then
    # mirrors those onto the opp, so the Ready-to-Onboard shows who purchased instead of a blank
    # manager. Only fills when Manager 1 is blank. Mirrors the create-program-enrollment
    # auto-stamp so both paths behave the same. (Bryn Jul 30: picker had no student/manager step.)
    if not dry_run and opp:
        try:
            _buyer_id = opp.get("contactId") or (opp.get("contact") or {}).get("id")
            _enrolled = {c for c, w in assignments.items() if (w or [])}
            if _buyer_id and _buyer_id not in _enrolled:
                _h = {**XINNIX_GHL_HEADERS, "Authorization": f"Bearer {XINNIX_GHL_TOKEN}"}
                _bc = requests.get(f"{XINNIX_GHL_BASE}/contacts/{_buyer_id}", headers=_h, timeout=20)
                _b = (_bc.json().get("contact") or {}) if _bc.status_code == 200 else {}
                _cur = ""
                for _c in (_b.get("customFields") or []):
                    if _c.get("id") == "vJmUbMdMuTlGLycpKObe":                       # manager_first_name
                        _cur = (_c.get("value") or _c.get("fieldValue") or "")
                        break
                if _b and not _cur:
                    _mcfs = [{"id": _fid, "field_value": _v} for _fid, _v in (
                        ("vJmUbMdMuTlGLycpKObe", _b.get("firstName")),               # manager_first_name
                        ("sZPlYyWp20YBWxbAN9Mb", _b.get("lastName")),                # manager_last_name
                        ("jzD9Ft1k2bl9VRDLF9mJ", _b.get("email")),                   # manager_email
                        ("aNYYAUR99Y76DFVcvvKC", _b.get("phone")),                   # manager_phone
                    ) if _v]
                    if _mcfs:
                        requests.put(f"{XINNIX_GHL_BASE}/contacts/{_buyer_id}", headers=_h,
                                     json={"customFields": _mcfs}, timeout=20)
                        _log_debug("xinnix", f"picker manager-stamped buyer {_b.get('email')} on {opp_id}")
        except Exception as _e:
            _log_debug("xinnix", f"picker manager stamp failed: {_e}")

    # Picker COMPLETED: stamp headcount / allotment / roster and fire the roster email.
    roster = {}
    if not dry_run:
        roster = _xinnix_stamp_roster(opp_id, fire=True)
    return jsonify({"success": True, "dry_run": dry_run, "opp": opp_id, "changes": changes, "roster": roster})


@app.route("/xinnix/enroll-grid/add-student", methods=["POST", "OPTIONS"])
def xinnix_enroll_grid_add_student():
    """Picker: add the real student to a manager's deal. Creates or finds the student contact
    (deduped by email, DND-safe) so the rep can enroll who is actually being trained instead of
    the buyer landing in the student slot. Returns a grid row the UI appends. The enrollment is
    created on Save via _xinnix_create_one_enrollment, which does not require a contact<->opp
    association, so the added student enrolls cleanly. (Bryn Jul 30.)"""
    if request.method == "OPTIONS":
        return ("", 204)
    if not XINNIX_GHL_TOKEN:
        return jsonify({"error": "Server misconfigured — missing XINNIX_GHL_TOKEN"}), 500
    data = request.get_json(force=True, silent=True) or {}
    email = (data.get("email") or "").strip()
    first = (data.get("firstName") or "").strip()
    last = (data.get("lastName") or "").strip()
    phone = (data.get("phone") or "").strip()
    if not email or not (first or last):
        return jsonify({"error": "Student name and email are both required."}), 400
    cid, created = _xinnix_find_or_create_contact(first, last, email, phone)
    if not cid:
        return jsonify({"error": "Could not add the student in GHL. Check the email and try again."}), 502
    name = f"{first} {last}".strip() or email
    return jsonify({"contact_id": cid, "name": name, "created": created})


XINNIX_PICKER_HTML = r"""<!DOCTYPE html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow"><title>XINNIX Enrollment Picker</title>
<style>
:root{--navy:#003366;--gold:#ED8B00;--line:#dfe6ee;--ink:#1a2430;--mut:#5b6b7a;--green:#2e8b57;}
*{box-sizing:border-box}body{margin:0;font-family:'Segoe UI',Helvetica,Arial,sans-serif;color:var(--ink);background:#eef2f6}
header{background:var(--navy);color:#fff;padding:16px 20px}header h1{margin:0;font-size:18px}header .sub{color:#bcd0e4;font-size:13px;margin-top:3px}
.wrap{max-width:900px;margin:0 auto;padding:18px}
.card{background:#fff;border:1px solid var(--line);border-radius:12px;padding:16px 18px;margin-bottom:16px}
.hint{font-size:13.5px;color:var(--mut);margin:0 0 12px}
table{width:100%;border-collapse:collapse;font-size:14px}
th,td{padding:9px 10px;border-bottom:1px solid var(--line);text-align:left}
th{background:#f4f7fb;color:var(--navy);font-size:12.5px;position:sticky;top:0}
td.prog,th.prog{text-align:center}
.name{font-weight:600}.role{font-size:11px;color:var(--mut);font-weight:400;display:block}
input[type=checkbox]{width:20px;height:20px;cursor:pointer}
input[type=checkbox]:disabled{cursor:not-allowed;opacity:.4}
.capbox{margin-top:6px;font-weight:400}
.capbox label{display:block;font-size:10px;color:var(--mut);text-transform:none;letter-spacing:0;margin-bottom:2px}
input.cap{width:56px;padding:4px 6px;border:1px solid var(--line);border-radius:6px;font-size:13px;text-align:center}
.used{display:block;margin-top:4px;font-size:11px;color:var(--mut);font-weight:600}
.used.full{color:var(--navy)}.used.over{color:#c0392b}
.mgr{background:#f9fbfd;color:var(--mut)}
button{background:var(--gold);color:#fff;border:0;padding:11px 22px;border-radius:8px;font-weight:700;cursor:pointer;font-size:15px}
button:disabled{opacity:.5;cursor:default}
#msg{font-size:14px;margin-top:12px}.ok{color:var(--green)}.err{color:#c0392b}
.gate{position:fixed;inset:0;background:var(--navy);display:flex;align-items:center;justify-content:center;z-index:99}
.gate .box{text-align:center;color:#fff;max-width:320px;padding:24px}.gate input{padding:12px;width:100%;border:0;border-radius:8px;font-size:16px;margin:12px 0}
.tablewrap{overflow-x:auto}
#toast{position:fixed;left:50%;top:20px;transform:translateX(-50%);background:var(--green);color:#fff;padding:15px 30px;border-radius:10px;font-size:17px;font-weight:700;box-shadow:0 8px 28px rgba(0,0,0,.28);z-index:200;display:none}
</style></head><body>
<div id="toast"></div>
<div class="gate" id="gate"><div class="box"><div style="font-size:20px;font-weight:700;letter-spacing:2px">XINNIX</div>
<p style="color:#bcd0e4">Access code</p><input id="pw" type="password" onkeydown="if(event.key==='Enter')unlock()"><button onclick="unlock()">Open</button></div></div>
<header><h1>Enrollment Picker</h1><div class="sub" id="oppname">Loading...</div></header>
<div class="wrap">
<div class="card">
<div id="search" style="display:none"><p class="hint">Search for the deal to set enrollments on:</p><input id="q" placeholder="Deal or company name..." autocomplete="off" oninput="doSearch()" style="width:100%;padding:11px;border:1px solid var(--line);border-radius:8px;font-size:15px"><div id="results" style="margin-top:8px"></div></div>
<div id="gridwrap" style="display:none">
<p class="hint">Set how many seats were purchased for each program (the "purchased" box under each column), then check which student goes in which program. Once a program is full, its remaining boxes lock so you can't enroll more than were paid for. Leave a purchased box blank for no limit. The manager is shown for reference and is not enrolled unless also marked a student. Click Save to apply.</p>
<div class="tablewrap"><table id="grid"><thead></thead><tbody></tbody></table></div>
<div id="addstu" style="margin-top:14px;padding:12px 14px;border:1px dashed var(--line);border-radius:8px;background:#f9fbfd">
<div style="font-size:13px;font-weight:700;color:var(--navy);margin-bottom:6px">Add a student</div>
<p class="hint" style="margin:0 0 10px">On a manager purchase the buyer shows above for reference. Enter the person actually being trained here, then check their program and Save. The buyer stays the manager, not a student.</p>
<div style="display:flex;flex-wrap:wrap;gap:8px;align-items:center">
<input id="sf" placeholder="First name" style="padding:9px;border:1px solid var(--line);border-radius:8px;font-size:14px;flex:1;min-width:110px">
<input id="sl" placeholder="Last name" style="padding:9px;border:1px solid var(--line);border-radius:8px;font-size:14px;flex:1;min-width:110px">
<input id="se" type="email" placeholder="Email" style="padding:9px;border:1px solid var(--line);border-radius:8px;font-size:14px;flex:1.4;min-width:150px">
<input id="sp" placeholder="Phone (optional)" style="padding:9px;border:1px solid var(--line);border-radius:8px;font-size:14px;flex:1;min-width:120px">
<button type="button" onclick="addStudent()" style="padding:9px 18px;font-size:14px">Add</button>
</div>
<span id="addmsg" style="font-size:13px"></span>
</div>
<div style="margin-top:14px"><button id="save" onclick="save()" disabled>Save enrollments</button><span id="msg"></span></div>
</div>
</div></div>
<script>
var API="", OPP=new URLSearchParams(location.search).get("opp")||"", DATA=null;
function unlock(){if(document.getElementById('pw').value.trim().toLowerCase()==='xinnix2026'){localStorage.setItem('xnxpick','1');document.getElementById('gate').style.display='none';load();}else{document.getElementById('pw').value='';document.getElementById('pw').placeholder='Try again';}}
if(localStorage.getItem('xnxpick')==='1'){document.getElementById('gate').style.display='none';}
var stmr;
function doSearch(){clearTimeout(stmr);stmr=setTimeout(function(){
 var q=document.getElementById('q').value.trim();var R=document.getElementById('results');
 if(q.length<2){R.innerHTML='';return;}
 fetch(API+'/xinnix/opp-search?q='+encodeURIComponent(q)).then(r=>r.json()).then(function(d){
  R.innerHTML=(d.results||[]).map(function(o){return '<div style="padding:10px 12px;border:1px solid var(--line);border-radius:8px;margin-bottom:6px;cursor:pointer" onclick="pickOpp(\''+o.id+'\')">'+(o.name||o.id)+'</div>';}).join('')||'<p class="hint">No matches</p>';
 });
},250);}
function pickOpp(id){OPP=id;history.replaceState(null,'','?opp='+id);load();}
function load(){
 if(!OPP){document.getElementById('search').style.display='block';document.getElementById('oppname').textContent='Pick a deal to begin';return;}
 document.getElementById('search').style.display='none';document.getElementById('gridwrap').style.display='block';
 fetch(API+'/xinnix/enroll-grid?opp='+encodeURIComponent(OPP)).then(r=>r.json()).then(d=>{
  if(d.error){document.getElementById('oppname').textContent='Error: '+d.error;return;}
  DATA=d;document.getElementById('oppname').textContent=d.opp_name||OPP;
  var pur=d.purchased||{};
  function esc(s){return String(s).replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;');}
  var thead='<tr><th>Student</th>';d.programs.forEach(function(p){
   var cv=(pur[p]!=null&&pur[p]>0)?pur[p]:'';
   thead+='<th class="prog">'+esc(p)+
    '<div class="capbox"><label>purchased</label>'+
    '<input class="cap" type="number" min="0" data-prog="'+esc(p)+'" value="'+cv+'" oninput="refreshCaps()" placeholder="∞"></div>'+
    '<span class="used" data-prog="'+esc(p)+'"></span></th>';});
  thead+='</tr>';
  document.querySelector('#grid thead').innerHTML=thead;
  var tb='';
  if(d.manager){tb+='<tr class="mgr"><td class="name">'+d.manager.name+'<span class="role">Manager</span></td>';d.programs.forEach(function(){tb+='<td class="prog">-</td>';});tb+='</tr>';}
  d.students.forEach(function(s){tb+='<tr data-cid="'+s.contact_id+'"><td class="name">'+s.name+'<span class="role">Student</span></td>';
   d.programs.forEach(function(p){var ck=s.assigned.indexOf(p)>-1?'checked':'';tb+='<td class="prog"><input type="checkbox" data-prog="'+esc(p)+'" onchange="refreshCaps()" '+ck+'></td>';});tb+='</tr>';});
  document.querySelector('#grid tbody').innerHTML=tb;
  refreshCaps();
  document.getElementById('save').disabled=false;
 }).catch(function(e){document.getElementById('oppname').textContent='Load failed: '+e;});
}
function boxesForProg(p){var out=[];document.querySelectorAll('#grid tbody input[type=checkbox]').forEach(function(c){if(c.getAttribute('data-prog')===p)out.push(c);});return out;}
function capFor(p){var i=document.querySelector('input.cap[data-prog="'+p.replace(/"/g,'\\"')+'"]');if(!i)return 0;var v=parseInt(i.value,10);return isNaN(v)||v<0?0:v;}
function refreshCaps(){
 if(!DATA)return;
 DATA.programs.forEach(function(p){
  var cap=capFor(p);var boxes=boxesForProg(p);
  var used=boxes.filter(function(c){return c.checked;}).length;
  var span=document.querySelector('.used[data-prog="'+p.replace(/"/g,'\\"')+'"]');
  if(span){
   if(cap>0){span.textContent=used+' of '+cap+(used>cap?' - OVER':'');span.className='used'+(used>cap?' over':(used>=cap?' full':''));}
   else{span.textContent=used+' checked';span.className='used';}
  }
  boxes.forEach(function(c){c.disabled=(cap>0&&used>=cap&&!c.checked);});
 });
}
function save(force){
 var asg={};document.querySelectorAll('#grid tbody tr[data-cid]').forEach(function(tr){
  var cid=tr.getAttribute('data-cid');asg[cid]=[];
  tr.querySelectorAll('input[type=checkbox]:checked').forEach(function(c){asg[cid].push(c.getAttribute('data-prog'));});});
 var caps={};document.querySelectorAll('input.cap').forEach(function(i){var v=parseInt(i.value,10);if(!isNaN(v)&&v>0)caps[i.getAttribute('data-prog')]=v;});
 document.getElementById('save').disabled=true;document.getElementById('msg').textContent=' Saving...';document.getElementById('msg').className='';
 fetch(API+'/xinnix/enroll-grid',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({opp:OPP,assignments:asg,purchased:caps,force:!!force})})
  .then(function(r){return r.json().then(function(j){return {status:r.status,body:j};});}).then(function(res){
   var m=document.getElementById('msg');document.getElementById('save').disabled=false;
   if(res.status===409&&res.body.error==='payment_required'){
    if(confirm((res.body.message||'This deal is not marked paid.')+'\n\nEnroll anyway?')){save(true);}
    else{m.textContent=' Not saved - deal not marked Won/paid.';m.className='err';showToast('Not saved: deal not paid');}
    return;}
   if(res.status===409){var v=(res.body.violations||[]).map(function(x){return x.program+' ('+x.requested+' of '+x.purchased+')';}).join(', ');
    m.textContent=' Over purchased quantity: '+v;m.className='err';showToast('Too many for: '+v);refreshCaps();return;}
   if(res.body.error){m.textContent=' Save failed: '+res.body.error;m.className='err';showToast('Save failed');return;}
   var n=(res.body.changes||[]).length;
   m.textContent=' Saved. '+n+' change(s) applied.';m.className='ok';
   showToast(n>0?('Saved! '+n+' enrollment change(s) applied.'):'Saved. Nothing changed.');setTimeout(load,900);
  }).catch(function(e){var m=document.getElementById('msg');m.textContent=' Save failed: '+e;m.className='err';document.getElementById('save').disabled=false;showToast('Save failed: '+e);});
}
function showToast(t){var e=document.getElementById('toast');e.textContent=t;e.style.background=/fail|too many|over/i.test(t)?'#c0392b':'#2e8b57';e.style.display='block';clearTimeout(e._t);e._t=setTimeout(function(){e.style.display='none';},2800);
}
function xval(id){return (document.getElementById(id).value||'').trim();}
function esc2(s){return String(s).replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;');}
function addStudent(){
 var f=xval('sf'),l=xval('sl'),e=xval('se'),p=xval('sp');var am=document.getElementById('addmsg');
 if(!e||(!f&&!l)){am.textContent=' Enter a name and an email.';am.className='err';return;}
 if(!DATA){am.textContent=' Load a deal first.';am.className='err';return;}
 am.textContent=' Adding...';am.className='';
 fetch(API+'/xinnix/enroll-grid/add-student',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({opp:OPP,firstName:f,lastName:l,email:e,phone:p})})
  .then(function(r){return r.json();}).then(function(d){
   if(d.error){am.textContent=' '+d.error;am.className='err';return;}
   if(document.querySelector('#grid tbody tr[data-cid="'+d.contact_id+'"]')){am.textContent=' That student is already on the grid.';am.className='';return;}
   var tb=document.querySelector('#grid tbody');var tr=document.createElement('tr');tr.setAttribute('data-cid',d.contact_id);
   var h='<td class="name">'+esc2(d.name)+'<span class="role">Student'+(d.created?' (new)':'')+'</span></td>';
   DATA.programs.forEach(function(pg){h+='<td class="prog"><input type="checkbox" data-prog="'+esc2(pg)+'" onchange="refreshCaps()"></td>';});
   tr.innerHTML=h;tb.appendChild(tr);
   ['sf','sl','se','sp'].forEach(function(id){document.getElementById(id).value='';});
   am.textContent=' Added '+d.name+'. Check their program(s), then Save.';am.className='ok';refreshCaps();
  }).catch(function(err){am.textContent=' Failed: '+err;am.className='err';});
}
if(document.getElementById('gate').style.display==='none'){load();}
</script></body></html>"""


@app.route("/xinnix/opp-search", methods=["GET"])
def xinnix_opp_search():
    """Search opportunities by name/company for the picker launcher."""
    if not XINNIX_GHL_TOKEN:
        return jsonify({"error": "missing token"}), 500
    q = (request.args.get("q") or "").strip()
    if len(q) < 2:
        return jsonify({"results": []})
    headers = {**XINNIX_GHL_HEADERS, "Authorization": f"Bearer {XINNIX_GHL_TOKEN}"}
    r = requests.get(f"{XINNIX_GHL_BASE}/opportunities/search", headers=headers,
                     params={"location_id": XINNIX_LOCATION_ID, "q": q, "limit": 12}, timeout=25)
    opps = r.json().get("opportunities", []) if r.status_code == 200 else []
    return jsonify({"results": [{"id": o.get("id"), "name": o.get("name")} for o in opps]})


@app.route("/xinnix/enrollment-picker", methods=["GET"])
def xinnix_enrollment_picker():
    return XINNIX_PICKER_HTML, 200, {"Content-Type": "text/html; charset=utf-8"}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))
