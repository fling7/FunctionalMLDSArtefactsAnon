"""Deterministic metadata cleanup for generated, static research figures."""
from pathlib import Path
import argparse
import hashlib
import io
import json
import re

ROOT = Path(__file__).resolve().parents[1]
FIGURE_DIRS = ("paper_inputs/figures", "output/metamodel_v2/figures")

def pdf_bytes(data):
    """Keep page content and resources; omit document identity and timestamps."""
    from pypdf import PdfReader, PdfWriter
    reader = PdfReader(io.BytesIO(data))
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    writer.metadata = None
    writer.root_object.pop("/Metadata", None)
    stream = io.BytesIO()
    writer.write(stream)
    return stream.getvalue()

def svg_bytes(data):
    """Drop metadata and stabilize opaque Matplotlib IDs after label renaming."""
    text = re.sub(r"<metadata\b[^>]*>.*?</metadata>", "", data.decode("utf-8"),
                  flags=re.S | re.I)
    pattern = r"""\bid=(["'])([mp][0-9a-f]{10})\1"""
    identifiers = list(dict.fromkeys(match.group(2) for match in re.finditer(pattern, text)))
    mapping = {value: f"figure-id-{index:04d}" for index, value in enumerate(identifiers, 1)}
    text = re.sub(pattern, lambda match: "id=" + match.group(1) + mapping[match.group(2)] + match.group(1), text)
    if mapping:
        references = r"#(" + "|".join(map(re.escape, mapping)) + r")(?![\w-])"
        text = re.sub(references, lambda match: "#" + mapping[match.group(1)], text)
    return text.replace("\r\n", "\n").encode("utf-8")

def png_bytes(data):
    """Canonical RGBA pixel encoding without ancillary document metadata."""
    from PIL import Image
    with Image.open(io.BytesIO(data)) as source:
        rgba = source.convert("RGBA")
        clean = Image.frombytes("RGBA", rgba.size, rgba.tobytes())
    stream = io.BytesIO()
    clean.save(stream, format="PNG", compress_level=9)
    return stream.getvalue()

def normalize(root=ROOT):
    root = Path(root)
    records = []
    for relative in FIGURE_DIRS:
        folder = root / relative
        for path in sorted(folder.glob("*")):
            suffix = path.suffix.lower()
            if not path.is_file() or suffix not in {".pdf", ".svg", ".png"}:
                continue
            before = path.read_bytes()
            after = {".pdf": pdf_bytes, ".svg": svg_bytes, ".png": png_bytes}[suffix](before)
            if before != after:
                path.write_bytes(after)
            records.append({"path": path.relative_to(root).as_posix(),
                            "sha256": hashlib.sha256(after).hexdigest(),
                            "bytes": len(after)})
    report = {"schema": "static-figure-metadata-normalization-v2",
              "policy": "Page-only PDF without document metadata; SVG metadata removed and opaque IDs stabilized; PNG pixel-preserving RGBA encoding without metadata.",
              "files": records}
    output = root / "results/processed/figure_metadata_normalization.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    result = normalize(parser.parse_args().root)
    print(json.dumps({"normalized_figures": len(result["files"])}))

if __name__ == "__main__":
    main()
