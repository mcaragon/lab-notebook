import pytest

from labnotebook.report import fmt, h_text


def build(client):
    exp_id = client.post("/api/experiments", json={
        "title": "Reduction of benzaldehyde", "objective": "Reduce an aldehyde with NaBH4.",
        "procedure": "1. Dissolve benzaldehyde in MeOH\n2. Add NaBH4 in portions", "discussion": "Worked | well",
        "references": "Lab manual, exp. 7"}).json()["experiment"]["id"]
    ald = client.post(f"/api/experiments/{exp_id}/reagents", json={"query": "benzaldehyde"}).json()["reagent_id"]
    client.put(f"/api/reagents/{ald}", json={"basis": "mass", "basis_value": 1.06})
    bh = client.post(f"/api/experiments/{exp_id}/reagents", json={"query": "sodium borohydride", "role": "reagent"}).json()
    client.put(f"/api/reagents/{bh['reagent_id']}", json={"basis": "equiv", "basis_value": 0.5})
    p = client.post(f"/api/experiments/{exp_id}/reagents", json={"query": "benzyl alcohol", "role": "product"}).json()
    client.put(f"/api/reagents/{p['reagent_id']}", json={"actual_mass_g": 0.9})
    client.post(f"/api/experiments/{exp_id}/entries", json={"kind": "observation", "text": "Gas evolution"})
    return exp_id


def test_markdown_report(client):
    exp_id = build(client)
    r = client.get(f"/api/experiments/{exp_id}/report.md?download=true")
    assert r.status_code == 200
    assert "attachment" in r.headers["content-disposition"]
    md = r.text
    for heading in ["# Reduction of benzaldehyde", "## Objective", "## Reagents", "## Safety", "## Procedure",
                    "## Observations", "## Results", "## Discussion", "## References"]:
        assert heading in md
    assert "Benzaldehyde (limiting)" in md
    assert "Worked \\| well" not in md  # prose is not table-escaped
    assert "PubChem CID 240" in md
    assert "H302: Harmful if swallowed" in md and "[Warning" not in md
    assert "83.3 %" in md  # 0.9 g / (9.989 mmol * 108.14 g/mol = 1.080 g)


def test_html_report_embeds_images(client):
    exp_id = build(client)
    html = client.get(f"/api/experiments/{exp_id}/report.html").text
    assert "data:image/svg+xml;base64," in html
    assert "<li>Dissolve benzaldehyde in MeOH</li>" in html
    assert "Test Lab" in html


def test_report_works_offline(offline_client):
    exp_id = offline_client.post("/api/experiments", json={"title": "Offline"}).json()["experiment"]["id"]
    offline_client.post(f"/api/experiments/{exp_id}/reagents", json={"query": "X", "mw": 100})
    assert offline_client.get(f"/api/experiments/{exp_id}/report.html").status_code == 200


def test_pdf_report(client):
    pytest.importorskip("weasyprint")
    exp_id = build(client)
    r = client.get(f"/api/experiments/{exp_id}/report.pdf")
    assert r.status_code == 200
    assert r.content.startswith(b"%PDF")
    assert r.headers["content-type"] == "application/pdf"


def test_formatting_helpers():
    assert fmt(1.0612) == "1.06"
    assert fmt(0.004567) == "0.00457"
    assert fmt(1234.6) == "1235"
    assert fmt(None) == ""
    assert h_text("H225: Highly flammable [Danger Flammable liquids]") == "H225: Highly flammable"
