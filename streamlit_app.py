"""
ATRIA — the live triage board, as a Streamlit app.

This is the deployable face of the same engine that `make demo` runs. The
FastAPI version pushes state over a websocket; Streamlit reruns instead, so the
clock is advanced a few events at a time inside an auto-refreshing fragment.
Everything below the presentation layer is the identical code path: Layer 0
gates, Layer 1 scores, Layer 2 re-ranks, Layer 3 records.
"""
from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="ATRIA · live triage board",
                   page_icon="🩺", layout="wide",
                   initial_sidebar_state="expanded")

from data.loaders.synthetic import generate, surge_missing_rate   # noqa: E402
from layer1.model import AcuityScorer                             # noqa: E402
from service import decision_window, forecast                      # noqa: E402
from service.clock import build_events                            # noqa: E402
from service.queue import QueueEngine                             # noqa: E402

ESI_LABELS = {1: "Resuscitation", 2: "Emergent", 3: "Urgent",
              4: "Less urgent", 5: "Non-urgent"}

REASON_CODES = ["reassessed_at_bedside", "clinically_well", "known_baseline",
                "artefact", "resource_constraint", "other"]

CSS = """
<style>
  #MainMenu, footer {visibility:hidden}
  .block-container{padding-top:2.1rem;max-width:1350px}
  .atria-h{font-family:ui-monospace,Menlo,monospace;font-size:11px;letter-spacing:.14em;
           text-transform:uppercase;color:#72837F;margin:0 0 6px}
  .lanebar{display:flex;gap:18px;flex-wrap:wrap;font-family:ui-monospace,Menlo,monospace;
           font-size:11px;color:#72837F;padding:8px 0;border-top:1px solid #26352F;
           border-bottom:1px solid #26352F;margin-bottom:6px}
  .lanebar b{color:#98A9A5;font-weight:500}
  .tick{font-family:ui-monospace,Menlo,monospace;font-size:11px;color:#72837F;
        line-height:1.9;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .tick .arrived b{color:#98A9A5}.tick .seen b{color:#45C4B2}
  .tick .left b{color:#72837F}.tick .escalated b{color:#E8903F}
  .row{display:grid;grid-template-columns:52px minmax(0,1fr) auto;gap:14px;
       padding:11px 14px;margin-bottom:7px;background:#15201E;border:1px solid #26352F;
       border-left:3px solid transparent}
  .row.ESCALATED{border-left-color:#E8903F}
  .row.AWAITING{border-left-color:#45C4B2}
  .row.red{border-left-color:#E5766A}
  .row.abstain{border-left-color:#E5766A;background:linear-gradient(90deg,rgba(229,118,106,.08),#15201E 240px)}
  .row.treat{opacity:.5;border-left-color:#72837F}
  .band{font-family:ui-monospace,Menlo,monospace;font-size:23px;line-height:1;color:#E7EDEA}
  .band small{display:block;font-size:9px;color:#E8903F;margin-top:4px}
  .who{font-weight:600;font-size:14.5px;color:#E7EDEA}
  .who .age{color:#72837F;font-weight:400;font-family:ui-monospace,Menlo,monospace;
            font-size:11px;margin-left:7px}
  .lane{font-family:ui-monospace,Menlo,monospace;font-size:9px;letter-spacing:.08em;
        padding:1px 5px;border:1px solid #26352F;color:#72837F;margin-right:6px}
  .lane.RESUS{border-color:#E5766A;color:#E5766A}
  .lane.ACUTE{border-color:#E8903F;color:#E8903F}
  .tkt{font-family:ui-monospace,Menlo,monospace;font-size:10.5px;color:#45C4B2;
       border:1px solid #26352F;padding:1px 5px;margin-right:7px}
  .why{color:#98A9A5;font-size:12.5px;margin-top:3px}
  .tags{margin-top:6px;display:flex;gap:5px;flex-wrap:wrap}
  .tag{font-family:ui-monospace,Menlo,monospace;font-size:9px;letter-spacing:.05em;
       padding:2px 6px;border:1px solid #26352F;color:#72837F}
  .tag.red{border-color:#E5766A;color:#E5766A}
  .tag.meas{border-color:#E8903F;color:#E8903F}
  .tag.HIGH{border-color:#45C4B2;color:#45C4B2}
  .tag.LOW{border-color:#E5766A;color:#E5766A}
  .abst{margin-top:6px;padding:6px 9px;border-left:2px solid #E5766A;
        background:rgba(229,118,106,.09);font-family:ui-monospace,Menlo,monospace;
        font-size:10.5px;color:#E5766A;line-height:1.5}
  .meta{text-align:right;font-family:ui-monospace,Menlo,monospace;font-size:10.5px;
        color:#72837F;white-space:nowrap}
  .meta .ov{color:#E8903F}
</style>
"""


