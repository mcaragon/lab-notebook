import pytest

from labnotebook.report import fmt, format_ref, h_text


def build(client):
    d = client.post("/api/experiments", json={
        "title": "Reduction of benzaldehyde", "objective": "Reduce an aldehyde with NaBH4.",
        "discussion": "Worked | well"}).json()
    exp_id, sid = d["experiment"]["id"], d["steps"][0]["id"]

    def add(**b):
        return client.post(f"/api/experiments/{exp_id}/reagents", json={"step_id": sid, **b}).json()["reagent_id"]

    ald = add(query="benzaldehyde", basis="mass", basis_value=1.06, grade="99%", supplier="Acme", lot="L7",
              notes="freshly distilled")
    client.put(f"/api/reagents/{ald}", json={"actual_basis": "mass", "actual_value": 1.04})
    bh = add(query="sodium borohydride", role="reagent", basis="equiv", basis_value=0.5)
    add(query="methanol", role="solvent", basis_value=15)
    fulm = add(query="628-86-4", role="workup", hazard_notes="Do not let it dry out")
    prod = add(query="benzyl alcohol", role="product")
    client.post(f"/api/steps/{sid}/conditions", json={"temperature": "0", "duration": "15 min"})
    client.post(f"/api/steps/{sid}/conditions", json={"temperature": "rt", "duration": "2 h"})
    client.post(f"/api/experiments/{exp_id}/procedure", json={"text": "Dissolve @Benzaldehyde in @Methanol.",
                                                               "notes": "Use dry MeOH"})
    client.post(f"/api/experiments/{exp_id}/start")
    client.post(f"/api/experiments/{exp_id}/entries", json={"action": "observation", "data": {"text": "Gas evolution"}})
    client.post(f"/api/experiments/{exp_id}/entries", json={
        "action": "isolate", "data": {"product": prod, "stage": "purified", "mass": 0.9}})
    ref = client.post(f"/api/experiments/{exp_id}/refs", json={
        "authors": "Smith, J.; Doe, A.", "title": "A reduction", "source": "J. Org. Chem.", "year": "2020",
        "volume": "85", "pages": "1–10", "doi": "10.1000/xyz"}).json()["refs"][0]["id"]
    client.post(f"/api/experiments/{exp_id}/refs", json={"text": "Lab manual, exp. 7"})
    client.put(f"/api/reagents/{prod}", json={"expected_yield_pct": 90, "expected_ref_id": ref})
    return exp_id, {"ald": ald, "bh": bh, "fulm": fulm, "prod": prod}


def test_markdown_report(client):
    exp_id, _ = build(client)
    r = client.get(f"/api/experiments/{exp_id}/report.md?download=true")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    md = r.text
    for heading in ["# Reduction of benzaldehyde", "## Objective", "## Reaction", "## Reagents", "## Safety",
                    "## Procedure", "## Log", "## Results", "## Discussion", "## References"]:
        assert heading in md, heading
    assert "Benzaldehyde (99%, Acme, lot L7) — limiting" in md
    assert "- Benzaldehyde: freshly distilled" in md
    assert "Sodium borohydride (0.50 equiv), Methanol, 0 °C, 15 min; then rt, 2 h" in md
    assert "1. Dissolve Benzaldehyde (1.04 g, 9.80 mmol) in Methanol (15.0 mL)." in md
    assert "*Note:* Use dry MeOH" in md
    assert "DOT: forbidden for transport" in md and "Do not let it dry out" in md
    assert "NFPA 704: 1-3-0" in md  # methanol
    assert "90% (0.954 g) [1]" in md  # expected yield with its reference
    assert "84.9%" in md  # 0.9 g / (9.80 mmol × 108.14 g/mol = 1.060 g)
    assert "1. Smith, J.; Doe, A. A reduction. J. Org. Chem. 2020, 85, 1–10. DOI: 10.1000/xyz." in md
    assert "2. Lab manual, exp. 7" in md
    assert "3. Benzaldehyde: PubChem CID 240" in md
    assert "| 0:00:0" in md  # T+ column


def test_html_report_embeds_images_and_scheme(client):
    exp_id, _ = build(client)
    html = client.get(f"/api/experiments/{exp_id}/report.html").text
    assert "data:image/svg+xml;base64," in html
    assert 'class="scheme' in html and 'class="arrow"' in html
    assert "Test Lab" in html and "freshly distilled" in html
    assert '<span class="mention"><b>Benzaldehyde</b> (1.04 g, 9.80 mmol)</span>' in html


def test_report_works_offline(offline_client):
    d = offline_client.post("/api/experiments", json={"title": "Offline"}).json()
    offline_client.post(f"/api/experiments/{d['experiment']['id']}/reagents", json={"query": "X", "mw": 100})
    assert offline_client.get(f"/api/experiments/{d['experiment']['id']}/report.html").status_code == 200


def test_pdf_report(client):
    pytest.importorskip("weasyprint")
    exp_id, _ = build(client)
    r = client.get(f"/api/experiments/{exp_id}/report.pdf")
    assert r.status_code == 200 and r.content.startswith(b"%PDF")


def test_helpers():
    assert fmt(1.0612) == "1.06" and fmt(0.004567) == "0.00457" and fmt(1234.6) == "1235" and fmt(None) == ""
    assert h_text("H225: Highly flammable [Danger Flammable liquids]") == "H225: Highly flammable"
    assert format_ref({"text": "Lab manual"}) == "Lab manual"
    assert format_ref({"authors": "A, B.", "title": "T", "source": "J", "year": "2020", "url": "http://x"}) == \
        "A, B. T. J 2020. http://x"
