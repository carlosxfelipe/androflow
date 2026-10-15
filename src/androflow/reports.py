from __future__ import annotations

import html
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from .runner import FlowResult


def generate_junit_xml(
    results: FlowResult | Sequence[FlowResult], destination: str | Path
) -> Path:
    """Gera relatório no formato padrão JUnit XML para integração em CI/CD."""
    dest = Path(destination)
    dest.parent.mkdir(parents=True, exist_ok=True)
    flow_list = [results] if isinstance(results, FlowResult) else list(results)

    total_tests = sum(f.total for f in flow_list)
    total_failures = sum(f.failed for f in flow_list)
    total_time = sum(f.duration for f in flow_list)

    root = ET.Element(
        "testsuites",
        name="androflow",
        tests=str(total_tests),
        failures=str(total_failures),
        errors="0",
        time=f"{total_time:.3f}",
    )

    for flow in flow_list:
        suite = ET.SubElement(
            root,
            "testsuite",
            name=flow.path.stem,
            tests=str(flow.total),
            failures=str(flow.failed),
            errors="0",
            skipped=str(flow.skipped),
            time=f"{flow.duration:.3f}",
        )
        for step in flow.steps:
            case = ET.SubElement(
                suite,
                "testcase",
                classname=flow.path.stem,
                name=f"{step.index:02d}_{step.command}",
                time=f"{step.duration:.3f}",
            )
            if not step.passed:
                fail_elem = ET.SubElement(
                    case,
                    "failure",
                    message=step.error or "Falha na etapa",
                    type="FlowError",
                )
                fail_elem.text = step.error or "Falha na etapa"

        for skipped_idx in range(len(flow.steps) + 1, flow.total + 1):
            case = ET.SubElement(
                suite,
                "testcase",
                classname=flow.path.stem,
                name=f"{skipped_idx:02d}_skipped",
                time="0.000",
            )
            ET.SubElement(case, "skipped", message="Pulada devido a falha anterior")

    tree = ET.ElementTree(root)
    tree.write(dest, encoding="utf-8", xml_declaration=True)
    return dest