@st.cache_resource(show_spinner="Training the acuity scorer…")
def load_scorer() -> AcuityScorer:
    """Trained once per container. 1500 patients keeps this inside 1 GB of RAM."""
    return AcuityScorer().fit(generate(1500, seed=3))


def new_shift(surge: float) -> None:
    rate = surge_missing_rate(0.18, surge)
    ds = generate(40, seed=st.session_state.shift_seed, hours=3.0, missing_rate=rate)
    st.session_state.events = build_events(ds, surge=surge)
    st.session_state.cursor = 0
    st.session_state.engine = QueueEngine(load_scorer(), slots=3)
    st.session_state.engine.degraded = st.session_state.get("degraded", False)
    st.session_state.missing_rate = rate


def init(surge: float) -> None:
    if "engine" not in st.session_state:
        st.session_state.shift_seed = 21
        new_shift(surge)
        # warm start: a board that opens empty looks broken, and the first
        # arrivals carry no history for Layer 2 to reason about yet
        advance(90)


def advance(step: int) -> None:
    eng, events = st.session_state.engine, st.session_state.events
    cur = st.session_state.cursor
    for e in events[cur:cur + step]:
        eng.on_arrival(e) if e.kind == "arrival" else eng.on_vitals(e)
    st.session_state.cursor = cur + step
    if st.session_state.cursor >= len(events):
        st.session_state.shift_seed += 1
        new_shift(st.session_state.get("surge", 1.0))


def render_row(r: dict) -> str:
    treat = r["state"] == "IN TREATMENT"
    cls = " ".join(["row", "treat" if treat else r["state"],
                    "red" if r["red_flag"] else "",
                    "abstain" if r.get("abstained") else ""])
    from_band = f"<small>&uarr; {r['band_before']}</small>" if r["band_before"] else ""
    why = r["red_flag"] or " · ".join(r["reasons"]) or r.get("needs_measurement") or "—"
    age = f"{round(r['age'])}{r['gender'] or ''}" if r.get("age") is not None else "—"

    tags = []
    if r["red_flag"]:
        tags.append('<span class="tag red">RED FLAG</span>')
    if r.get("needs_measurement") and not r["red_flag"]:
        tags.append('<span class="tag meas">MEASURE</span>')
    tags.append(f'<span class="tag {r["confidence"]}">TRIAGE {r["confidence"]}</span>')
    dx = r.get("diagnostic_confidence", "HIGH")
    tags.append(f'<span class="tag {dx}">DIAGNOSIS {dx}</span>')
    if r.get("pathway"):
        tags.append(f'<span class="tag">{r["pathway"]}</span>')
    if r["missing"]:
        tags.append(f'<span class="tag">missing: {", ".join(r["missing"])}</span>')

    blocks = ""
    if r.get("abstained"):
        blocks += f'<div class="abst">{r["abstain_reason"] or "system abstained"}</div>'
    for c in r.get("conflicts", []):
        blocks += f'<div class="abst">TREATMENT CONFLICT · {c}</div>'

    right = "in a bay" if treat else (
        f'<div class="ov">{r["overdue_by"]}m past safe wait</div>' if r["overdue_by"] > 0 else "")
    return (
        f'<div class="{cls}"><div class="band">{r["band"]}{from_band}</div>'
        f'<div><div class="who"><span class="lane {r.get("lane","")}">{r.get("lane","")}</span>'
        f'<span class="tkt">{r["ticket"]}</span>{r["complaint"]}'
        f'<span class="age">{age}</span></div>'
        f'<div class="why">{why}</div><div class="tags">{"".join(tags)}</div>{blocks}</div>'
        f'<div class="meta">waited {r["waited"]}m{right}</div></div>'
    )


