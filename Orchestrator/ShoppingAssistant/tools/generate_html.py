#!/usr/bin/env python3
# generate_html.py
#
# Standalone HTML report generator. Run as a script or imported.
# Usage: python generate_html.py   (reads SHOPPING_OUTPUT_DIR env var)

import json
import os
import sys
import html as _html
from datetime import datetime

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..')))


def _e(s):
    return _html.escape(str(s)) if s is not None else ''


def _price(raw):
    s = str(raw).strip() if raw else ''
    if not s or s.lower() == 'unknown':
        return 'Unknown'
    s = s.lstrip('$').strip()
    return f'${s}' if s else 'Unknown'


def _items(val):
    if isinstance(val, list):
        return [i.lstrip('- •').strip() for i in val if str(i).strip()]
    if isinstance(val, str):
        return [i.lstrip('- •').strip() for i in val.split('\n') if i.strip()]
    return []


def generate(report_obj, html_path):
    reqs     = _e(report_obj.get('requirements_summary', ''))
    rec      = report_obj.get('recommendation', {})
    winner   = _e(rec.get('winner_name', ''))
    reason   = _e(rec.get('reason', ''))
    products = report_obj.get('products', [])
    gen_date = report_obj.get('generated_at', '')[:10]

    cards_html = ''
    rows_html  = ''

    for p in products:
        name         = _e(p.get('name', ''))
        price        = _price(p.get('price'))
        avail        = _e(p.get('availability', 'Unknown'))
        summary      = _e(p.get('summary', ''))
        purchase_url = _e(p.get('purchase_url') or '#')
        source_url   = _e(p.get('source_url') or '#')
        is_winner    = p.get('name', '') == rec.get('winner_name', '')

        pros = _items(p.get('pros', []))
        cons = _items(p.get('cons', []))
        pros_li = ''.join(f'<li>{_e(x)}</li>' for x in pros[:5])
        cons_li = ''.join(f'<li>{_e(x)}</li>' for x in cons[:5])

        badge      = '<span class="badge-winner">★ Top Pick</span>' if is_winner else ''
        card_class = ' card--winner' if is_winner else ''
        avail_slug = avail.lower().replace(' ', '-')

        cards_html += f'''
<div class="card{card_class}">
  <div class="card-top">
    <div class="card-name-row">
      <h3>{name}</h3>
      {badge}
    </div>
    <div class="card-meta">
      <span class="price">{price}</span>
      <span class="avail avail--{avail_slug}">{avail}</span>
    </div>
  </div>
  <p class="card-summary">{summary}</p>
  <div class="pros-cons">
    <div class="col-pros"><span class="label-pros">Pros</span><ul>{pros_li}</ul></div>
    <div class="col-cons"><span class="label-cons">Cons</span><ul>{cons_li}</ul></div>
  </div>
  <div class="card-actions">
    <a href="{purchase_url}" target="_blank" rel="noopener" class="btn-buy">Buy Now</a>
    <a href="{source_url}"   target="_blank" rel="noopener" class="btn-source">View Source</a>
  </div>
</div>'''

        top_pro    = _e(pros[0]) if pros else '—'
        top_con    = _e(cons[0]) if cons else '—'
        row_class  = ' class="row-winner"' if is_winner else ''
        rows_html += f'''
<tr{row_class}>
  <td class="col-name">{name} {badge}</td>
  <td class="col-price">{price}</td>
  <td>{avail}</td>
  <td class="col-pro">{top_pro}</td>
  <td class="col-con">{top_con}</td>
  <td><a href="{purchase_url}" target="_blank" rel="noopener" class="btn-buy btn-sm">Buy Now</a></td>
</tr>'''

    doc = f'''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Shopping Report</title>
  <style>
    /* ─── Tokens ─────────────────────────────────────── */
    :root {{
      --bg:       #f2f2f7;
      --surface:  #ffffff;
      --surface2: #f2f2f7;
      --border:   #d1d1d6;
      --text:     #1c1c1e;
      --text2:    #6c6c70;
      --accent:   #007aff;
      --green:    #34c759;
      --red:      #ff3b30;
      --gold:     #f5a623;
      --gold-bg:  #fff8e6;
      --shadow:   0 2px 14px rgba(0,0,0,.07);
    }}
    [data-theme="dark"] {{
      --bg:       #000000;
      --surface:  #1c1c1e;
      --surface2: #2c2c2e;
      --border:   #3a3a3c;
      --text:     #f5f5f7;
      --text2:    #98989d;
      --gold-bg:  #2a1f00;
      --shadow:   0 2px 14px rgba(0,0,0,.45);
    }}

    /* ─── Reset ──────────────────────────────────────── */
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
            background: var(--bg); color: var(--text); line-height: 1.5; min-height: 100vh; }}
    a {{ color: inherit; }}
    ul {{ list-style: disc; padding-left: 1.1em; }}

    /* ─── Top bar ─────────────────────────────────────── */
    .topbar {{
      position: sticky; top: 0; z-index: 200;
      background: var(--surface); border-bottom: 1px solid var(--border);
      padding: 10px 20px; display: flex; align-items: center; gap: 10px;
      box-shadow: var(--shadow);
    }}
    .topbar-title {{ flex: 1; font-size: 1rem; font-weight: 700; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
    .topbar-controls {{ display: flex; gap: 6px; flex-shrink: 0; }}
    .seg {{ display: flex; border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }}
    .seg button {{
      background: var(--surface2); border: none; color: var(--text2);
      padding: 5px 12px; font-size: 0.78rem; font-weight: 600; cursor: pointer;
      border-right: 1px solid var(--border); transition: background 0.15s, color 0.15s;
    }}
    .seg button:last-child {{ border-right: none; }}
    .seg button.active {{ background: var(--accent); color: #fff; }}
    .seg button:hover:not(.active) {{ background: var(--border); }}
    .theme-btn {{
      background: var(--surface2); border: 1px solid var(--border); color: var(--text2);
      padding: 5px 12px; border-radius: 8px; font-size: 0.78rem; font-weight: 600;
      cursor: pointer; transition: background 0.15s;
    }}
    .theme-btn:hover {{ background: var(--border); }}

    /* ─── Page ────────────────────────────────────────── */
    .page {{ max-width: 1140px; margin: 0 auto; padding: 24px 20px 72px; }}

    /* ─── Recommendation banner ───────────────────────── */
    .rec-banner {{
      background: var(--gold-bg); border: 1.5px solid var(--gold);
      border-radius: 14px; padding: 20px 24px; margin-bottom: 20px;
      display: flex; gap: 16px; align-items: flex-start;
    }}
    .rec-star {{ font-size: 2rem; line-height: 1; flex-shrink: 0; }}
    .rec-label {{
      font-size: 0.68rem; font-weight: 800; text-transform: uppercase;
      letter-spacing: .1em; color: var(--gold); margin-bottom: 3px;
    }}
    .rec-name {{ font-size: 1.3rem; font-weight: 800; margin-bottom: 5px; }}
    .rec-reason {{ font-size: 0.875rem; color: var(--text2); }}

    /* ─── Requirements strip ──────────────────────────── */
    .reqs {{
      background: var(--surface); border: 1px solid var(--border);
      border-radius: 10px; padding: 12px 16px; margin-bottom: 24px;
      font-size: 0.85rem; color: var(--text2);
    }}
    .reqs strong {{ color: var(--text); }}

    /* ─── Section heading ─────────────────────────────── */
    .section-title {{ font-size: 1.05rem; font-weight: 700; margin-bottom: 14px; }}

    /* ─── Cards ───────────────────────────────────────── */
    .cards-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(290px, 1fr));
      gap: 16px;
    }}
    .card {{
      background: var(--surface); border: 1px solid var(--border);
      border-radius: 16px; padding: 18px; box-shadow: var(--shadow);
      display: flex; flex-direction: column; gap: 11px;
    }}
    .card--winner {{ border-color: var(--gold); background: var(--gold-bg); }}
    .card-name-row {{ display: flex; align-items: flex-start; justify-content: space-between; gap: 8px; }}
    .card-name-row h3 {{ font-size: 0.97rem; font-weight: 700; line-height: 1.3; }}
    .badge-winner {{
      flex-shrink: 0; background: var(--gold); color: #fff;
      font-size: 0.65rem; font-weight: 800; padding: 2px 8px;
      border-radius: 20px; white-space: nowrap; margin-top: 2px;
    }}
    .card-meta {{ display: flex; align-items: center; gap: 8px; }}
    .price {{ font-size: 1.15rem; font-weight: 800; font-variant-numeric: tabular-nums; }}
    .avail {{
      font-size: 0.72rem; font-weight: 600; padding: 2px 9px;
      border-radius: 20px; background: var(--surface2); color: var(--text2);
    }}
    .avail--in-stock {{ background: #d4f5dc; color: #1d7a33; }}
    [data-theme="dark"] .avail--in-stock {{ background: #0d3018; color: #30d158; }}
    .card-summary {{ font-size: 0.83rem; color: var(--text2); line-height: 1.55; }}
    .pros-cons {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; font-size: 0.8rem; }}
    .label-pros, .label-cons {{
      display: block; font-size: 0.67rem; font-weight: 800;
      text-transform: uppercase; letter-spacing: .07em; margin-bottom: 4px;
    }}
    .label-pros {{ color: var(--green); }}
    .label-cons {{ color: var(--red); }}
    .col-pros ul, .col-cons ul {{ color: var(--text2); line-height: 1.65; }}
    .card-actions {{ display: flex; align-items: center; gap: 10px; margin-top: auto; padding-top: 4px; }}

    /* ─── Buttons ─────────────────────────────────────── */
    .btn-buy {{
      display: inline-block; background: var(--green); color: #fff;
      padding: 8px 18px; border-radius: 20px; text-decoration: none;
      font-size: 0.83rem; font-weight: 700; transition: opacity .15s;
    }}
    .btn-buy:hover {{ opacity: .82; }}
    .btn-buy.btn-sm {{ padding: 5px 12px; font-size: 0.76rem; }}
    .btn-source {{
      font-size: 0.8rem; color: var(--text2); text-decoration: none;
    }}
    .btn-source:hover {{ color: var(--accent); text-decoration: underline; }}

    /* ─── Table ───────────────────────────────────────── */
    .table-wrap {{
      overflow-x: auto; border-radius: 14px; box-shadow: var(--shadow);
      border: 1px solid var(--border);
    }}
    table {{ width: 100%; border-collapse: collapse; background: var(--surface); font-size: 0.85rem; }}
    thead th {{
      background: var(--surface2); color: var(--text2);
      font-size: 0.67rem; font-weight: 800; text-transform: uppercase; letter-spacing: .08em;
      padding: 10px 14px; text-align: left;
    }}
    tbody td {{ padding: 12px 14px; border-bottom: 1px solid var(--border); vertical-align: top; }}
    tbody tr:last-child td {{ border-bottom: none; }}
    tbody tr:hover td {{ background: var(--surface2); }}
    .row-winner td {{ background: var(--gold-bg); }}
    .row-winner:hover td {{ filter: brightness(.97); }}
    .col-name {{ font-weight: 700; min-width: 160px; }}
    .col-name .badge-winner {{ margin-left: 6px; vertical-align: middle; }}
    .col-price {{ font-weight: 800; white-space: nowrap; font-variant-numeric: tabular-nums; }}
    .col-pro {{ color: #1d7a33; font-size: 0.8rem; }}
    .col-con {{ color: #b0291e; font-size: 0.8rem; }}
    [data-theme="dark"] .col-pro {{ color: #30d158; }}
    [data-theme="dark"] .col-con {{ color: #ff6961; }}

    /* ─── View switching ─────────────────────────────── */
    #view-list {{ display: none; }}

    /* ─── Footer ─────────────────────────────────────── */
    .footer {{ margin-top: 48px; text-align: center; font-size: 0.75rem; color: var(--text2); }}
  </style>
</head>
<body>

<div class="topbar">
  <span class="topbar-title">🛒 Shopping Report</span>
  <div class="topbar-controls">
    <div class="seg">
      <button id="btn-cards" class="active" onclick="setView('cards')">⊞ Cards</button>
      <button id="btn-list"              onclick="setView('list')">☰ List</button>
    </div>
    <button class="theme-btn" id="btn-theme" onclick="toggleTheme()">🌙 Dark</button>
  </div>
</div>

<div class="page">

  <div class="rec-banner">
    <div class="rec-star">★</div>
    <div>
      <div class="rec-label">Top Pick</div>
      <div class="rec-name">{winner}</div>
      <div class="rec-reason">{reason}</div>
    </div>
  </div>

  <div class="reqs"><strong>Looking for:</strong> {reqs}</div>

  <div class="section-title">Products</div>

  <div id="view-cards">
    <div class="cards-grid">
      {cards_html}
    </div>
  </div>

  <div id="view-list">
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Product</th>
            <th>Price</th>
            <th>Availability</th>
            <th>Top Pro</th>
            <th>Top Con</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {rows_html}
        </tbody>
      </table>
    </div>
  </div>

  <div class="footer">Generated {gen_date} &middot; Prices and availability may have changed.</div>
</div>

<script>
  function setView(v) {{
    document.getElementById('view-cards').style.display = v === 'cards' ? 'block' : 'none';
    document.getElementById('view-list').style.display  = v === 'list'  ? 'block' : 'none';
    document.getElementById('btn-cards').classList.toggle('active', v === 'cards');
    document.getElementById('btn-list').classList.toggle('active',  v === 'list');
    try {{ localStorage.setItem('sr-view', v); }} catch(e) {{}}
  }}

  function toggleTheme() {{
    var root = document.documentElement;
    var next = root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
    applyTheme(next);
    try {{ localStorage.setItem('sr-theme', next); }} catch(e) {{}}
  }}

  function applyTheme(t) {{
    document.documentElement.setAttribute('data-theme', t);
    document.getElementById('btn-theme').textContent = t === 'dark' ? '☀ Light' : '🌙 Dark';
  }}

  (function init() {{
    // Theme
    var saved = null;
    try {{ saved = localStorage.getItem('sr-theme'); }} catch(e) {{}}
    if (saved) {{
      applyTheme(saved);
    }} else if (window.matchMedia('(prefers-color-scheme: dark)').matches) {{
      applyTheme('dark');
    }}
    // View
    var view = null;
    try {{ view = localStorage.getItem('sr-view'); }} catch(e) {{}}
    if (view) setView(view);
  }})();
</script>
</body>
</html>'''

    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(doc)
    print(f'HTML written to: {html_path}')
    return html_path


if __name__ == '__main__':
    from ShoppingAssistant.tools.shopping_tools import fetch_latest_report

    output_dir = os.environ.get('SHOPPING_OUTPUT_DIR', '.')
    verified   = os.path.join(output_dir, 'SHOPPING_REPORT_verified.json')
    html_path  = os.path.join(output_dir, 'SHOPPING_REPORT.html')

    if os.path.exists(verified):
        with open(verified, 'r', encoding='utf-8') as f:
            report_obj = json.load(f)
        print('Loaded verified JSON.')
    else:
        row = fetch_latest_report()
        if not row:
            print('No report found.')
            sys.exit(1)
        report_obj = json.loads(row['content'])
        print('Loaded report from DB.')

    generate(report_obj, html_path)
