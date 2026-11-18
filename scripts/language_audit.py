#!/usr/bin/env python3
"""MADLAD technical audit (Stage 1 of the language-expansion process).

Run with the *inference* virtualenv (it has sentencepiece):

    ~/.han-venvs/inference/bin/python scripts/language_audit.py checkpoint --out docs/reports/madlad-audit/checkpoint.json
    ~/.han-venvs/inference/bin/python scripts/language_audit.py probe --url http://127.0.0.1:9030 \
        --token-file ~/han-data-prod/han.env --out docs/reports/madlad-audit/probe-results.json

`checkpoint` identifies the exact downloaded artefact (repository, revision, file sizes and SHA-256, model shape, licence from the
model card) and classifies every `<2xx>` token in the SentencePiece vocabulary.

`probe` sends a fixed, non-confidential probe sentence English -> X for each language token, then translates the output back
X -> English (a round trip). It records latency, outputs and simple degeneracy heuristics. It is sequential and idempotent (resumable).

IMPORTANT: this is a TECHNICAL check only. "passed" means the model produced non-degenerate output in both directions. It says nothing
about translation quality. Quality is established only by qualified human translators (Stage 2); until then every language is
at most Tier 3 / Experimental.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
import struct
import sys
import time
import urllib.request
import zlib
from datetime import datetime, timezone
from pathlib import Path

HOME = Path.home()
MODEL_ROOT = HOME / "han-models" / ".hf" / "hub" / "models--google--madlad400-3b-mt"
PROBE_TEXT = "Good morning, everyone."
PLAIN = re.compile(r"^<2([a-z]{2,3})>$")
CONTROL = re.compile(r"(_xx_|noise|simple)|^<2[A-Z][a-z]{3}>$")  # control tokens and bare script tokens are not languages


def snapshot() -> Path:
    snaps = sorted((MODEL_ROOT / "snapshots").iterdir())
    if not snaps:
        raise SystemExit(f"no MADLAD snapshot under {MODEL_ROOT}")
    return snaps[-1]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 22), b""):
            h.update(block)
    return h.hexdigest()


def safetensors_summary(path: Path) -> dict:
    with open(path, "rb") as f:
        n = struct.unpack("<Q", f.read(8))[0]
        header = json.loads(f.read(n))
    total = 0
    dtypes = set()
    for k, v in header.items():
        if k == "__metadata__":
            continue
        count = 1
        for d in v["shape"]:
            count *= d
        total += count
        dtypes.add(v["dtype"])
    return {"tensors": len(header) - ("__metadata__" in header), "parameters": total, "dtypes": sorted(dtypes)}


def language_tokens() -> list[str]:
    import sentencepiece as spm

    sp = spm.SentencePieceProcessor()
    sp.load(str(snapshot() / "spiece.model"))
    return [t for t in (sp.id_to_piece(i) for i in range(sp.get_piece_size())) if re.fullmatch(r"<2[^>]+>", t)]


def classify(tokens: list[str]) -> dict:
    out = {"plain": [], "variant": [], "control": []}
    for t in sorted(tokens):
        if PLAIN.match(t):
            out["plain"].append(t[2:-1])
        elif CONTROL.search(t):
            out["control"].append(t[2:-1])
        else:
            out["variant"].append(t[2:-1])
    return out


def cmd_checkpoint(args: argparse.Namespace) -> None:
    snap = snapshot()
    cfg = json.loads((snap / "config.json").read_text())
    card = (snap / "README.md").read_text(errors="replace")
    front = card.split("---")[1] if card.startswith("---") else ""
    lic = re.search(r"^license:\s*(\S+)", front, re.M)
    files = {}
    for p in sorted(snap.iterdir()):
        real = p.resolve()
        files[p.name] = {"bytes": real.stat().st_size, "sha256": sha256(real) if p.suffix in (".safetensors", ".json", ".model") else None}
    toks = classify(language_tokens())
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "repository": "google/madlad400-3b-mt",
        "revision": snap.name,
        "licence_from_model_card": lic.group(1) if lic else None,
        "architecture": cfg.get("architectures"),
        "model_shape": {k: cfg.get(k) for k in ("d_model", "d_ff", "num_layers", "num_decoder_layers", "num_heads", "vocab_size")},
        "weights": safetensors_summary(snap / "model.safetensors"),
        "files": files,
        "variant_note": "This is the 3B checkpoint (google/madlad400-3b-mt), not the 7B variant referenced in some documents.",
        "language_tokens": {
            "plain_codes": len(toks["plain"]), "variant_tokens": len(toks["variant"]), "control_tokens": len(toks["control"]),
            "plain": toks["plain"], "variants": toks["variant"], "control": toks["control"],
        },
        "model_card_statements": [l.strip(" >") for l in card.splitlines() if re.search(r"157 languages|204 of the languages|varies based on language|over 400 languages", l)],
        "prompt_format": "'<2xx> source text' where xx selects the TARGET language; the source language is not specified.",
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    t = report["language_tokens"]
    print(f"revision {snap.name}\nparameters {report['weights']['parameters']:,}  licence {report['licence_from_model_card']}")
    print(f"language tokens: {t['plain_codes']} plain, {t['variant_tokens']} variants, {t['control_tokens']} control -> {args.out}")


# ---------------------------------------------------------------------------------------------------- probe
def post(url: str, token: str, body: dict, timeout: float = 300) -> dict:
    req = urllib.request.Request(url + "/translate", data=json.dumps(body).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def degenerate(text: str, source: str) -> str | None:
    t = text.strip()
    if not t:
        return "empty"
    if t.casefold() == source.strip().casefold():
        return "echoes_input"
    raw = t.encode()
    if len(raw) > 40 and len(zlib.compress(raw)) / len(raw) < 0.22:
        return "repetition_loop"
    words = t.split()
    if len(words) >= 6 and len(set(words)) / len(words) < 0.25:
        return "repetition_loop"
    if len(t) > 12 * len(source):
        return "runaway_length"
    return None


def probe_one(url: str, token: str, code: str) -> dict:
    rec: dict = {"code": code}
    try:
        t0 = time.time()
        fwd = post(url, token, {"family": "madlad", "text": f"<2{code}> {PROBE_TEXT}", "target_lang": code})["translation"]
        rec["forward"] = {"output": fwd, "seconds": round(time.time() - t0, 2), "flag": degenerate(fwd, PROBE_TEXT)}
        t1 = time.time()
        back = post(url, token, {"family": "madlad", "text": f"<2en> {fwd}", "target_lang": "en"})["translation"]
        rec["reverse"] = {"output": back, "seconds": round(time.time() - t1, 2), "flag": degenerate(back, fwd)}
        rec["roundtrip_similarity"] = round(difflib.SequenceMatcher(None, PROBE_TEXT.casefold(), back.casefold()).ratio(), 3)
        flags = [x for x in (rec["forward"]["flag"], rec["reverse"]["flag"]) if x]
        rec["status"] = "degraded" if flags else "passed"
        rec["flags"] = flags
    except Exception as e:  # noqa: BLE001
        rec["status"], rec["flags"], rec["error"] = "failed", ["request_failed"], str(e)[:200]
    return rec


def cmd_probe(args: argparse.Namespace) -> None:
    token = next(l.split("=", 1)[1] for l in Path(args.token_file).expanduser().read_text().splitlines() if l.startswith("HAN_INFERENCE_TOKEN="))
    toks = classify(language_tokens())
    codes = toks["plain"] + (toks["variant"] if args.variants else [])
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    done: dict = json.loads(out.read_text())["results"] if out.exists() else {}
    todo = [c for c in codes if c not in done and c != "en"][: args.limit or None]
    print(f"{len(done)} already probed, {len(todo)} to go", flush=True)
    started = time.time()
    for i, code in enumerate(todo, 1):
        done[code] = probe_one(args.url, token, code)
        if i % 10 == 0 or i == len(todo):
            out.write_text(json.dumps({"probe_text": PROBE_TEXT, "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                       "note": "Technical check only; not a quality assessment.", "results": done}, indent=1, ensure_ascii=False) + "\n")
            n = {s: sum(1 for r in done.values() if r["status"] == s) for s in ("passed", "degraded", "failed")}
            print(f"[{i}/{len(todo)}] {code}  {n}  {int(time.time() - started)}s", flush=True)
        time.sleep(args.pause)
    print("probe complete", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("checkpoint")
    c.add_argument("--out", required=True)
    p = sub.add_parser("probe")
    p.add_argument("--url", default="http://127.0.0.1:9030")
    p.add_argument("--token-file", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--variants", action="store_true", help="also probe script/region variant tokens")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--pause", type=float, default=0.3, help="seconds between languages (keeps the service responsive for translators)")
    args = ap.parse_args()
    {"checkpoint": cmd_checkpoint, "probe": cmd_probe}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
