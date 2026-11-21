"""Plain-text extraction from legacy binary Word (.doc, Word 97-2003) files. No external converter is needed."""
from __future__ import annotations

import re
import struct
from io import BytesIO
from typing import List

OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


class LegacyDocError(ValueError):
    pass


def is_legacy_doc(data: bytes) -> bool:
    return data.startswith(OLE_MAGIC)


def extract_paragraphs(data: bytes) -> List[str]:
    import olefile

    try:
        ole = olefile.OleFileIO(BytesIO(data))
        word = ole.openstream("WordDocument").read()
    except Exception as exc:
        raise LegacyDocError("not a Word document") from exc
    try:
        if struct.unpack_from("<H", word, 0)[0] != 0xA5EC:
            raise LegacyDocError("not a Word document")
        flags = struct.unpack_from("<H", word, 0x0A)[0]
        if flags & 0x0100:
            raise LegacyDocError("encrypted")
        table = ole.openstream("1Table" if flags & 0x0200 else "0Table").read()
        ccp_text = struct.unpack_from("<i", word, 0x4C)[0]
        fc_clx, lcb_clx = struct.unpack_from("<II", word, 0x1A2)
        clx = table[fc_clx:fc_clx + lcb_clx]
        i = 0
        while clx[i] == 1:  # skip Prc entries
            i += 3 + struct.unpack_from("<H", clx, i + 1)[0]
        if clx[i] != 2:
            raise LegacyDocError("no piece table")
        size = struct.unpack_from("<I", clx, i + 1)[0]
        plc = clx[i + 5:i + 5 + size]
    except LegacyDocError:
        raise
    except Exception as exc:
        raise LegacyDocError("unreadable structure") from exc
    n = (size - 4) // 12
    cps = struct.unpack_from(f"<{n + 1}I", plc, 0)
    parts: List[str] = []
    for k in range(n):
        start, end = cps[k], min(cps[k + 1], ccp_text)
        if end <= start:
            continue
        fc = struct.unpack_from("<I", plc, 4 * (n + 1) + 8 * k + 2)[0]
        length = end - start
        if fc & 0x40000000:
            off = (fc & 0x3FFFFFFF) // 2
            parts.append(word[off:off + length].decode("cp1252", errors="replace"))
        else:
            parts.append(word[fc:fc + 2 * length].decode("utf-16-le", errors="replace"))
    text = "".join(parts)
    text = re.sub(r"\x13[^\x14\x15]*\x14?", "", text).replace("\x15", "")  # field codes, keep results
    text = text.replace("\x07", "\r").replace("\x0b", " ").replace("\x0c", "\r").replace("\u00a0", " ")
    text = re.sub(r"[\x00-\x08\x0e-\x1f\x01]", "", text)
    return [p.strip() for p in re.split(r"[\r\n]+", text) if p.strip()]
