"""Extract text from a reportlab-generated PDF without external dependencies.

Used to verify report structure in environments where pypdf/poppler are absent.

    python scripts/inspect_pdf.py data/reports/DeepTrace_Report_INV2.pdf
"""

import base64
import re
import sys
import zlib

TEXT_STRING = re.compile(r"\((?:\\.|[^()\\])*\)", re.S)
SECTION = re.compile(r"^(\d{1,2})\. ([A-Z].{4,70})$")


def decode_stream(payload: bytes) -> bytes | None:
    """reportlab writes ASCII85 over Flate, so both layers have to come off."""
    candidate = payload.strip()
    cut = candidate.find(b"~>")
    if cut != -1:
        try:
            candidate = base64.a85decode(candidate[:cut])
        except Exception:
            return None
    try:
        return zlib.decompress(candidate)
    except Exception:
        return None


def extract(path: str) -> str:
    raw = open(path, "rb").read()
    pieces = []
    # reportlab emits "stream\n<data>~>endstream" with no newline before the
    # closing keyword, so the terminator must not be anchored to a line break.
    for match in re.finditer(rb"stream\r?\n(.*?)endstream", raw, re.S):
        decoded = decode_stream(match.group(1))
        if decoded:
            pieces.append(decoded)
    body = b"\n".join(pieces).decode("latin-1")
    out = []
    for token in TEXT_STRING.findall(body):
        inner = token[1:-1]
        inner = re.sub(r"\\(\d{1,3})", lambda m: chr(int(m.group(1), 8)), inner)
        inner = re.sub(r"\\([()\\])", r"\1", inner)
        out.append(inner)
    return "\n".join(out)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    path = sys.argv[1]
    raw = open(path, "rb").read()
    pages = raw.count(b"/Type /Page") - raw.count(b"/Type /Pages")
    text = extract(path)
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    print(f"file: {path}")
    print(f"pages: {pages}")
    print(f"text runs: {len(lines)}")

    sections = []
    for line in lines:
        found = SECTION.match(line)
        if found and found.group(1) not in {s[0] for s in sections}:
            sections.append((found.group(1), found.group(2)))
    print(f"\nnumbered sections: {len(sections)}")
    for number, name in sections:
        print(f"  {number:>2}. {name}")

    if len(sys.argv) > 2 and sys.argv[2] == "--full":
        print("\n--- text ---")
        for line in lines:
            print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
