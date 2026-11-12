"""Tools MCP exercitadas contra a API real (TestClient) + smoke do servidor stdio."""
import asyncio
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.mcp_server import Kontrul, ToolFailure, build_server
from app.services.ingest import run_ingest


@pytest.fixture
def tools(tmp_path):
    http = TestClient(app, headers={"Authorization": f"Bearer {settings.api_token}"})
    server = build_server(Kontrul(http, allowed_dirs=[tmp_path, Path("/tmp")]))

    def call(name, **args):
        res = asyncio.run(server.call_tool(name, args))
        if res.is_error:  # erro de tool chega ao agente como resultado com is_error
            raise RuntimeError(" ".join(c.text for c in res.content))
        return res
    return call, server


def run(tools, name, **args):
    import json
    res = tools[0](name, **args)
    sc = res.structured_content
    if sc is not None:
        return sc["result"] if set(sc) == {"result"} else sc
    items = [json.loads(c.text) for c in res.content]
    return items[0] if len(items) == 1 and isinstance(items[0], dict) else items


def test_all_expected_tools_registered(tools):
    _, server = tools
    names = {t.name for t in asyncio.run(server.list_tools())}
    expected = {"create_project", "upload_asset", "transcribe_video", "attach_script", "analyze_video", "list_suggestions",
                "apply_edit_operations", "insert_media", "get_timeline", "render_preview", "render_final", "get_job_status",
                "get_render_artifact", "record_feedback", "propose_media", "plan_edit", "wait_for_job", "add_rule", "list_rules"}
    assert expected <= names


def test_headless_flow_through_tools(tools, sample_video, sample_image, tmp_path):
    p = run(tools, "create_project", title="via mcp")
    pid = p["id"]
    up = run(tools, "upload_asset", project_id=pid, file_path=str(sample_video))
    run_ingest(up["job"]["job_id"])
    aux = run(tools, "upload_asset", project_id=pid, file_path=str(sample_image), role="auxiliary", tags=["logo"])
    run_ingest(aux["job"]["job_id"])
    assert run(tools, "get_job_status", job_id=up["job"]["job_id"])["state"] == "succeeded"
    r = run(tools, "apply_edit_operations", project_id=pid, operations=[{"type": "init_main", "asset_id": up["asset"]["id"]}])
    assert r["revision"] == 1
    r = run(tools, "apply_edit_operations", project_id=pid, operations=[{"type": "remove_range", "start_ms": 500, "end_ms": 1000}])
    assert r["revision"] == 2  # expected_revision omitido usa a atual
    r = run(tools, "insert_media", project_id=pid, asset_id=aux["asset"]["id"], at_ms=500, duration_ms=1000)
    assert r["revision"] == 3 and len(r["document"]["clips"]) == 3
    job = run(tools, "render_final", project_id=pid)  # final sem preview
    from app.services.render import run_render
    run_render(job["job_id"])
    done = run(tools, "wait_for_job", job_id=job["job_id"], timeout_s=5)
    assert done["state"] == "succeeded"
    dest = tmp_path / "saida" / "final.mp4"
    art = run(tools, "get_render_artifact", job_id=job["job_id"], save_to=str(dest))
    assert Path(art["saved_to"]).exists() and art["size_bytes"] > 1000 and art["profile"] == "final"
    # o que o agente fez é visível pela mesma API que a interface usa
    assert run(tools, "get_timeline", project_id=pid)["revision"] == 3
    projs = run(tools, "list_projects")
    assert any(x["id"] == pid for x in (projs if isinstance(projs, list) else [projs]))  # lista de 1 item chega como dict


def test_path_allowlist_and_errors_are_clear(tools, tmp_path):
    call, _ = tools
    pid = run(tools, "create_project", title="x")["id"]
    with pytest.raises(Exception) as e:
        call("upload_asset", project_id=pid, file_path="/etc/passwd")
    assert "fora das pastas permitidas" in str(e.value)
    with pytest.raises(Exception) as e:
        call("apply_edit_operations", project_id=pid, operations=[{"type": "remove_range", "start_ms": 0, "end_ms": 5}])
    assert "422" in str(e.value) or "409" in str(e.value) or "404" in str(e.value) or "timeline" in str(e.value).lower()
    with pytest.raises(Exception) as e:
        call("get_render_artifact", job_id="00000000-0000-0000-0000-000000000000", save_to="/etc/x.mp4")
    assert "404" in str(e.value) or "fora" in str(e.value)


def test_pending_suggestion_cannot_be_applied_by_agent(tools, sample_video):
    import uuid
    from app.db import SessionLocal
    from app.models import Suggestion
    pid = run(tools, "create_project", title="x")["id"]
    up = run(tools, "upload_asset", project_id=pid, file_path=str(sample_video))
    run_ingest(up["job"]["job_id"])
    run(tools, "apply_edit_operations", project_id=pid, operations=[{"type": "init_main", "asset_id": up["asset"]["id"]}])
    with SessionLocal() as db:
        s = Suggestion(project_id=uuid.UUID(pid), asset_id=uuid.UUID(up["asset"]["id"]), start_ms=500, end_ms=1500,
                       category="speech_error", rationale="t")
        db.add(s)
        db.commit()
        sid = str(s.id)
    call, _ = tools
    with pytest.raises(Exception) as e:
        call("apply_edit_operations", project_id=pid, operations=[{"type": "apply_suggestion", "suggestion_id": sid}])
    assert "aceita" in str(e.value)  # mesma regra do modo manual vale para agentes
    run(tools, "record_feedback", project_id=pid, suggestion_id=sid, decision="accept")
    assert run(tools, "apply_edit_operations", project_id=pid, operations=[{"type": "apply_suggestion", "suggestion_id": sid}])["revision"] == 2


def test_stdio_server_boots_and_lists_tools():
    from mcp import Client, StdioServerParameters
    from mcp.client.stdio import stdio_client  # noqa: F401

    async def go():
        params = StdioServerParameters(command=sys.executable, args=["-m", "app.mcp_server"], cwd=str(Path(__file__).parents[1]))
        async with Client(params) as c:
            return {t.name for t in (await c.list_tools()).tools}
    try:
        names = asyncio.run(asyncio.wait_for(go(), 30))
    except TypeError:
        pytest.skip("API do cliente MCP difere nesta versão")
    assert "render_final" in names and "create_project" in names
