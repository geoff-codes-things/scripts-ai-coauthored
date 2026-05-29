#!/usr/bin/env python3
# release_tools.py
#
# Importable functions for the release note pipeline.
# Used by release_writer and release_editor agents, and by the CLI wrappers.

import sqlite3
import os
import json
import urllib.request

VALID_TYPES = ('New Features', 'Enhancements', 'Bug Fixes')


def _get_output_dir():
    env = os.environ.get('RELEASE_OUTPUT_DIR')
    if env:
        return env
    # Fallback: two levels up from this file (Orchestrator/)
    return os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

def _db_path():
    return os.path.join(_get_output_dir(), 'release_data.db')

def _notes_path():
    return os.path.join(_get_output_dir(), 'RELEASE_NOTES.md')


def _ensure_schema(conn):
    conn.execute('''
        CREATE TABLE IF NOT EXISTS commits (
            sha TEXT PRIMARY KEY,
            repo TEXT,
            url TEXT,
            message TEXT,
            author TEXT,
            date TEXT,
            skip_reason TEXT
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS commit_files (
            sha TEXT,
            filename TEXT,
            status TEXT,
            additions INTEGER,
            deletions INTEGER,
            patch TEXT
        )
    ''')
    conn.commit()


# ── GitHub fetch + store ─────────────────────────────────────────────────────

# Fetches a GitHub commit by URL, saves it to release_data.db, and returns the data dict.
def store_commit_data(url, token=None):
    parts = url.rstrip('/').split('/')
    try:
        idx   = parts.index('commit')
        sha   = parts[idx + 1]
        repo  = parts[idx - 1]
        owner = parts[idx - 2]
    except (ValueError, IndexError):
        raise ValueError(f"Cannot parse GitHub commit URL: {url}")

    api_url = f"https://api.github.com/repos/{owner}/{repo}/commits/{sha}"
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "release-tools"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = urllib.request.Request(api_url, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())

    sha_full   = data['sha']
    message    = data['commit']['message']
    author     = data['commit']['author']['name']
    date       = data['commit']['author']['date']
    repo_slug  = f"{owner}/{repo}"
    commit_url = f"https://github.com/{owner}/{repo}/commit/{sha_full}"

    files = [
        {
            'filename':  f['filename'],
            'status':    f.get('status', 'modified'),
            'additions': f.get('additions', 0),
            'deletions': f.get('deletions', 0),
            'patch':     f.get('patch', ''),
        }
        for f in data.get('files', [])
    ]

    conn = sqlite3.connect(_db_path())
    _ensure_schema(conn)
    c = conn.cursor()
    c.execute('INSERT OR REPLACE INTO commits (sha, repo, url, message, author, date) VALUES (?,?,?,?,?,?)',
              (sha_full, repo_slug, commit_url, message, author, date))
    c.execute('DELETE FROM commit_files WHERE sha = ?', (sha_full,))
    for f in files:
        c.execute(
            'INSERT INTO commit_files (sha, filename, status, additions, deletions, patch) VALUES (?,?,?,?,?,?)',
            (sha_full, f['filename'], f['status'], f['additions'], f['deletions'], f['patch'])
        )
    conn.commit()
    conn.close()

    return {
        'sha':     sha_full,
        'sha7':    sha_full[:7],
        'repo':    repo_slug,
        'url':     commit_url,
        'message': message,
        'author':  author,
        'date':    date[:10],
        'files':   files,
    }

# ── Skip tracking ────────────────────────────────────────────────────────────

# Marks a commit as not needing a release note, storing the reason in the DB.
def mark_commit_skip(sha, reason):
    conn = sqlite3.connect(_db_path())
    _ensure_schema(conn)
    c = conn.cursor()
    try:
        c.execute('ALTER TABLE commits ADD COLUMN skip_reason TEXT')
    except sqlite3.OperationalError:
        pass  # column already exists
    c.execute(
        'UPDATE commits SET skip_reason = ? WHERE sha LIKE ?',
        (reason, sha[:7] + '%')
    )
    conn.commit()
    conn.close()

# Returns a dict mapping sha7 -> skip_reason for all skipped commits.
def get_skipped_sha7s():
    db = _db_path()
    if not os.path.exists(db):
        return {}
    conn = sqlite3.connect(db)
    c = conn.cursor()
    try:
        c.execute('SELECT sha, skip_reason FROM commits WHERE skip_reason IS NOT NULL')
        result = {row[0][:7]: row[1] for row in c.fetchall()}
    except sqlite3.OperationalError:
        result = {}
    conn.close()
    return result

# ── Data access ──────────────────────────────────────────────────────────────

