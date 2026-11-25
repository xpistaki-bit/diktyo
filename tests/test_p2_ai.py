"""KI-Recherche für den Katalog (Claude API) – mit nachgebildetem Client, ohne echte Anfragen."""
from urllib.parse import urlparse
from types import SimpleNamespace as NS

from app import ai, security
from app.db import db, get_setting
from tests.test_m6 import H, login


def usage(i=1000, o=200, searches=0):
    return NS(input_tokens=i, output_tokens=o, cache_creation_input_tokens=0, cache_read_input_tokens=0,
              server_tool_use=NS(web_search_requests=searches))


ENTRY = dict(type="computer", manufacturer="HP", model="EliteDesk 800 G4 DM",
             ports=[dict(count=1, kind="rj45", speed="1G", label="LAN", poe=False)], wifi="Wi-Fi 5 (optional)", managed=False,
             note="Mini-PC, Intel Core 8. Gen., bis 32 GB DDR4.", sources=["https://support.hp.com/quickspecs-800g4dm", "javascript:alert(1)"],
             confidence="high")


class FakeMessages:
    def __init__(self):
        self.calls = []

    def create(self, **kw):
        self.calls.append(kw)
        if len(self.calls) == 1:  # erst pausiert die Websuche den Turn
            return NS(model=kw["model"], stop_reason="pause_turn", usage=usage(searches=2),
                      content=[NS(type="server_tool_use", name="web_search"), NS(type="web_search_tool_result", content=[NS(url="https://example.org/a")])])
        return NS(model=kw["model"], stop_reason="tool_use", usage=usage(3000, 600, 1),
                  content=[NS(type="text", text="Gefunden."), NS(type="tool_use", name="catalog_entry", input=ENTRY)])


def test_ai_settings_lookup_and_privacy(monkeypatch):
    fake = FakeMessages()
    seen_keys = []
    monkeypatch.setattr(ai, "_client", lambda key: seen_keys.append(key) or NS(beta=NS(messages=fake), messages=fake))
    cl = login()
    with db() as c:
        ai.save(c, key="")
    # ohne Schlüssel: klare Meldung
    r = cl.post("/api/catalog/ai-lookup", json={"manufacturer": "HP", "model": "EliteDesk 800 G4 DM 35W"}, headers=H)
    assert r.status_code == 400 and "Schlüssel" in r.json()["error"]
    # Schlüssel speichern: verschlüsselt, Anzeige maskiert
    s = cl.put("/api/settings/ai", json={"key": "sk-ant-test-123", "model": "claude-opus-5-5"}, headers=H).json()
    assert s["key"] == security.MASK and s["model"] == "claude-opus-5-5"
    with db() as c:
        assert "sk-ant" not in str(get_setting(c, "ai")) and security.decrypt(get_setting(c, "ai")["key"]) == "sk-ant-test-123"
    assert cl.get("/api/catalog").json()["ai"] is True
    r = cl.post("/api/catalog/ai-lookup", json={"manufacturer": "HP", "model": "EliteDesk 800 G4 DM 35W", "family": "EliteDesk",
                                                "serial": "GEHEIM123", "uuid": "0000-1111", "nics": ["Intel I219-LM"]}, headers=H).json()
    e = r["entry"]
    assert (e["type"], e["model"], e["ports"][0]["kind"]) == ("computer", "EliteDesk 800 G4 DM", "rj45") and r["confidence"] == "high"
    assert r["sources"] == ["https://support.hp.com/quickspecs-800g4dm"] and urlparse(e["source"]).hostname == "support.hp.com"
    # Kosten: Opus 5.5 $4/$20 je 1 Mio. + 3 Websuchen à 1 Cent
    assert r["usage"]["searches"] == 3 and abs(r["usage"]["cost"] - (4000 * 4 / 1e6 + 800 * 20 / 1e6 + 0.03)) < 1e-6
    # Anfrage: Modell, Websuche, strenges Werkzeug, Fallback; pause_turn wurde fortgesetzt
    first, second = fake.calls
    assert first["model"] == "claude-opus-5-5" and first["fallbacks"] == "default" and "server-side-fallback-2026-07-01" in first["betas"]
    assert first["tools"][0]["type"] == "web_search_20260209" and first["tools"][1]["strict"] is True
    assert second["messages"][-1]["role"] == "assistant" and seen_keys[-1] == "sk-ant-test-123"
    prompt = first["messages"][0]["content"]
    assert "EliteDesk 800 G4 DM 35W" in prompt and "Intel I219-LM" in prompt
    assert "GEHEIM123" not in str(fake.calls) and "0000-1111" not in str(fake.calls)
    # Backup: Schlüssel nur mit Passphrase, sonst leer
    from app import backup as bk
    with db() as c:
        exp = bk.export_data(c)
    assert "sk-ant" not in str(exp["settings"]["ai"])


def test_ai_refusal(monkeypatch):
    responses = iter([NS(model="claude-opus-5-5", stop_reason="refusal", usage=usage(), content=[])])
    monkeypatch.setattr(ai, "_client", lambda key: NS(beta=NS(messages=NS(create=lambda **kw: next(responses)))))
    with db() as c:
        ai.save(c, key="sk-ant-x", model="claude-sonnet-5-5")
        try:
            ai.lookup(c, {"manufacturer": "HP", "model": "X"})
            raise AssertionError
        except ai.AIError as ex:
            assert "abgelehnt" in str(ex)
        assert ai.settings(c)["model"] == "claude-sonnet-5-5"
