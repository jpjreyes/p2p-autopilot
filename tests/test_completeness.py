"""Completeness check in code: "done" is refused while a row the agent saw listed as open was never downloaded.
Found on real-PO invoices (portal B, renamed columns): the agent skipped page 1 and declared all 20 covered."""

from p2p_autopilot.agent import missing_downloads, open_rows

PAGE_1 = '''- table:
  - row "Belegnr. Belegdatum Auftrag Wert Status":
  - row "VX/2026/0311 28.10.2018 PO-4507011588 1.234,50 EUR Offen Details":
  - row "VX/2026/0315 01.11.2018 PO-4507011590 99,00 EUR Offen Details":
  - row "VX/2026/0290 01.06.2018 PO-4507011500 10,00 EUR Bezahlt Details":
'''
PAGE_A = '- row "INV-1059 10/03/2018 PO-4507011588 EUR 2,014.75 OPEN View PDF":\n- row "INV-1001 PAID View PDF":'


def test_open_rows_keep_open_and_skip_paid_and_headers():
    rows = open_rows(PAGE_1)
    assert len(rows) == 2 and all("Offen" in r for r in rows)
    assert open_rows(PAGE_A) == {"INV-1059 10/03/2018 PO-4507011588 EUR 2,014.75 OPEN View PDF"}


def test_missing_downloads_match_file_names_across_separators():
    rows = open_rows(PAGE_1)
    assert missing_downloads(rows, ["/runs/x/VX-2026-0311.pdf"]) == [r for r in sorted(rows) if "0315" in r]
    assert missing_downloads(rows, ["/runs/x/VX-2026-0311.pdf", "/runs/x/VX-2026-0315.pdf"]) == []
    assert len(missing_downloads(rows, [])) == 2


def test_stored_paths_survive_a_repo_rename_and_cannot_escape_runs():
    import os
    os.environ.setdefault("DATABASE_URL", "postgresql://unused")
    from p2p_autopilot.api import RUNS_DIR, _local
    assert _local("/home/x/other-checkout/runs/r1/001.png") == str((RUNS_DIR / "r1/001.png").resolve())
    assert _local("/etc/passwd") == ""
    assert _local("/x/runs/../../etc/passwd") == ""
    assert _local("gs://bucket/runs/r1/001.png") == "gs://bucket/runs/r1/001.png"
