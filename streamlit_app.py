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
from service.clock import build_events                            # noqa: E402
from service.queue import QueueEngine                             # noqa: E402

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

    running = st.toggle("Run the shift", value=True)
    speed = st.select_slider("Events per tick", [1, 2, 4, 8], value=2)
    surge = st.select_slider("Arrival volume", [1.0, 2.0, 3.0], value=1.0,
                             format_func=lambda v: f"{v:.0f}× normal")
    st.session_state.surge = surge

    degraded = st.toggle("Kill the model service", value=False,
                         help="Scenario 06 — Layer 0 keeps gating deterministically.")
    st.session_state.degraded = degraded
    if "engine" in st.session_state:
        st.session_state.engine.degraded = degraded

    if st.button("Restart the shift", use_container_width=True):
        st.session_state.shift_seed = st.session_state.get("shift_seed", 21) + 1
        new_shift(surge)

    st.divider()
    st.caption(f"Missing-vitals rate this shift: "
               f"**{st.session_state.get('missing_rate', 0.18):.0%}** — surge degrades "
               f"data quality, which is when a model is most tempted to read "
               f"missingness as signal.")

init(surge)
engine = st.session_state.engine
if running:
    advance(int(speed))
snap = engine.snapshot()

# ------------------------------------------------------------------ board ---
st.markdown("#### ATRIA · Bay A")
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
    st.error("**DEGRADED MODE** · model service unavailable · Layer 0 red-flag gate still active",
             icon="⚠️")

lanes = " &nbsp; ".join(f"{k} <b>{v}</b>" for k, v in snap["lanes"].items())
st.markdown(f'<div class="lanebar">{lanes} &nbsp;&nbsp;·&nbsp;&nbsp; '
            f'scoring p95 <b>{snap["p95_ms"] or "–"} ms</b></div>', unsafe_allow_html=True)

board, side = st.columns([2.1, 1])

with board:
    if not snap["rows"]:
        st.caption("Waiting for the first arrival…")
    for r in snap["rows"][:14]:
        st.markdown(render_row(r), unsafe_allow_html=True)

with side:
    st.markdown('<div class="atria-h">Movement</div>', unsafe_allow_html=True)
    verb = {"arrived": "arrived", "seen": "taken through", "left": "left",
            "escalated": "escalated"}
    ticker = "".join(
        f'<div class="tick {t["kind"]}">{t["at"]} <b>{t["ticket"]} '
        f'{verb.get(t["kind"], t["kind"])}</b> · {t["detail"]}</div>'
        for t in snap["ticker"][:9])
    st.markdown(ticker or '<div class="tick">no movement yet</div>', unsafe_allow_html=True)

    st.markdown('<div class="atria-h" style="margin-top:18px">Clinician override</div>',
                unsafe_allow_html=True)
    waiting = [r for r in snap["rows"] if r["state"] != "IN TREATMENT"]
    if waiting:
        pick = st.selectbox("Patient", [r["ticket"] for r in waiting],
                            label_visibility="collapsed")
        row = next(r for r in waiting if r["ticket"] == pick)
        band = st.select_slider("New band", [1, 2, 3, 4, 5], value=row["band"])
        reason = st.selectbox("Reason", [
            "reassessed_at_bedside", "clinically_well", "known_baseline",
            "artefact", "resource_constraint", "other"], label_visibility="collapsed")
        if band > row["band"]:
            st.warning("This lowers the patient's priority — the one move no model "
                       "in this system may make.", icon="⚠️")
        if st.button("Record override", use_container_width=True):
            engine.override(row["stay_id"], band, reason, "nurse.demo")
            st.rerun()
    else:
        st.caption("Nobody waiting.")

    st.markdown('<div class="atria-h" style="margin-top:18px">Audit trail</div>',
                unsafe_allow_html=True)
    intact, note = engine.audit.verify()
    st.caption(f"{'✅' if intact else '❌'} {note}")
    with st.expander(f"{len(engine.audit)} entries"):
        for e in reversed(engine.audit.entries[-12:]):
            st.markdown(
                f'<div class="tick">{e.seq} <b>{e.kind}</b> · {e.hash[:10]}'
                f' &larr; {e.prev_hash[:10]}</div>', unsafe_allow_html=True)

@st.fragment(run_every=2)
def _pulse() -> None:
    """Drives the redraw while the shift is running."""
    st.rerun()


if running:
    _pulse()
