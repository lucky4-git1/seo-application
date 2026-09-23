"""Report builders: assemble stored data → CSV bytes + PDF bytes.

One section per table; sections concatenated with `# section` markers in
CSV and headed tables in PDF. No charts-as-images in v1 (honest tables).
"""
from __future__ import annotations

import csv
import io
import uuid

from sqlalchemy.orm import Session

from app import models_seo as seo
from app.config import get_settings
from app.gap import compute_gap
from app.keyword_service import scored_view
from app.tracking import movement

REPORT_TYPES = ("SEO_OVERVIEW", "AUDIT", "KEYWORDS", "RANKINGS", "COMPETITORS")
FORMATS = ("CSV", "PDF")


def export_path(report_id: uuid.UUID, fmt: str) -> str:
    import os
    base = get_settings().export_dir
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, f"{report_id}.{fmt.lower()}")


def _latest_audit(db: Session, project_id: uuid.UUID):
    return (db.query(seo.CrawlRun).filter_by(project_id=project_id, status="COMPLETED")
            .order_by(seo.CrawlRun.created_at.desc()).first())


def build_sections(db: Session, project, report_type: str) -> list[tuple[str, list[str], list[list]]]:
    """[(section_title, headers, rows)] — shared by CSV and PDF builders."""
    pid = project.id
    sections: list[tuple[str, list[str], list[list]]] = []
    sections.append(("Project", ["field", "value"], [
        ["name", project.name], ["domain", project.domain],
        ["country", project.country], ["language", project.language],
        ["device", project.device]]))

    if report_type in ("SEO_OVERVIEW", "AUDIT"):
        run = _latest_audit(db, pid)
        if run is None:
            sections.append(("Audit", ["info"], [["no completed audit"]]))
        else:
            issues = (db.query(seo.AuditIssue, seo.AuditRule.code)
                      .join(seo.AuditRule, seo.AuditIssue.rule_id == seo.AuditRule.id)
                      .filter(seo.AuditIssue.crawl_run_id == run.id)
                      .order_by(seo.AuditIssue.affected_count.desc()).all())
            sections.append(("Audit summary",
                             ["health_score", "pages_crawled", "rules_firing"],
                             [[run.health_score, run.pages_crawled, len(issues)]]))
            sections.append(("Audit issues",
                             ["rule", "severity", "category", "affected", "recommendation"],
                             [[code, i.severity, i.category, i.affected_count,
                               i.recommendation] for i, code in issues]))

    if report_type in ("SEO_OVERVIEW", "KEYWORDS"):
        kws = db.query(seo.Keyword).filter_by(organization_id=project.organization_id).all()
        views = sorted(
            (scored_view(db, k) for k in kws
             if k.project_id in (None, pid)),
            key=lambda v: -(v["opportunity"] or 0))[:500]
        sections.append(("Keywords",
                         ["keyword", "intent", "volume", "cpc", "difficulty",
                          "opportunity", "provider"],
                         [[v["keyword"], v["intent"], v["search_volume"], v["cpc"],
                           v["difficulty"], v["opportunity"], v["provider"]]
                          for v in views]))

    if report_type in ("SEO_OVERVIEW", "RANKINGS"):
        tracked = (db.query(seo.TrackedKeyword)
                   .filter_by(project_id=pid, is_active=True).all())
        rows = []
        for t in tracked:
            m = movement(db, t)
            rows.append([m["keyword"], m["current_rank"], m["previous_rank"],
                         m["change"], m["best_rank"], m["worst_rank"]])
        sections.append(("Rankings",
                         ["keyword", "current", "previous", "change", "best", "worst"],
                         rows or [["(no tracked keywords)", "", "", "", "", ""]]))

    if report_type in ("SEO_OVERVIEW", "COMPETITORS"):
        comps = db.query(seo.Competitor).filter_by(project_id=pid,
                                                   is_active=True).all()
        sections.append(("Competitors", ["domain", "label"],
                         [[c.domain, c.label or ""] for c in comps]
                         or [["(none)", ""]]))
        gap = compute_gap(db, project, comps, page=1, page_size=200)
        sections.append(("Keyword gap",
                         ["keyword", "your_rank", "bucket", "volume",
                          "difficulty", "opportunity"],
                         [[r["keyword"], r["your_rank"], r["bucket"],
                           r["search_volume"], r["difficulty"], r["opportunity"]]
                          for r in gap["items"]]))

    if report_type == "SEO_OVERVIEW":
        recos = (db.query(seo.Recommendation).filter_by(project_id=pid, status="OPEN")
                 .order_by(seo.Recommendation.score.desc()).limit(50).all())
        sections.append(("Recommendations",
                         ["score", "severity", "type", "source", "title"],
                         [[r.score, r.severity, r.type, r.source, r.title] for r in recos]
                         or [["(none yet — run recalculate)", "", "", "", ""]]))
    return sections


def build_csv(sections: list[tuple[str, list[str], list[list]]]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    for title, headers, rows in sections:
        w.writerow([f"# {title}"])
        w.writerow(headers)
        w.writerows([[("" if v is None else v) for v in r] for r in rows])
        w.writerow([])
    return buf.getvalue().encode("utf-8")


def build_pdf(title: str, sections: list[tuple[str, list[str], list[list]]]) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4),
                            title=title[:100], author="SEO Intelligence Platform")
    styles = getSampleStyleSheet()
    story = [Paragraph(title, styles["Title"]), Spacer(1, 12)]
    wrap = lambda v: Paragraph(str("" if v is None else v)[:300], styles["Normal"])
    for heading, headers, rows in sections:
        story.append(Paragraph(heading, styles["Heading2"]))
        data = [[wrap(h) for h in headers]] + [[wrap(v) for v in r] for r in rows[:400]]
        t = Table(data, repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ]))
        story.append(t)
        story.append(Spacer(1, 12))
    doc.build(story)
    return buf.getvalue()