# Returns a dict with commit metadata and file list for the given SHA prefix.
def fetch_commit_data(sha):
    conn = sqlite3.connect(_db_path())
    c = conn.cursor()
    c.execute(
        'SELECT sha, repo, url, message, author, date FROM commits WHERE sha LIKE ?',
        (sha[:7] + '%',)
    )
    row = c.fetchone()
    if not row:
        raise ValueError(f"Commit '{sha[:7]}' not found in database.")
    sha_full, repo, url, message, author, date_iso = row

    c.execute(
        'SELECT filename, status, additions, deletions, patch FROM commit_files WHERE sha = ?',
        (sha_full,)
    )
    files = [
        {'filename': f[0], 'status': f[1], 'additions': f[2], 'deletions': f[3], 'patch': f[4]}
        for f in c.fetchall()
    ]
    conn.close()

    return {
        'sha':     sha_full,
        'sha7':    sha_full[:7],
        'repo':    repo,
        'url':     url,
        'message': message,
        'author':  author,
        'date':    date_iso[:10],
        'files':   files,
    }

# Returns the RELEASE_NOTES.md section (date block) that contains this SHA's entry.
def fetch_note_entry(sha):
    sha7 = sha[:7]
    notes = _notes_path()
    if not os.path.exists(notes):
        return None
    with open(notes, 'r', encoding='utf-8') as f:
        content = f.read()
    if f'[{sha7}]' not in content:
        return None
    sha_pos = content.index(f'[{sha7}]')
    section_start = content.rfind('\n## ', 0, sha_pos)
    section_start = section_start + 1 if section_start != -1 else 0
    section_end = content.find('\n---\n', sha_pos)
    section_end = section_end + 5 if section_end != -1 else len(content)
    return content[section_start:section_end].strip()

# Returns commit data + the release note entry for that SHA — everything the editor needs.
def fetch_editor_data(sha):
    return {
        'commit':     fetch_commit_data(sha),
        'note_entry': fetch_note_entry(sha),
    }

# Prints a formatted summary of commit data and release note entry for the editor agent.
# Called directly from the editor's script so output is guaranteed regardless of how
# the LLM writes the calling code.
def print_editor_data(sha):
    data   = fetch_editor_data(sha)
    commit = data['commit']
    print('SHA7:', commit['sha7'])
    print('URL:', commit['url'])
    print('Date:', commit['date'])
    print('Message:', commit['message'])
    for f in commit['files']:
        print(f"  [{f['status']}] {f['filename']} (+{f['additions']}/-{f['deletions']})")
        if f['patch']:
            print('  Patch:', f['patch'][:400])
    print('\n--- Release Note Entry ---')
    print(data['note_entry'] if data['note_entry'] else '(no entry found for this SHA)')

# ── File writing ─────────────────────────────────────────────────────────────

def _notes_header(repo):
    branch = os.environ.get('RELEASE_BRANCH', '').strip()
    if branch:
        return f'# Release Notes for {repo} — {branch}\n'
    return f'# Release Notes for {repo}\n'

# Inserts a formatted release note entry into RELEASE_NOTES.md.
def write_release_entry(sha, summary, change_type):
    if change_type not in VALID_TYPES:
        raise ValueError(f"change_type must be one of {VALID_TYPES}, got: {change_type!r}")

    data       = fetch_commit_data(sha)
    sha7       = data['sha7']
    repo       = data['repo']
    commit_url = data['url']
    date_str   = data['date']

    header   = _notes_header(repo)
    date_hdr = f'## {date_str}\n'
    bullet   = f'* {summary} ([{sha7}]({commit_url}))\n'

    notes = _notes_path()
    if os.path.exists(notes):
        with open(notes, 'r', encoding='utf-8') as f:
            content = f.read()
        # Update the header line in-place if the branch label changed or was missing.
        if content.startswith('# Release Notes for '):
            first_newline = content.index('\n')
            content = header + content[first_newline:]
    else:
        content = header + '\n'

    if not content.startswith('# Release Notes'):
        content = header + '\n' + content

    if sha7 in content:
        return f"Entry for {sha7} already exists — skipping."

    if date_hdr in content:
        date_idx   = content.index(date_hdr)
        target     = f'### {change_type}\n'
        target_idx = content.index(target, date_idx)
        insert_at  = target_idx + len(target)
        after      = content[insert_at:]
        if after.startswith('_None_\n'):
            content = content[:insert_at] + bullet + content[insert_at + 7:]
        else:
            content = content[:insert_at] + bullet + content[insert_at:]
    else:
        nf = bullet if change_type == 'New Features'  else '_None_\n'
        en = bullet if change_type == 'Enhancements'  else '_None_\n'
        bf = bullet if change_type == 'Bug Fixes'     else '_None_\n'
        new_section = (
            f'\n{date_hdr}'
            f'\n### New Features\n{nf}'
            f'\n### Enhancements\n{en}'
            f'\n### Bug Fixes\n{bf}'
            f'\n---\n'
        )
        insert_pos = len(header)
        content = content[:insert_pos] + new_section + '\n' + content[insert_pos:].lstrip('\n')

    with open(notes, 'w', encoding='utf-8') as f:
        f.write(content)

    return f"Written: {bullet.strip()}\nChange type: {change_type}\nDate: {date_str}\nFile: {notes}"