# ---------------------------------------------------------------- sidebar ---
st.markdown(CSS, unsafe_allow_html=True)

with st.sidebar:
    st.markdown("### ATRIA")
    st.caption("A live queue, not a label. Emergency department triage that "
               "re-ranks continuously and never de-escalates on its own.")

    running = st.toggle("Run the shift", value=True, key="running")
    speed = st.select_slider("Events per tick", [1, 2, 4, 8], value=2, key="speed")
    surge = st.select_slider("Arrival volume", [1.0, 2.0, 3.0], value=1.0,
                             format_func=lambda v: f"{v:.0f}× normal", key="surge")

    degraded = st.toggle("Kill the model service", value=False,
                         help="Scenario 06 — Layer 0 keeps gating deterministically.")
    st.session_state.degraded = degraded
    if "engine" in st.session_state:
        st.session_state.engine.degraded = degraded

    if st.button("Restart the shift", width='stretch'):
        st.session_state.shift_seed = st.session_state.get("shift_seed", 21) + 1
        new_shift(surge)

    st.divider()
    st.caption(f"Missing-vitals rate this shift: "
               f"**{st.session_state.get('missing_rate', 0.18):.0%}** — surge degrades "
               f"data quality, which is when a model is most tempted to read "
               f"missingness as signal.")

init(surge)


