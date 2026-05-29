#!/usr/bin/env python3
# shopping_tools.py
#
# Importable functions for the shopping assistant pipeline.
# Used by all five agents and by the pipeline directly.

import sqlite3
import os
import json
import re
from datetime import datetime


def _get_output_dir():
    env = os.environ.get('SHOPPING_OUTPUT_DIR')
    if env:
        return env
    # Fallback: two levels up from this file (Orchestrator/)
    return os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

def _db_path():
    return os.path.join(_get_output_dir(), 'shopping_data.db')

def _now():
    return datetime.utcnow().isoformat()


def _ensure_schema(conn):
    conn.execute('''
        CREATE TABLE IF NOT EXISTS session (
            session_id       TEXT PRIMARY KEY,
            raw_answers      TEXT,
            requirements     TEXT,
            status           TEXT DEFAULT 'collecting',
            pending_question TEXT,
            created_at       TEXT,
            updated_at       TEXT
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS products (
            product_id    INTEGER PRIMARY KEY AUTOINCREMENT,
            search_query  TEXT,
            result_index  INTEGER,
            url           TEXT,
            title         TEXT,
            price         TEXT,
            price_numeric REAL,
            summary       TEXT,
            pros          TEXT,
            cons          TEXT,
            availability  TEXT,
            purchase_url  TEXT,
            raw_snippet   TEXT,
            extracted_at  TEXT
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS report (
            report_id      INTEGER PRIMARY KEY AUTOINCREMENT,
            content        TEXT,
            iteration      INTEGER,
            status         TEXT DEFAULT 'draft',
            revision_notes TEXT,
            created_at     TEXT
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS candidates (
            candidate_id   INTEGER PRIMARY KEY AUTOINCREMENT,
            model_name     TEXT UNIQUE,
            source_snippet TEXT,
            researched     INTEGER DEFAULT 0,
            created_at     TEXT
        )
    ''')
    conn.commit()


# ── Session ──────────────────────────────────────────────────────────────────

def save_raw_answers(answers):
    conn = sqlite3.connect(_db_path())
    _ensure_schema(conn)
    now = _now()
    conn.execute('''
        INSERT INTO session (session_id, raw_answers, status, pending_question, created_at, updated_at)
        VALUES ('current', ?, 'collecting', NULL, ?, ?)
        ON CONFLICT(session_id) DO UPDATE SET
            raw_answers = excluded.raw_answers,
            status = 'collecting',
            pending_question = NULL,
            updated_at = excluded.updated_at
    ''', (answers, now, now))
    conn.commit()
    conn.close()
    print('Raw answers saved.')

def save_requirements(requirements):
    conn = sqlite3.connect(_db_path())
    _ensure_schema(conn)
    now = _now()
    conn.execute('''
        INSERT INTO session (session_id, requirements, status, updated_at, created_at)
        VALUES ('current', ?, 'complete', ?, ?)
        ON CONFLICT(session_id) DO UPDATE SET
            requirements = excluded.requirements,
            status = 'complete',
            updated_at = excluded.updated_at
    ''', (requirements, now, now))
    conn.commit()
    conn.close()
    print('Requirements saved.')

def save_pending_question(question):
    conn = sqlite3.connect(_db_path())
    _ensure_schema(conn)
    now = _now()
    conn.execute('''
        INSERT INTO session (session_id, pending_question, status, updated_at, created_at)
        VALUES ('current', ?, 'collecting', ?, ?)
        ON CONFLICT(session_id) DO UPDATE SET
            pending_question = excluded.pending_question,
            status = 'collecting',
            updated_at = excluded.updated_at
    ''', (question, now, now))
    conn.commit()
    conn.close()
    print('Pending question saved.')

def fetch_requirements():
    db = _db_path()
    if not os.path.exists(db):
        return None
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute('SELECT * FROM session WHERE session_id = "current"')
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    return dict(row)

def print_requirements():
    data = fetch_requirements()
    print('STATUS:', data['status'] if data else 'none')
    print('RAW ANSWERS:')
    print(data['raw_answers'] if data else '(no data)')


# ── Products ──────────────────────────────────────────────────────────────────

