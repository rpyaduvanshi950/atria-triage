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

ESI_MEANING = {
    1: "Needs a life-saving intervention now",
    2: "High risk, or time-critical — cannot wait",
    3: "Stable enough to wait briefly; likely several resources",
    4: "Stable; likely one resource",
    5: "Stable; likely nothing beyond an examination",
}

REASON_LABELS = {
    "reassessed_at_bedside": "I reassessed at the bedside",
    "clinically_well": "Vitals look alarming, the patient does not",
    "known_baseline": "These readings are normal for this patient",
    "artefact": "The reading is an artefact",
    "resource_constraint": "Triage under genuine scarcity",
    "other": "Other",
}

#: Adult reference ranges, shown beside each vital so a number means something.
VITAL_REF = {
    "heartrate": ("HR", "50–110", "bpm"),
    "sbp": ("SBP", "90–180", "mmHg"),
    "o2sat": ("SpO₂", "≥94", "%"),
    "resprate": ("RR", "10–30", "/min"),
    "temperature": ("Temp", "36–38.5", "°C"),
}

CSS = """
<style>
  #MainMenu, footer {visibility:hidden}
  .block-container{padding-top:1.6rem;max-width:1400px}

  /* section labels */
  .atria-h{font-family:ui-monospace,Menlo,monospace;font-size:10.5px;letter-spacing:.16em;
           text-transform:uppercase;color:#72837F;margin:0 0 8px;
           border-bottom:1px solid #26352F;padding-bottom:6px}

  /* the step flow across the top of the assessment */
  .steps{display:flex;gap:0;margin:0 0 14px}
  .step{flex:1;padding:9px 12px;border:1px solid #26352F;border-right:none;
        font-family:ui-monospace,Menlo,monospace;font-size:11px;color:#5C6D69}
  .step:last-child{border-right:1px solid #26352F}
  .step b{display:block;font-size:12.5px;color:#72837F;margin-bottom:2px;font-weight:500}
  .step.on{background:#15201E;border-color:#45C4B2}
  .step.on b{color:#45C4B2}
  .step.on{color:#98A9A5}
  .step.done b{color:#98A9A5}

  .lanebar{display:flex;gap:18px;flex-wrap:wrap;font-family:ui-monospace,Menlo,monospace;
           font-size:11px;color:#72837F;padding:9px 0;border-top:1px solid #26352F;
           border-bottom:1px solid #26352F;margin-bottom:10px}
  .lanebar b{color:#98A9A5;font-weight:500}

  .tick{font-family:ui-monospace,Menlo,monospace;font-size:11px;color:#72837F;
        line-height:1.85;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .tick .arrived b{color:#98A9A5}.tick .seen b{color:#45C4B2}
  .tick .left b{color:#5C6D69}.tick .escalated b{color:#E8903F}

  /* queue rows */
  .row{display:grid;grid-template-columns:46px minmax(0,1fr);gap:12px;
       padding:10px 12px;margin-bottom:6px;background:#15201E;border:1px solid #26352F;
       border-left:3px solid transparent}
  .row.ESCALATED{border-left-color:#E8903F}
  .row.AWAITING{border-left-color:#45C4B2}
  .row.red{border-left-color:#E5766A}
  .row.abstain{border-left-color:#E5766A;background:linear-gradient(90deg,rgba(229,118,106,.09),#15201E 260px)}
  .row.treat{opacity:.42;border-left-color:#5C6D69}
  .row.sel{outline:1px solid #45C4B2;outline-offset:1px}
  .band{font-family:ui-monospace,Menlo,monospace;font-size:21px;line-height:1;color:#E7EDEA}
  .band small{display:block;font-size:9px;color:#E8903F;margin-top:3px}
  .who{font-weight:600;font-size:13.5px;color:#E7EDEA;line-height:1.3}
  .who .age{color:#72837F;font-weight:400;font-family:ui-monospace,Menlo,monospace;
            font-size:10.5px;margin-left:6px}
  .lane{font-family:ui-monospace,Menlo,monospace;font-size:8.5px;letter-spacing:.09em;
        padding:1px 5px;border:1px solid #26352F;color:#72837F;margin-right:5px}
  .lane.RESUS{border-color:#E5766A;color:#E5766A}
  .lane.ACUTE{border-color:#E8903F;color:#E8903F}
  .tkt{font-family:ui-monospace,Menlo,monospace;font-size:10px;color:#45C4B2;
       border:1px solid #26352F;padding:1px 5px;margin-right:6px}
  .why{color:#98A9A5;font-size:11.5px;margin-top:3px;line-height:1.45}
  .tags{margin-top:5px;display:flex;gap:4px;flex-wrap:wrap}
  .tag{font-family:ui-monospace,Menlo,monospace;font-size:8.5px;letter-spacing:.05em;
       padding:1px 5px;border:1px solid #26352F;color:#72837F}
  .tag.red{border-color:#E5766A;color:#E5766A}
  .tag.meas{border-color:#E8903F;color:#E8903F}
  .tag.HIGH{border-color:#45C4B2;color:#45C4B2}
  .tag.LOW{border-color:#E5766A;color:#E5766A}
  .wait{float:right;font-family:ui-monospace,Menlo,monospace;font-size:10px;color:#5C6D69}
  .wait .ov{color:#E8903F}

  /* vitals grid in the record panel */
  .vitals{display:grid;grid-template-columns:repeat(2,1fr);gap:6px;margin-top:4px}
  .v{background:#15201E;border:1px solid #26352F;padding:7px 9px}
  .v .k{font-family:ui-monospace,Menlo,monospace;font-size:9px;letter-spacing:.09em;
        color:#5C6D69;text-transform:uppercase}
  .v .n{font-family:ui-monospace,Menlo,monospace;font-size:17px;color:#E7EDEA;line-height:1.25}
  .v .r{font-family:ui-monospace,Menlo,monospace;font-size:9px;color:#5C6D69}
  .v.bad{border-color:#E5766A}      .v.bad .n{color:#E5766A}
  .v.warn{border-color:#E8903F}     .v.warn .n{color:#E8903F}
  .v.gone{border-style:dashed}      .v.gone .n{color:#E8903F;font-size:12px}

  /* comparison cards after reveal */
  .cmp{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:2px 0 10px}
  .cmp .c{background:#15201E;border:1px solid #26352F;padding:11px 13px;text-align:center}
  .cmp .c .k{font-family:ui-monospace,Menlo,monospace;font-size:9px;letter-spacing:.1em;
             color:#5C6D69;text-transform:uppercase}
  .cmp .c .n{font-size:27px;font-weight:600;color:#E7EDEA;line-height:1.15}
  .cmp .c .l{font-size:11px;color:#72837F}
  .cmp .c.nurse{border-color:#45C4B2}
  .abst{margin-top:6px;padding:7px 10px;border-left:2px solid #E5766A;
        background:rgba(229,118,106,.09);font-family:ui-monospace,Menlo,monospace;
        font-size:10.5px;color:#E5766A;line-height:1.5}
  .locked{background:#15201E;border:1px dashed #45C4B2;padding:13px 15px;
          color:#98A9A5;font-size:12.5px;line-height:1.55}
  .locked b{color:#45C4B2}
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


#: Bump when the engine's shape changes. Session state outlives a code deploy —
#: Streamlit Cloud pulls new code and reruns, but anything already in
#: st.session_state was built by the *previous* version and keeps its old shape.
SESSION_VERSION = "2026-08-27.blind-workflow"

#: Attributes the current code expects an engine to have. Checked directly, so a
#: forgotten version bump self-heals instead of crashing every open session.
REQUIRED_ENGINE_ATTRS = ("workflow", "audit", "in_treatment", "ticker")


def _session_is_stale() -> bool:
    engine = st.session_state.get("engine")
    if engine is None:
        return True
    if st.session_state.get("_session_version") != SESSION_VERSION:
        return True
    return any(not hasattr(engine, a) for a in REQUIRED_ENGINE_ATTRS)


def engine() -> QueueEngine:
    """
    The only way to reach the engine.

    Every read validates, because `board()` is a fragment: fragments rerun
    *without re-executing the module*, so a guard placed in the script body is
    simply never reached on the reruns that matter. That is what made the first
    attempt at this fix useless — it ran once at startup and never again.
    """
    if _session_is_stale():
        init(st.session_state.get("surge", 1.0))
    return st.session_state.engine


def init(surge: float) -> None:
    if not _session_is_stale():
        return
    # rebuild from scratch; keep sidebar widget values, drop everything derived
    for key in ("engine", "events", "cursor", "missing_rate"):
        st.session_state.pop(key, None)
    st.session_state.shift_seed = 21
    st.session_state._session_version = SESSION_VERSION
    new_shift(surge)
    # warm start: a board that opens empty looks broken, and the first
    # arrivals carry no history for Layer 2 to reason about yet
    advance(90)


def advance(step: int) -> None:
    eng, events = engine(), st.session_state.events
    cur = st.session_state.cursor
    for e in events[cur:cur + step]:
        eng.on_arrival(e) if e.kind == "arrival" else eng.on_vitals(e)
    st.session_state.cursor = cur + step
    if st.session_state.cursor >= len(events):
        st.session_state.shift_seed += 1
        new_shift(st.session_state.get("surge", 1.0))


def render_row(r: dict, selected: bool = False) -> str:
    """One queue row. Compact enough that twelve fit without scrolling."""
    treat = r["state"] == "IN TREATMENT"
    cls = " ".join(["row", "treat" if treat else r["state"],
                    "red" if r["red_flag"] else "",
                    "abstain" if r.get("abstained") else "",
                    "sel" if selected else ""])
    from_band = f"<small>&uarr;{r['band_before']}</small>" if r["band_before"] else ""
    why = r["red_flag"] or " · ".join(r["reasons"]) or r.get("needs_measurement") or "—"
    age = f"{round(r['age'])}{r['gender'] or ''}" if r.get("age") is not None else "—"

    tags = []
    if r["red_flag"]:
        tags.append('<span class="tag red">RED FLAG</span>')
    if r.get("abstained"):
        tags.append('<span class="tag red">ABSTAIN</span>')
    if r.get("needs_measurement") and not r["red_flag"]:
        tags.append('<span class="tag meas">MEASURE</span>')
    if r.get("worsening"):
        tags.append('<span class="tag meas">WORSENED</span>')
    tags.append(f'<span class="tag {r["confidence"]}">TRIAGE {r["confidence"]}</span>')
    dx = r.get("diagnostic_confidence", "HIGH")
    tags.append(f'<span class="tag {dx}">DX {dx}</span>')
    if r["missing"]:
        tags.append(f'<span class="tag meas">no {", ".join(r["missing"][:2])}</span>')

    over = (f'<span class="ov"> · {r["overdue_by"]}m over</span>'
            if r["overdue_by"] > 0 else "")
    wait = ("in a bay" if treat else f'{r["waited"]}m{over}')
    return (
        f'<div class="{cls}"><div class="band">{r["band"]}{from_band}</div>'
        f'<div><div class="who"><span class="wait">{wait}</span>'
        f'<span class="lane {r.get("lane","")}">{r.get("lane","")}</span>'
        f'<span class="tkt">{r["ticket"]}</span>{r["complaint"]}'
        f'<span class="age">{age}</span></div>'
        f'<div class="why">{why[:96]}</div><div class="tags">{"".join(tags)}</div></div></div>'
    )


def render_vitals(row: dict) -> str:
    """Vitals with their reference range beside them, so a number means something."""
    cells = []
    for key, (label, ref, unit) in VITAL_REF.items():
        value = row.get("vitals", {}).get(key)
        missing = value is None
        tone = "gone" if missing else ""
        shown = "not taken" if missing else f"{value:g}"
        cells.append(
            f'<div class="v {tone}"><div class="k">{label}</div>'
            f'<div class="n">{shown}</div>'
            f'<div class="r">{"must be measured" if missing else f"normal {ref} {unit}"}</div></div>')
    return f'<div class="vitals">{"".join(cells)}</div>'


def step_bar(stage: str) -> str:
    """Where the nurse is in the blind cycle. Three states, always visible."""
    order = ["awaiting_nurse", "compared", "signed"]
    names = [("1", "Assess", "Choose an ESI. ATRIA is hidden."),
             ("2", "Compare", "See ATRIA and resolve the difference."),
             ("3", "Sign off", "Confirm, with a reason where required.")]
    here = order.index(stage) if stage in order else 0
    out = []
    for i, (num, name, hint) in enumerate(names):
        cls = "step on" if i == here else ("step done" if i < here else "step")
        out.append(f'<div class="{cls}"><b>{num} · {name}</b>{hint}</div>')
    return f'<div class="steps">{"".join(out)}</div>'


# ------------------------------------------------------------------ sidebar --
st.markdown(CSS, unsafe_allow_html=True)

with st.sidebar:
    st.markdown("## ATRIA")
    st.caption("**A live queue, not a label.** Triage that reorders attention "
               "continuously, so the patient who is *becoming* sickest is seen "
               "sooner. It supports the nurse — it never prescribes, and it can "
               "never lower anyone's priority on its own.")

    st.divider()
    st.markdown("**Shift controls**")
    running = st.toggle("Run the shift", value=True, key="running",
                        help="Pause to study the board without it moving under you.")
    speed = st.select_slider("Speed", [1, 2, 4, 8], value=2, key="speed",
                             format_func=lambda v: f"{v}× ",
                             help="Events processed per two-second tick.")
    surge = st.select_slider("Arrival volume", [1.0, 2.0, 3.0], value=1.0, key="surge",
                             format_func=lambda v: f"{v:.0f}× normal",
                             help="Surge also degrades data quality — less time per "
                                  "patient means more blank fields.")

    st.divider()
    st.markdown("**Break something**")
    degraded = st.toggle("Kill the model service", value=False, key="degraded",
                         help="Layer 0 keeps gating deterministically, offline.")
    if st.button("Restart the shift", width='stretch'):
        st.session_state.shift_seed = st.session_state.get("shift_seed", 21) + 1
        new_shift(surge)

    st.divider()
    st.caption(f"Missing-vitals rate this shift **{st.session_state.get('missing_rate', 0.18):.0%}** "
               f"· flow **{st.session_state.get('flow_state', 'Steady')}**")

init(surge)
if "engine" in st.session_state:
    engine().degraded = degraded


# ------------------------------------------------------------- assessment ---
def tab_assessment() -> None:
    eng = engine()
    if st.session_state.get("running", True):
        advance(int(st.session_state.get("speed", 2)))
    snap = eng.snapshot()

    top = st.columns(6)
    for col, (label, value, hint) in zip(top, [
        ("Waiting", snap["waiting"], "Patients in the queue right now."),
        ("In a bay", f'{snap["in_treatment"]}/{snap["slots"]}',
         "Treatment spaces occupied. When one frees, the highest-priority "
         "waiting patient is taken through."),
        ("Seen", snap["seen"], "Treated and discharged this shift."),
        ("Escalated", snap["escalated"],
         "Times a machine raised someone's priority. It can never lower one."),
        ("Abstained", snap["abstained"],
         "Times ATRIA refused to score — too little data, or the picture fits "
         "more than one pathway."),
        ("Clock", snap["now"][11:16], "Simulated department time."),
    ]):
        col.metric(label, value, help=hint)

    if snap["degraded"]:
        st.error("**Model service down.** Layer 0 is still gating on hard rules, "
                 "offline. Every score drops to LOW confidence, because the thing "
                 "that produced confidence is gone.", icon="⚠️")

    lanes = " &nbsp; ".join(f"{k} <b>{v}</b>" for k, v in snap["lanes"].items())
    st.markdown(f'<div class="lanebar">{lanes} &nbsp;·&nbsp; scoring p95 '
                f'<b>{snap["p95_ms"] or "–"} ms</b> &nbsp;·&nbsp; '
                f'RESUS never queues behind anyone</div>', unsafe_allow_html=True)

    waiting = [r for r in snap["rows"] if r["state"] != "IN TREATMENT"]
    sel_ticket = st.session_state.get("assess_pick")

    queue_col, work_col, record_col = st.columns([1.15, 1.15, 1.0])

    with queue_col:
        st.markdown('<div class="atria-h">Attention queue</div>', unsafe_allow_html=True)
        st.caption("Rank is **not** ESI. ESI is the acuity the nurse signs; rank is "
                   "a live sequence that changes as people wait and worsen.")
        if not snap["rows"]:
            st.caption("Waiting for the first arrival…")
        for r in snap["rows"][:12]:
            st.markdown(render_row(r, selected=(r["ticket"] == sel_ticket)),
                        unsafe_allow_html=True)

    if not waiting:
        with work_col:
            st.markdown('<div class="atria-h">Nurse assessment</div>',
                        unsafe_allow_html=True)
            st.caption("Nobody waiting.")
        return

    with work_col:
        st.markdown('<div class="atria-h">Nurse assessment</div>', unsafe_allow_html=True)
        pick = st.selectbox("Patient", [r["ticket"] for r in waiting],
                            label_visibility="collapsed", key="assess_pick")
        row = next((r for r in waiting if r["ticket"] == pick), waiting[0])
        sid = row["stay_id"]
        a = eng.workflow.open(sid)
        view = a.visible_to_nurse()

        st.markdown(step_bar(view["stage"]), unsafe_allow_html=True)

        if not view["revealed"]:
            st.markdown(
                '<div class="locked"><b>ATRIA is locked.</b> Its recommendation is '
                'not on this page — not hidden, <i>absent</i> — until you choose. '
                'Show a clinician a number first and they converge on it; this is '
                'the cheapest defence against that.</div>', unsafe_allow_html=True)
            st.write("")
            for i in range(1, 6):
                if st.button(f"**{i}** · {ESI_LABELS[i]}", key=f"esi_{sid}_{i}",
                             width='stretch', help=ESI_MEANING[i]):
                    eng.nurse_assess(sid, i)
                    eng.reveal(sid)
                    st.rerun(scope="fragment")
        else:
            atria = view["atria_esi"]
            st.markdown(
                f'<div class="cmp">'
                f'<div class="c nurse"><div class="k">You</div>'
                f'<div class="n">{view["nurse_esi"]}</div>'
                f'<div class="l">{ESI_LABELS[view["nurse_esi"]]}</div></div>'
                f'<div class="c"><div class="k">ATRIA</div>'
                f'<div class="n">{atria if atria else "—"}</div>'
                f'<div class="l">{ESI_LABELS[atria] if atria else "abstained"}</div></div>'
                f'</div>', unsafe_allow_html=True)

            outcome = view.get("outcome")
            if outcome == "match":
                st.success("**You agree.** Confirm and move on.", icon="✅")
            elif outcome == "nurse_escalation":
                st.warning("**You are more urgent than ATRIA.** Your view stands and "
                           "no reason is required — a clinician escalating is never "
                           "questioned. The difference is logged.", icon="⬆️")
            elif outcome == "nurse_downgrade":
                st.warning("**You are less urgent than ATRIA.** This is the direction "
                           "that can harm someone, so it needs a reason before "
                           "sign-off.", icon="⬇️")
            elif outcome == "guardrail":
                st.error("**A hard rule fired on recorded values.** Going less urgent "
                         "needs a reason and escalates to the charge nurse. No model "
                         "output can suppress this.", icon="🚨")
            elif outcome == "uncertain":
                st.warning("**ATRIA abstained** — essential data is missing, and it "
                           "will not guess. Complete the vitals, or give a reason to "
                           "sign off regardless.", icon="❓")

            reason = ""
            if view["needs_reason"]:
                reason = st.selectbox(
                    "Why?", list(REASON_LABELS), key=f"why_{sid}",
                    format_func=lambda k: REASON_LABELS[k])
            label = ("Confirm & send inside" if view["nurse_esi"] <= 2
                     else "Confirm & advance")
            if st.button(label, width='stretch', key=f"fin_{sid}", type="primary"):
                eng.finalise(sid, clinician="nurse.demo", reason_code=reason)
                st.rerun(scope="fragment")

        st.write("")
        if st.button("⟲ Report change / worsening", width='stretch', key=f"worse_{sid}"):
            eng.report_change(sid)
            st.rerun(scope="fragment")
        st.caption("Clears the sign-off and starts a **fresh blind cycle**. The old "
                   "recommendation is discarded — showing it would anchor the very "
                   "decision this keeps independent.")

    with record_col:
        st.markdown('<div class="atria-h">Patient record</div>', unsafe_allow_html=True)
        age = f"{round(row['age'])}{row['gender'] or ''}" if row.get("age") is not None else "—"
        st.markdown(f"**{row['complaint']}** · {age} · waited {row['waited']}m")
        st.markdown(render_vitals(row), unsafe_allow_html=True)

        st.markdown('<div class="atria-h" style="margin-top:14px">Why this band</div>',
                    unsafe_allow_html=True)
        st.caption(row["red_flag"] or " · ".join(row["reasons"]) or "—")
        if row.get("pathway"):
            st.caption(f"Pathway engaged: **{row['pathway']}** — which of the three "
                       f"gates (lungs, heart, brain) is closing.")
        if row["missing"]:
            st.warning(f"Never measured: {', '.join(row['missing'])}. A missing vital "
                       f"is never read as a normal one.", icon="⚠️")
        if row.get("abstained"):
            st.error(row["abstain_reason"] or "system abstained", icon="⛔")
        for c in row.get("conflicts", []):
            st.error(f"**Treatment conflict** — {c}", icon="⚡")


# -------------------------------------------------------------- operations --
def tab_operations() -> None:
    eng = engine()
    snap = eng.snapshot()

    st.caption("Demand against **staffed capacity** for the next hour. This informs "
               "ordering *within* an ESI band only — it can never move a patient "
               "across one. A busy department does not make a sick patient less sick.")

    left, right = st.columns([1, 1.5])
    with left:
        st.markdown('<div class="atria-h">Staffing</div>', unsafe_allow_html=True)
        nurses = st.slider("Nurses on", 1, 12, 6, key="ops_nurses")
        spaces = st.slider("Physical spaces", 4, 40, 20, key="ops_spaces",
                           help="Rooms that physically exist. Capacity is the "
                                "*lesser* of this and what your nurses can safely cover.")
        st.markdown('<div class="atria-h" style="margin-top:12px">Connected systems</div>',
                    unsafe_allow_html=True)
        st.caption("Turn one off to see the forecast get *more* conservative, not less.")
        records = st.toggle("Records", value=True, key="ops_records")
        beds = st.toggle("Beds", value=True, key="ops_beds")
        roster = st.toggle("Roster", value=True, key="ops_roster")
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
        m[0].metric("Flow", out.state,
                    help="Waiting patients against staffed capacity.")
        m[1].metric("Open spaces", out.open_spaces,
                    help="Staffed spaces free right now — physically available "
                         "AND safely staffed. Not licensed beds.")
        m[2].metric("Wait buffer", f"{out.wait_buffer_minutes:.0f}m",
                    help="Median minutes before non-critical waiting patients "
                         "cross the site threshold. A planning signal only.")
        m[3].metric("Arrivals/hr", out.arrivals_next_hour)
        st.info(out.explanation, icon="📋")
        for note in out.assumptions:
            st.warning(note, icon="⚠️")

    import pandas as pd
    chart = pd.DataFrame({
        "minutes from now": [p.minute for p in out.points],
        "In a bay": [p.in_treatment for p in out.points],
        "Waiting": [p.waiting for p in out.points],
        "Staffed capacity": [out.staffed_spaces] * len(out.points),
    }).set_index("minutes from now")
    st.line_chart(chart, color=["#45C4B2", "#E8903F", "#E5766A"], height=270)

    a, b = st.columns(2)
    a.caption("**Why the green line flattens.** Treatment is capped at staffed "
              "spaces — you cannot treat more people than you have staffed places "
              "for, and a chart that let it climb would be lying.")
    b.caption("**Why the orange line can climb past it.** A queue *can* grow beyond "
              "capacity. Hiding that would hide the single condition most worth "
              "seeing.")


# ----------------------------------------------------------------- history --
def tab_history() -> None:
    eng = engine()
    intact, note = eng.audit.verify()

    c1, c2 = st.columns([1, 2])
    c1.metric("Chain", "intact" if intact else "BROKEN",
              help="Each entry embeds the hash of the one before it. Edit or "
                   "delete anything and this breaks.")
    c2.caption(f"{note}. Append-only: a correction creates a new linked event, "
               f"it never rewrites an old one. This is what makes a clinical "
               f"decision reconstructable months later.")

    mode = st.radio("View", ["Decisions", "Everything"], horizontal=True,
                    label_visibility="collapsed", key="hist_mode")
    st.caption("**Decisions** shows only what a human or the model decided — the "
               "audit trail proper. **Everything** adds arrivals, escalations and "
               "movements in time order.")

    decision_kinds = {"nurse_assessment", "atria_reveal", "sign_off",
                      "override", "worsening_reported", "abstain"}
    friendly = {"nurse_assessment": "nurse chose (blind)",
                "atria_reveal": "ATRIA revealed", "sign_off": "signed off",
                "override": "override", "worsening_reported": "change reported",
                "abstain": "refused to score", "arrival": "arrived",
                "escalation": "escalated", "seen": "taken through",
                "departure": "left"}

    rows = []
    for e in reversed(eng.audit.entries):
        if mode == "Decisions" and e.kind not in decision_kinds:
            continue
        rows.append({
            "#": e.seq, "time": str(e.at)[11:19],
            "event": friendly.get(e.kind, e.kind), "stay": e.stay_id,
            "detail": ", ".join(f"{k}={v}" for k, v in e.payload.items()
                                if v not in (None, "", [], False))[:80],
            "hash": e.hash[:8], "links to": e.prev_hash[:8],
        })
    if rows:
        import pandas as pd
        st.dataframe(pd.DataFrame(rows), width='stretch', height=430, hide_index=True)
    else:
        st.caption("No events yet — let the shift run for a moment.")


@st.fragment(run_every=2)
def board() -> None:
    """
    The board, redrawn on a timer.

    The refresh lives here, on the thing being redrawn. An empty fragment calling
    st.rerun() loops forever without finishing the script, which renders as a
    permanently blank page.
    """
    assessment, operations, history = st.tabs(
        ["  Assessment  ", "  Operations & Flow  ", "  History  "])
    with assessment:
        tab_assessment()
    with operations:
        tab_operations()
    with history:
        tab_history()


board()