def tab_assessment() -> None:
    """Blind nurse-first triage. ATRIA stays locked until the nurse commits."""
    engine = st.session_state.engine
    if st.session_state.get("running", True):
        advance(int(st.session_state.get("speed", 2)))
    snap = engine.snapshot()

    cols = st.columns(6)
    for col, (label, value) in zip(cols, [
        ("Waiting", snap["waiting"]),
        ("In treatment", f'{snap["in_treatment"]}/{snap["slots"]}'),
        ("Seen", snap["seen"]),
        ("Escalated", snap["escalated"]),
        ("Abstained", snap["abstained"]),
        ("Clock", snap["now"][11:16]),
    ]):
        col.metric(label, value)

    if snap["degraded"]:
        st.error("**DEGRADED MODE** · model service unavailable · "
                 "Layer 0 red-flag gate still active", icon="⚠️")

    lanes = " &nbsp; ".join(f"{k} <b>{v}</b>" for k, v in snap["lanes"].items())
    st.markdown(f'<div class="lanebar">{lanes} &nbsp;&nbsp;·&nbsp;&nbsp; '
                f'scoring p95 <b>{snap["p95_ms"] or "–"} ms</b></div>',
                unsafe_allow_html=True)

    queue_col, work_col, record_col = st.columns([1.25, 1.15, 0.95])

    with queue_col:
        st.markdown('<div class="atria-h">Attention queue</div>', unsafe_allow_html=True)
        st.caption("Rank is not ESI. It is a live sequence; ESI is what the nurse signs.")
        if not snap["rows"]:
            st.caption("Waiting for the first arrival…")
        for r in snap["rows"][:12]:
            st.markdown(render_row(r), unsafe_allow_html=True)

    waiting = [r for r in snap["rows"] if r["state"] != "IN TREATMENT"]

    with work_col:
        st.markdown('<div class="atria-h">Nurse assessment</div>', unsafe_allow_html=True)
        if not waiting:
            st.caption("Nobody waiting.")
            return

        pick = st.selectbox("Patient", [r["ticket"] for r in waiting],
                            label_visibility="collapsed", key="assess_pick")
        row = next((r for r in waiting if r["ticket"] == pick), waiting[0])
        sid = row["stay_id"]
        a = engine.workflow.open(sid)
        view = a.visible_to_nurse()

        age = f"{round(row['age'])}{row['gender'] or ''}" if row.get("age") is not None else "—"
        st.markdown(f"**{row['complaint']}** · {age} · waited {row['waited']}m")

        window = decision_window.seconds_for(
            flow_state=st.session_state.get("flow_state", "Steady"),
            esi=row["band"], age=row.get("age"))
        st.caption(f"Decision window {window}s · expiry prompts and logs; "
                   f"it never assigns an ESI.")

        if not view["revealed"]:
            st.info("ATRIA is locked. Choose an ESI first — the recommendation "
                    "is not on this page until you do.", icon="🔒")
            esi_cols = st.columns(5)
            for i, col in enumerate(esi_cols, start=1):
                if col.button(f"{i}", key=f"esi_{sid}_{i}", width='stretch',
                              help=ESI_LABELS[i]):
                    engine.nurse_assess(sid, i)
                    engine.reveal(sid)
                    st.rerun(scope="fragment")
            st.caption(" · ".join(f"{i} {ESI_LABELS[i]}" for i in range(1, 6)))
        else:
            outcome = view.get("outcome")
            c1, c2 = st.columns(2)
            c1.metric("Nurse ESI", view["nurse_esi"])
            c2.metric("ATRIA", view["atria_esi"] if view["atria_esi"] else "abstained")

            if outcome == "match":
                st.success("ESI match", icon="✅")
            elif outcome == "nurse_escalation":
                st.warning("You are more urgent than ATRIA. Your view stands; "
                           "the difference is logged. No reason required.", icon="⬆️")
            elif outcome == "nurse_downgrade":
                st.warning("You are less urgent than ATRIA. A reason is required "
                           "before sign-off.", icon="⬇️")
            elif outcome == "guardrail":
                st.error("Layer 0 critical guardrail is active. Going less urgent "
                         "requires a reason and escalates to the charge nurse.", icon="🚨")
            elif outcome == "uncertain":
                st.warning("ATRIA abstained — essential data missing. Complete the "
                           "vital set, or give a reason to sign off regardless.", icon="❓")

            reason = ""
            if view["needs_reason"]:
                reason = st.selectbox("Reason", REASON_CODES, key=f"why_{sid}")
            label = ("Confirm & send inside" if view["nurse_esi"] <= 2
                     else "Confirm & advance")
            if st.button(label, width='stretch', key=f"fin_{sid}"):
                engine.finalise(sid, clinician="nurse.demo", reason_code=reason)
                st.rerun(scope="fragment")

        if st.button("Report change / worsening", width='stretch',
                     key=f"worse_{sid}"):
            engine.report_change(sid)
            st.rerun(scope="fragment")
        st.caption("Reporting a change clears any sign-off and starts a fresh "
                   "blind assessment. The old recommendation is discarded.")

    with record_col:
        st.markdown('<div class="atria-h">Patient record</div>', unsafe_allow_html=True)
        st.markdown(f"**{row['complaint']}**")
        why = row["red_flag"] or " · ".join(row["reasons"]) or "—"
        st.caption(why)
        if row.get("pathway"):
            st.caption(f"Pathway: {row['pathway']}")
        if row["missing"]:
            st.warning(f"Missing: {', '.join(row['missing'])}", icon="⚠️")
        if row.get("abstained"):
            st.error(row["abstain_reason"] or "system abstained", icon="⛔")
        for c in row.get("conflicts", []):
            st.error(f"Treatment conflict · {c}", icon="⚡")


