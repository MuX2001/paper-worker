"""Replace a managed analysis with optimistic locking and protected-content validation."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import yaml
from validate import BEGIN, END, MUTABLE, validate


def render_update(original, body, fields):
    text = original.decode('utf-8-sig')
    if set(fields) - MUTABLE:
        raise ValueError('Refusing human-owned or unknown metadata fields')
    if BEGIN in body or END in body:
        raise ValueError('Supply the region content without ownership markers')
    if text.count(BEGIN) != 1 or text.count(END) != 1:
        raise ValueError('Legacy adoption requires a separate reviewed migration')
    header = re.match(r'\A---\r?\n(.*?)\r?\n---\r?\n', text, re.S)
    if not header:
        raise ValueError('Missing frontmatter')
    nl = '\r\n' if '\r\n' in text else '\n'
    raw = header[1].replace('\r\n', '\n') + '\n'
    for key, value in fields.items():
        entry = yaml.safe_dump({key: value}, allow_unicode=True, sort_keys=False).rstrip() + '\n'
        pattern = re.compile(r'^' + re.escape(key) + r':[^\n]*(?:\n(?![^\s#][^\n]*:)[^\n]*)*\n?', re.M)
        matches = list(pattern.finditer(raw))
        if len(matches) > 1:
            raise ValueError('Duplicate metadata field: ' + key)
        if matches:
            m = matches[0]
            raw = raw[:m.start()] + entry + raw[m.end():]
        else:
            raw += entry
    text = '---' + nl + raw.replace('\n', nl) + '---' + nl + text[header.end():]
    prefix, rest = text.split(BEGIN)
    _, suffix = rest.split(END)
    candidate = prefix + BEGIN + nl + body.strip().replace('\r\n', '\n').replace('\n', nl) + nl + nl + END + suffix
    errors = validate(candidate, original.decode('utf-8-sig'))
    if errors:
        raise ValueError('; '.join(errors))
    bom = b'\xef\xbb\xbf' if original.startswith(b'\xef\xbb\xbf') else b''
    return bom + candidate.encode('utf-8')


def update(note, body, fields, expected_sha256):
    original = note.read_bytes()
    if hashlib.sha256(original).hexdigest() != expected_sha256:
        raise ValueError('Note changed after snapshot; re-read before updating')
    candidate = render_update(original, body, fields)
    if candidate == original:
        return False
    fd, name = tempfile.mkstemp(prefix='.paper-update-', suffix='.tmp', dir=note.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(candidate)
        if note.read_bytes() != original:
            raise ValueError('Concurrent edit detected; no overwrite')
        os.replace(name, note)
    finally:
        if os.path.exists(name):
            os.unlink(name)
    return True


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('note', type=Path)
    p.add_argument('--body', type=Path, required=True)
    p.add_argument('--metadata', type=Path)
    p.add_argument('--expected-sha256', required=True)
    args = p.parse_args()
    fields = json.loads(args.metadata.read_text(encoding='utf-8')) if args.metadata else {}
    changed = update(args.note, args.body.read_text(encoding='utf-8'), fields, args.expected_sha256)
    print(json.dumps({'changed': changed, 'sha256': hashlib.sha256(args.note.read_bytes()).hexdigest()}))
