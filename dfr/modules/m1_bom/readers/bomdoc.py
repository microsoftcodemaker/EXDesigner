"""Altium LiveBOM ``.BomDoc`` reader (PRD 3.1, BOM-11).

Format (from the supplied sample): Latin-1, CRLF, one record per line, fields
``|KEY=VALUE|KEY=VALUE...``. ``RECORD=CatalogItem`` rows carry ``DESCRIPTION`` and
``USERCOMMENTS`` (= MPN). ``RECORD=PartChoice`` rows carry supplier data and
``DATASHEETS`` URLs, which are stored as links and never fetched. The file has no
designators: parts are joined to the netlist by MPN (NET-10).
"""

from __future__ import annotations

import hashlib

from dfr.core.contracts import BomImportResult, RawPart
from dfr.core.diagnostics import DiagnosticSink

FORMAT_ID = "altium_bomdoc"
_ENCODING = "latin-1"
_URL_SEP = "\ufffd"  # Altium writes U+FFFD-like separators between URLs; also split on whitespace


class BomDocReader:
    id = FORMAT_ID
    extensions: tuple[str, ...] = (".bomdoc",)

    def sniff(self, data: bytes, name: str) -> bool:
        head = data[:200].decode(_ENCODING, errors="replace")
        return head.startswith("|RECORD=BOM|") or "KIND=ALTIUM_DESIGNER_LIVEBOM" in head

    def read(self, data: bytes, name: str) -> BomImportResult:
        sink = DiagnosticSink("m1_bom")
        text = data.decode(_ENCODING)
        parts: list[RawPart] = []
        links: dict[str, list[str]] = {}
        seen_mpn: dict[str, int] = {}

        for line_no, line in enumerate(text.splitlines(), 1):
            if not line.startswith("|"):
                if line.strip():
                    sink.warning(
                        "BOMDOC_UNPARSED_LINE", "line does not start with '|'", line_no=line_no
                    )
                continue
            rec = parse_record(line)
            kind = rec.get("RECORD")
            if kind == "CatalogItem":
                mpn = rec.get("USERCOMMENTS", "").strip() or None
                desc = rec.get("DESCRIPTION", "").strip() or None
                if mpn is None and desc is None:
                    sink.warning(
                        "BOMDOC_EMPTY_ITEM",
                        "CatalogItem without MPN or description",
                        line_no=line_no,
                    )
                    continue
                if mpn and mpn in seen_mpn:
                    sink.warning(
                        "BOMDOC_DUPLICATE_MPN",
                        f"MPN {mpn!r} already seen on line {seen_mpn[mpn]}",
                        line_no=line_no,
                    )
                if mpn:
                    seen_mpn.setdefault(mpn, line_no)
                parts.append(
                    RawPart(
                        refdes=None,
                        description=desc,
                        mpn=mpn,
                        source_row=line_no,
                        extra={
                            k: v
                            for k, v in rec.items()
                            if k in ("DESIGNITEMID", "ITEMSOURCE", "STATUS", "NOTE") and v
                        },
                    )
                )
            elif kind == "PartChoice":
                mpn = rec.get("MANUFACTURERPARTNO", "").strip()
                urls = _split_urls(rec.get("DATASHEETS", ""))
                if mpn and urls:
                    bucket = links.setdefault(mpn, [])
                    bucket.extend(u for u in urls if u not in bucket)

        if not parts:
            sink.error("BOMDOC_NO_ITEMS", "no CatalogItem records found")
        return BomImportResult(
            raw_parts=parts,
            source_format=FORMAT_ID,
            source_hash=hashlib.sha256(data).hexdigest(),
            source_name=name,
            has_designators=False,
            links=links,
            diagnostics=list(sink.items),
        )


def parse_record(line: str) -> dict[str, str]:
    """``|A=1|B=x=y|`` -> {"A": "1", "B": "x=y"}. Values may contain '=' but not '|'."""
    out: dict[str, str] = {}
    for field in line.strip().strip("|").split("|"):
        if "=" in field:
            key, _, value = field.partition("=")
            out[key] = value
    return out


def _split_urls(text: str) -> list[str]:
    if not text:
        return []
    for sep in (_URL_SEP, "\n", "\t", " "):
        text = text.replace(sep, "\x00")
    return [u for u in text.split("\x00") if u.startswith(("http://", "https://"))]