def tab_operations() -> None:
    """Demand against staffed capacity for the next hour."""
    engine = st.session_state.engine
    snap = engine.snapshot()

    st.markdown('<div class="atria-h">Staffing and connected systems</div>',
                unsafe_allow_html=True)
    left, right = st.columns([1, 1.4])
    with left:
        nurses = st.slider("Nurses available", 1, 12, 6, key="ops_nurses")
        spaces = st.slider("Physical treatment spaces", 4, 40, 20, key="ops_spaces")
        st.markdown("**Connected systems**")
        records = st.toggle("Records", value=True, key="ops_records")
        beds = st.toggle("Beds / spaces", value=True, key="ops_beds")
        roster = st.toggle("Staff roster", value=True, key="ops_roster")
        vitals = st.toggle("Vitals feed", value=True, key="ops_vitals")

    f = forecast.FlowInputs(
        waiting=snap["waiting"], inside=snap["in_treatment"], nurses=nurses,
        arrival_rate_per_hour=13.0, physical_spaces=spaces,
        records_connected=records, beds_connected=beds,
        roster_connected=roster, vitals_connected=vitals)
    out = forecast.project(f)
    st.session_state.flow_state = out.state

    with right:
        m = st.columns(4)
        m[0].metric("Flow state", out.state)
        m[1].metric("Open staffed spaces", out.open_spaces)
        m[2].metric("Wait buffer", f"{out.wait_buffer_minutes:.0f}m")
        m[3].metric("Arrivals / hour", out.arrivals_next_hour)
        st.info(out.explanation, icon="📋")
        for note in out.assumptions:
            st.warning(note, icon="⚠️")

    import pandas as pd
    chart = pd.DataFrame({
        "minutes from now": [p.minute for p in out.points],
        "In treatment": [p.in_treatment for p in out.points],
        "Waiting": [p.waiting for p in out.points],
        "Staffed spaces": [out.staffed_spaces] * len(out.points),
    }).set_index("minutes from now")
    st.line_chart(chart, color=["#45C4B2", "#E8903F", "#E5766A"], height=280)
    st.caption("In treatment is capped at staffed spaces — you cannot treat more "
               "people than you have staffed places for. Waiting is not capped, "
               "because a queue can grow past capacity, and hiding that would "
               "hide the one thing worth seeing. A staffed space is physically "
               "available *and* safely staffed; it is not a licensed bed.")
    st.caption("This informs ordering within an ESI band only. It can never move "
               "a patient across one.")


def tab_history() -> None:
    """Audit log first, general log second."""
    engine = st.session_state.engine
    intact, note = engine.audit.verify()
    st.markdown('<div class="atria-h">Audit log</div>', unsafe_allow_html=True)
    st.caption(f"{'✅' if intact else '❌'} {note}")

    mode = st.radio("View", ["Audit log", "General log"], horizontal=True,
                    label_visibility="collapsed", key="hist_mode")
    decision_kinds = {"nurse_assessment", "atria_reveal", "sign_off",
                      "override", "worsening_reported", "abstain"}

    rows = []
    for e in reversed(engine.audit.entries):
        if mode == "Audit log" and e.kind not in decision_kinds:
            continue
        rows.append({
            "seq": e.seq, "at": str(e.at)[11:19], "event": e.kind,
            "stay": e.stay_id,
            "detail": ", ".join(f"{k}={v}" for k, v in e.payload.items()
                                if v not in (None, "", [], False))[:90],
            "hash": e.hash[:10], "prev": e.prev_hash[:10],
        })
    if rows:
        import pandas as pd
        st.dataframe(pd.DataFrame(rows), width='stretch', height=420,
                     hide_index=True)
    else:
        st.caption("No events yet.")
    st.caption("Append-only. Each entry embeds the hash of the one before it, so "
               "an edit or deletion anywhere breaks the chain and is detectable. "
               "Corrections create a new linked event; nothing is ever rewritten.")


@st.fragment(run_every=2)
def board() -> None:
    """
    The board, redrawn on a timer.

    The refresh has to live here, on the thing being redrawn. An empty fragment
    calling st.rerun() loops forever without ever finishing the script, which
    renders as a permanently blank page.
    """
    assessment, operations, history = st.tabs(
        ["Assessment", "Operations & Flow", "History"])
    with assessment:
        tab_assessment()
    with operations:
        tab_operations()
    with history:
        tab_history()


board()
