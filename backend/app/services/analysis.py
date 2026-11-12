"""Job de análise: alinha o roteiro (opcional), aplica regras e grava sugestões."""
import logging
import uuid

from sqlalchemy import delete, select

from app.db import SessionLocal
from app.models import EditingRule, Job, Script, ScriptAlignment, Suggestion, Transcript, Word
from app.services import jobs as J
from app.llm import client as llmc
from app.services import learning, llm_analysis
from app.services.rules import analyze, contains_phrase, phrases_of
from app.services.scriptalign import align


def _run_llm(db, job, out: dict, words, segs, al, script) -> dict:
    """Refinamento por LLM (opcional). Qualquer falha é registrada e a análise segue só com as regras."""
    want = job.params.get("use_llm")
    if want is False:
        return {"status": "disabled"}
    client = llmc.get_client()
    if client is None:
        return {"status": "unavailable", "message": llmc.status()["message"]} if want else {"status": "disabled"}

    def progress(p: float) -> None:
        J.set_state(db, job, "running", 0.15 + 0.45 * p)

    def cancelled() -> bool:
        db.refresh(job)
        return job.cancel_requested
    try:
        out["suggestions"], report = llm_analysis.refine(client, words, segs, out["suggestions"], al,
                                                         script.text if script else None, progress, cancelled)
        return report
    except Exception as e:  # defesa final: o LLM nunca derruba a análise
        logging.getLogger("kontrul.llm").exception("refino por LLM falhou")
        return {"status": "failed", "provider": client.cfg.provider, "model": client.cfg.model, "errors": [type(e).__name__]}


def _analyze(db, job: Job) -> None:
    J.set_state(db, job, "running", 0.1)
    t = db.get(Transcript, uuid.UUID(job.params["transcript_id"]))
    script = db.get(Script, uuid.UUID(job.params["script_id"])) if job.params.get("script_id") else None
    ws = db.scalars(select(Word).where(Word.transcript_id == t.id).order_by(Word.idx)).all()
    words = [{"text": w.text, "start_ms": w.start_ms, "end_ms": w.end_ms,
              "speaker": str(w.speaker_id) if w.speaker_id else None} for w in ws]
    segs = [dict(s) for s in t.segments]
    for s in segs:  # propaga falante palavra→segmento quando houver diarização
        s["speaker"] = words[s["w0"]]["speaker"] if words else None

    al = None
    if script:
        al = align(segs, script.text)
        db.execute(delete(ScriptAlignment).where(ScriptAlignment.script_id == script.id,
                                                 ScriptAlignment.transcript_id == t.id))
        for it in al["items"]:
            sg = segs[it["seg"]]
            db.add(ScriptAlignment(script_id=script.id, transcript_id=t.id, script_start=it["script_start"],
                                   script_end=it["script_end"], word_start_idx=sg["w0"],
                                   word_end_idx=sg["w1"], adherence=it["adherence"], kind=it["kind"]))
        for u in al["unspoken"]:
            db.add(ScriptAlignment(script_id=script.id, transcript_id=t.id, script_start=u["script_start"],
                                   script_end=u["script_end"], kind="unspoken"))
    J.set_state(db, job, "running", 0.6)

    rules = [{"id": str(r.id), "kind": r.kind, "params": r.params} for r in db.scalars(
        select(EditingRule).where(EditingRule.enabled.is_(True),
                                  (EditingRule.project_id == t.project_id) | EditingRule.project_id.is_(None)))]
    out = analyze(words, segs, al, rules)
    llm_report = _run_llm(db, job, out, words, segs, al, script)
    protect = phrases_of(rules, "protect_phrase")  # a proteção do usuário vale também para achados do LLM
    if protect:
        keep = []
        for sg in out["suggestions"]:
            txt = " ".join(x["text"] for x in words if x["end_ms"] > sg["start_ms"] and x["start_ms"] < sg["end_ms"])
            if contains_phrase(txt, protect) is None:
                keep.append(sg)
            else:
                out["suppressed_by_rules"].append(sg)
        out["suggestions"] = keep
    learning.annotate(out["suggestions"], learning.load_examples(db, t.project_id))  # memória de decisões
    # recria só as pendentes geradas por regras; decisões do usuário ficam
    db.execute(delete(Suggestion).where(Suggestion.project_id == t.project_id, Suggestion.asset_id == t.asset_id,
                                        Suggestion.origin.in_(("rules", "rules+llm", "llm")), Suggestion.status == "pending"))
    for s in out["suggestions"]:
        db.add(Suggestion(project_id=t.project_id, asset_id=t.asset_id, script_id=script.id if script else None,
                          start_ms=s["start_ms"], end_ms=s["end_ms"], category=s["category"],
                          rationale=s["rationale"], evidence=s["evidence"], confidence=None,
                          origin=s.get("origin", "rules"),
                          model_version="rules/1" if s.get("origin", "rules") == "rules"
                          else f"rules/1+{llm_report.get('provider')}/{llm_report.get('model')}"))
    db.commit()
    J.set_state(db, job, "succeeded", 1.0, result={
        "suggestions": len(out["suggestions"]), "erro_ignored": len(out["ignored_erro"]),
        "suppressed_by_rules": len(out["suppressed_by_rules"]), "rules_applied": len(rules),
        "script": bool(script), "llm": llm_report})


def run_analysis(job_id: str) -> None:
    with SessionLocal() as db:
        job = db.get(Job, uuid.UUID(job_id))
        if job is None or job.state in J.TERMINAL:
            return
        try:
            with J.heartbeat(job.id):  # o LLM pode levar minutos: sem heartbeat o reaper trataria como worker perdido
                _analyze(db, job)
        except Exception as e:
            db.rollback()
            job = db.get(Job, job.id)
            J.set_state(db, job, "failed", error={"code": "analysis_failed", "message": str(e)[:500]})