def generate_html_report(
    results: FlowResult | Sequence[FlowResult], destination: str | Path
) -> Path:
    """Gera um relatório visual HTML interativo, responsivo e autocontido."""
    dest = Path(destination)
    dest.parent.mkdir(parents=True, exist_ok=True)
    flow_list = [results] if isinstance(results, FlowResult) else list(results)

    total_steps = sum(f.total for f in flow_list)
    total_passed = sum(f.passed for f in flow_list)
    total_failed = sum(f.failed for f in flow_list)
    total_skipped = sum(f.skipped for f in flow_list)
    total_time = sum(f.duration for f in flow_list)
    is_ok = total_failed == 0

    now_str = datetime.now(UTC).strftime("%d/%m/%Y %H:%M:%S UTC")

    flows_html = []
    for flow in flow_list:
        flow_status_badge = (
            '<span class="badge badge-pass">PASS</span>'
            if flow.ok
            else '<span class="badge badge-fail">FAIL</span>'
        )

        video_block = ""
        if flow.video_path and flow.video_path.is_file():
            try:
                rel_video = flow.video_path.relative_to(dest.parent)
            except ValueError:
                rel_video = flow.video_path
            video_block = f"""
            <div class="video-container">
                <h4>Gravação da Execução</h4>
                <video controls preload="metadata">
                    <source src="{html.escape(str(rel_video))}" type="video/mp4">
                    Seu navegador não suporta a tag video.
                </video>
            </div>
            """

        steps_rows = []
        for step in flow.steps:
            status_badge = (
                '<span class="badge badge-pass">PASS</span>'
                if step.passed
                else '<span class="badge badge-fail">FAIL</span>'
            )
            err_html = ""
            if step.error:
                err_html = f'<div class="error-box">{html.escape(step.error)}</div>'

            duration_ms = int(step.duration * 1000)
            row = f"""
            <tr class="step-row {"step-pass" if step.passed else "step-fail"}">
                <td class="col-idx">#{step.index:02d}</td>
                <td class="col-cmd"><code>{html.escape(step.command)}</code></td>
                <td class="col-status">{status_badge}</td>
                <td class="col-time">{duration_ms}ms</td>
            </tr>
            """
            if err_html:
                row += f"""
                <tr class="error-row">
                    <td colspan="4">{err_html}</td>
                </tr>
                """
            steps_rows.append(row)

        for skipped_idx in range(len(flow.steps) + 1, flow.total + 1):
            row = f"""
            <tr class="step-row step-skipped">
                <td class="col-idx">#{skipped_idx:02d}</td>
                <td class="col-cmd"><code>pulada</code></td>
                <td class="col-status">
                    <span class="badge badge-skipped">SKIPPED</span>
                </td>
                <td class="col-time">-</td>
            </tr>
            """
            steps_rows.append(row)

        # Galeria de artefatos (screenshots gerados durante o fluxo)
        screenshots = [p for p in flow.artifacts if p.suffix.lower() == ".png"]
        gallery_block = ""
        if screenshots:
            gallery_items = []
            for img in screenshots:
                try:
                    rel_img = img.relative_to(dest.parent)
                except ValueError:
                    rel_img = img
                gallery_items.append(f"""
                <div class="gallery-card">
                    <a href="{html.escape(str(rel_img))}" target="_blank">
                        <img src="{html.escape(str(rel_img))}"
                             alt="{html.escape(img.name)}" loading="lazy">
                    </a>
                    <div class="gallery-name">{html.escape(img.name)}</div>
                </div>
                """)
            gallery_block = f"""
            <div class="gallery-container">
                <h4>Capturas de Tela</h4>
                <div class="gallery-grid">
                    {"".join(gallery_items)}
                </div>
            </div>
            """

        flow_card = f"""
        <div class="flow-card {"flow-pass" if flow.ok else "flow-fail"}">
            <div class="flow-header">
                <div>
                    <h3 class="flow-title">{html.escape(str(flow.path))}</h3>
                    <div class="flow-meta">
                        {flow.total} etapas &bull; {flow.duration:.2f}s
                    </div>
                </div>
                <div>{flow_status_badge}</div>
            </div>
            {video_block}
            <div class="table-container">
                <table class="steps-table">
                    <thead>
                        <tr>
                            <th style="width: 60px;">Etapa</th>
                            <th>Comando</th>
                            <th style="width: 100px;">Status</th>
                            <th style="width: 100px;">Duração</th>
                        </tr>
                    </thead>
                    <tbody>
                        {"".join(steps_rows)}
                    </tbody>
                </table>
            </div>
            {gallery_block}
        </div>
        """
        flows_html.append(flow_card)

    content = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AndroFlow - Relatório de Testes</title>
    <style>
        :root {{
            --bg: #0f172a;
            --surface: #1e293b;
            --surface-hover: #334155;
            --border: #334155;
            --text: #f8fafc;
            --text-muted: #94a3b8;
            --pass: #10b981;
            --pass-bg: rgba(16, 185, 129, 0.15);
            --fail: #f43f5e;
            --fail-bg: rgba(244, 63, 94, 0.15);
            --skipped: #f59e0b;
            --skipped-bg: rgba(245, 158, 11, 0.15);
            --brand: #6366f1;
        }}
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            background: var(--bg);
            color: var(--text);
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI",
                         Roboto, Helvetica, Arial, sans-serif;
            padding: 32px 16px;
            line-height: 1.5;
        }}
        .container {{ max-width: 1100px; margin: 0 auto; }}
        header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 24px;
            padding-bottom: 16px;
            border-bottom: 1px solid var(--border);
        }}
        .brand {{ display: flex; align-items: center; gap: 12px; }}
        .brand h1 {{ font-size: 1.75rem; font-weight: 700; color: var(--text); }}
        .brand span {{
            background: var(--brand);
            color: white;
            font-size: 0.75rem;
            font-weight: 600;
            padding: 2px 8px;
            border-radius: 9999px;
            text-transform: uppercase;
        }}
        .timestamp {{ color: var(--text-muted); font-size: 0.875rem; }}
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
            gap: 16px;
            margin-bottom: 32px;
        }}
        .stat-card {{
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 16px;
            display: flex;
            flex-direction: column;
            gap: 4px;
        }}
        .stat-label {{
            color: var(--text-muted);
            font-size: 0.875rem;
            font-weight: 500;
        }}
        .stat-value {{ font-size: 1.75rem; font-weight: 700; }}
        .stat-pass {{ color: var(--pass); }}
        .stat-fail {{ color: var(--fail); }}
        .stat-skipped {{ color: var(--skipped); }}
        .flow-card {{
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 12px;
            margin-bottom: 24px;
            overflow: hidden;
        }}
        .flow-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 16px 20px;
            border-bottom: 1px solid var(--border);
            background: rgba(255, 255, 255, 0.02);
        }}
        .flow-title {{ font-size: 1.1rem; font-weight: 600; }}
        .flow-meta {{ font-size: 0.875rem; color: var(--text-muted); margin-top: 2px; }}
        .badge {{
            font-size: 0.75rem;
            font-weight: 700;
            padding: 4px 10px;
            border-radius: 6px;
            letter-spacing: 0.05em;
        }}
        .badge-pass {{ background: var(--pass-bg); color: var(--pass); }}
        .badge-fail {{ background: var(--fail-bg); color: var(--fail); }}
        .badge-skipped {{ background: var(--skipped-bg); color: var(--skipped); }}
        .table-container {{ overflow-x: auto; }}
        .steps-table {{
            width: 100%;
            border-collapse: collapse;
            text-align: left;
            font-size: 0.9rem;
        }}
        .steps-table th {{
            background: rgba(0, 0, 0, 0.2);
            color: var(--text-muted);
            font-weight: 600;
            padding: 12px 20px;
            font-size: 0.8rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }}
        .steps-table td {{ padding: 12px 20px; border-top: 1px solid var(--border); }}
        .col-idx {{
            color: var(--text-muted);
            font-family: monospace;
            font-size: 0.85rem;
        }}
        .col-cmd code {{
            background: rgba(0, 0, 0, 0.3);
            padding: 3px 6px;
            border-radius: 4px;
            font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
            font-size: 0.85rem;
            color: #38bdf8;
        }}
        .error-row td {{ background: rgba(244, 63, 94, 0.05); padding-top: 0; }}
        .error-box {{
            background: rgba(244, 63, 94, 0.1);
            border-left: 3px solid var(--fail);
            padding: 8px 12px;
            border-radius: 4px;
            font-family: monospace;
            font-size: 0.85rem;
            color: #fda4af;
            word-break: break-word;
        }}
        .video-container {{
            padding: 16px 20px;
            border-bottom: 1px solid var(--border);
            background: rgba(0, 0, 0, 0.15);
        }}
        .video-container h4 {{
            font-size: 0.9rem;
            color: var(--text-muted);
            margin-bottom: 8px;
        }}
        .video-container video {{
            max-width: 100%;
            width: 480px;
            border-radius: 8px;
            background: black;
        }}
        .gallery-container {{
            padding: 16px 20px;
            border-top: 1px solid var(--border);
            background: rgba(0, 0, 0, 0.1);
        }}
        .gallery-container h4 {{
            font-size: 0.9rem;
            color: var(--text-muted);
            margin-bottom: 12px;
        }}
        .gallery-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
            gap: 12px;
        }}
        .gallery-card {{
            background: var(--bg);
            border: 1px solid var(--border);
            border-radius: 8px;
            overflow: hidden;
            display: flex;
            flex-direction: column;
        }}
        .gallery-card img {{
            width: 100%;
            height: 180px;
            object-fit: cover;
            object-position: top;
            transition: transform 0.2s;
        }}
        .gallery-card img:hover {{ transform: scale(1.03); }}
        .gallery-name {{
            padding: 6px 8px;
            font-size: 0.75rem;
            color: var(--text-muted);
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="brand">
                <h1>AndroFlow</h1>
                <span>Test Report</span>
            </div>
            <div class="timestamp">{now_str}</div>
        </header>

        <section class="stats-grid">
            <div class="stat-card">
                <div class="stat-label">Status Geral</div>
                <div class="stat-value {"stat-pass" if is_ok else "stat-fail"}">
                    {"PASS" if is_ok else "FAIL"}
                </div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Total de Etapas</div>
                <div class="stat-value">{total_steps}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Aprovadas</div>
                <div class="stat-value stat-pass">{total_passed}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Falhas</div>
                <div class="stat-value stat-fail">{total_failed}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Puladas</div>
                <div class="stat-value stat-skipped">{total_skipped}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Duração Total</div>
                <div class="stat-value">{total_time:.2f}s</div>
            </div>
        </section>

        <section class="flows-section">
            {"".join(flows_html)}
        </section>
    </div>
</body>
</html>
"""
    dest.write_text(content, encoding="utf-8")
    return dest