def _parse_price(price_str):
    if not price_str or price_str.strip().lower() == 'unknown':
        return None
    m = re.search(r'[\d,]+(?:\.\d{1,2})?', price_str.replace(',', ''))
    if m:
        try:
            return float(m.group().replace(',', ''))
        except ValueError:
            return None
    return None

def save_product_data(search_query, result_index, url, title, price,
                      summary, pros, cons, availability, purchase_url, raw_snippet):
    conn = sqlite3.connect(_db_path())
    _ensure_schema(conn)
    price_numeric = _parse_price(price)
    c = conn.cursor()
    c.execute('''
        INSERT INTO products
            (search_query, result_index, url, title, price, price_numeric,
             summary, pros, cons, availability, purchase_url, raw_snippet, extracted_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (search_query, result_index, url, title, price, price_numeric,
          summary, pros, cons, availability, purchase_url, raw_snippet, _now()))
    product_id = c.lastrowid
    conn.commit()
    conn.close()
    print(f'Saved product_id: {product_id}')
    return product_id

def fetch_all_products():
    db = _db_path()
    if not os.path.exists(db):
        return []
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute('SELECT * FROM products ORDER BY price_numeric ASC NULLS LAST')
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows

def fetch_product_count():
    db = _db_path()
    if not os.path.exists(db):
        return 0
    conn = sqlite3.connect(db)
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM products')
    count = c.fetchone()[0]
    conn.close()
    return count


# ── Candidates ────────────────────────────────────────────────────────────────

def save_candidate(model_name, source_snippet=''):
    conn = sqlite3.connect(_db_path())
    _ensure_schema(conn)
    c = conn.cursor()
    c.execute('''
        INSERT INTO candidates (model_name, source_snippet, researched, created_at)
        VALUES (?, ?, 0, ?)
        ON CONFLICT(model_name) DO NOTHING
    ''', (model_name.strip(), source_snippet, _now()))
    conn.commit()
    conn.close()
    print(f'Saved candidate: {model_name.strip()}')

def fetch_candidates(unresearched_only=False):
    db = _db_path()
    if not os.path.exists(db):
        return []
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    if unresearched_only:
        c.execute('SELECT * FROM candidates WHERE researched = 0 ORDER BY candidate_id ASC')
    else:
        c.execute('SELECT * FROM candidates ORDER BY candidate_id ASC')
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows

def fetch_candidate_count():
    db = _db_path()
    if not os.path.exists(db):
        return 0
    conn = sqlite3.connect(db)
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM candidates')
    count = c.fetchone()[0]
    conn.close()
    return count

def mark_candidate_researched(model_name):
    conn = sqlite3.connect(_db_path())
    _ensure_schema(conn)
    conn.execute('UPDATE candidates SET researched = 1 WHERE model_name = ?', (model_name,))
    conn.commit()
    conn.close()
    print(f'Marked researched: {model_name}')


# ── Report ────────────────────────────────────────────────────────────────────

def save_report(content, iteration):
    conn = sqlite3.connect(_db_path())
    _ensure_schema(conn)
    c = conn.cursor()
    c.execute('''
        INSERT INTO report (content, iteration, status, created_at)
        VALUES (?, ?, 'draft', ?)
    ''', (content, iteration, _now()))
    report_id = c.lastrowid
    conn.commit()
    conn.close()
    print(f'Saved report_id: {report_id}')
    return report_id

def update_report_status(report_id, status, revision_notes=None):
    conn = sqlite3.connect(_db_path())
    _ensure_schema(conn)
    conn.execute('''
        UPDATE report SET status = ?, revision_notes = ? WHERE report_id = ?
    ''', (status, revision_notes, report_id))
    conn.commit()
    conn.close()
    print('Status updated.')

def fetch_latest_report():
    db = _db_path()
    if not os.path.exists(db):
        return None
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute('SELECT * FROM report ORDER BY report_id DESC LIMIT 1')
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    return dict(row)


# ── Search ────────────────────────────────────────────────────────────────────

def run_ddg_search(query, max_results=5):
    from ddgs import DDGS
    results = []
    with DDGS() as ddgs:
        for r in ddgs.text(query, max_results=max_results):
            results.append(r)
    return results
