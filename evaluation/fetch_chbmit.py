"""
Fetch CHB-MIT recordings and keep only the channels Vera can see.

For every EDF: download (PhysioNet AWS open-data mirror, or read from a local /
attached copy), extract FP1-F7 and FP2-F8 as raw int16 + calibration header
(`<rec>.ch.bin` / `<rec>.ch.json`), then delete the EDF.  If a recording uses a
referential montage (e.g. some chb12 files), the bipolar channel is derived as
FP1-ref − F7-ref and flagged `derived` in the json.

Selection (default): every recording that contains a seizure (141 files,
198 seizures) + the first seizure-free recording of every patient
(+ chb01_01 and chb01_02) for additional false-alarm hours.

usage: python fetch_chbmit.py --out data/chbmit [--local /kaggle/input/...] [--workers 6]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np

S3 = "https://physionet-open.s3.amazonaws.com/chbmit/1.0.0/"
WANT = {"FP1-F7": ("FP1", "F7"), "FP2-F8": ("FP2", "F8")}
CASES = [f"chb{i:02d}" for i in range(1, 25)]


def _get(url, tries=4):
    import requests
    for k in range(tries):
        try:
            r = requests.get(url, timeout=120)
            r.raise_for_status()
            return r.content
        except Exception:
            if k == tries - 1:
                raise
            time.sleep(2 * (k + 1))


def read_edf_channels(buf: bytes):
    """Minimal EDF reader → (meta, {label: int16 array})."""
    h = lambda o, l: buf[o:o + l].decode("ascii", "replace").strip()
    nrec, dur, ns = int(h(236, 8)), float(h(244, 8)), int(h(252, 4))
    o = 256
    def field(w):
        nonlocal o
        v = [h(o + i * w, w) for i in range(ns)]; o += ns * w; return v
    labels = field(16); field(80); dim = field(8)
    pmin = list(map(float, field(8))); pmax = list(map(float, field(8)))
    dmin = list(map(float, field(8))); dmax = list(map(float, field(8)))
    field(80); nsamp = list(map(int, field(8))); field(32)
    hdr = 256 + ns * 256
    rec_len = sum(nsamp)
    n_real = (len(buf) - hdr) // (rec_len * 2)
    nrec = min(nrec if nrec > 0 else n_real, n_real)
    data = np.frombuffer(buf, dtype="<i2", count=nrec * rec_len, offset=hdr).reshape(nrec, rec_len)
    offs = np.concatenate([[0], np.cumsum(nsamp)[:-1]])
    def chan(i):
        return data[:, offs[i]:offs[i] + nsamp[i]].reshape(-1)
    return dict(labels=labels, dim=dim, pmin=pmin, pmax=pmax, dmin=dmin, dmax=dmax,
                nsamp=nsamp, dur=dur), chan


def _bipolar_path(labels_upper, a, b):
    """Shortest chain of bipolar channels from electrode a to b → [(index, ±1), ...]."""
    from collections import deque
    adj = {}
    for k, l in enumerate(labels_upper):
        parts = l.split("-")
        if len(parts) != 2 or not parts[0] or not parts[1]:
            continue
        x, y = parts
        adj.setdefault(x, []).append((y, k, +1))     # x - y : stepping x→y adds +(x−y)
        adj.setdefault(y, []).append((x, k, -1))     # stepping y→x adds −(x−y)
    prev = {a: None}
    q = deque([a])
    while q:
        u = q.popleft()
        if u == b:
            break
        for v, k, s in adj.get(u, []):
            if v not in prev:
                prev[v] = (u, k, s); q.append(v)
    if b not in prev:
        return None
    path, node = [], b
    while prev[node] is not None:
        u, k, s = prev[node]; path.append((k, s)); node = u
    return path[::-1]


def extract(buf: bytes, source: str, out_dir: Path, name: str):
    H, chan = read_edf_channels(buf)
    # plain electrode names (e.g. chb12_28: "FP1", "F7", … against a common
    # reference) are treated as "<name>-REF" so referential montages work too
    up = [l.upper() if ("-" in l or not l.strip()) else l.upper().strip() + "-REF" for l in H["labels"]]
    cols, meta = [], dict(source=source, labels=[], dim=[], phys_min=[], phys_max=[],
                          dig_min=[], dig_max=[], derived=[], missing=[], all_labels=H["labels"])
    for want, (a, b) in WANT.items():
        if want in up:
            i = up.index(want)
            cols.append(chan(i).astype(np.int16))
            meta["labels"].append(want); meta["dim"].append(H["dim"][i])
            meta["phys_min"].append(H["pmin"][i]); meta["phys_max"].append(H["pmax"][i])
            meta["dig_min"].append(H["dmin"][i]); meta["dig_max"].append(H["dmax"][i])
            meta["derived"].append(False)
            fs = H["nsamp"][i] / H["dur"]
            continue
        # referential fallback: "FP1-<ref>" and "F7-<ref>" with the same ref
        ia = [k for k, l in enumerate(up) if l.split("-")[0] == a and "-" in l]
        ib = [k for k, l in enumerate(up) if l.split("-")[0] == b and "-" in l]
        pair = next(((i, j) for i in ia for j in ib if up[i].split("-", 1)[1] == up[j].split("-", 1)[1]), None)
        if pair is None:
            meta["missing"].append(want); continue
        i, j = pair
        # convert both to physical units, subtract, re-quantise on channel i's scale
        g = lambda k: (H["pmax"][k] - H["pmin"][k]) / (H["dmax"][k] - H["dmin"][k])
        phys = lambda k: (chan(k).astype(np.float64) - H["dmin"][k]) * g(k) + H["pmin"][k]
        d = phys(i) - phys(j)
        q = np.clip(np.round((d - H["pmin"][i]) / g(i) + H["dmin"][i]), -32768, 32767).astype(np.int16)
        cols.append(q)
        meta["labels"].append(want); meta["dim"].append(H["dim"][i])
        meta["phys_min"].append(H["pmin"][i]); meta["phys_max"].append(H["pmax"][i])
        meta["dig_min"].append(H["dmin"][i]); meta["dig_max"].append(H["dmax"][i])
        meta["derived"].append(f"{H['labels'][i]} - {H['labels'][j]}")
        fs = H["nsamp"][i] / H["dur"]
    # Device montage FP1 − FP2, derived as a signed sum of a
    # chain of bipolar channels (exact only if all channels share one reference) (e.g. FP1-F7, F7-T7, T7-FT9, FT9-FT10, FT10-T8, F8-T8, FP2-F8)
    chain = _bipolar_path(up, "FP1", "FP2")
    if chain:
        g = lambda k: (H["pmax"][k] - H["pmin"][k]) / (H["dmax"][k] - H["dmin"][k])
        phys = lambda k: (chan(k).astype(np.float64) - H["dmin"][k]) * g(k) + H["pmin"][k]
        n0 = min(len(chan(k)) for k, _ in chain)
        d = sum(sgn * phys(k)[:n0] for k, sgn in chain)
        # store at 0.2 µV/LSB (±6553.4 µV) — finer than CHB-MIT's native resolution
        q = np.clip(np.round(d / 0.2), -32767, 32767).astype(np.int16)
        meta["fp1fp2_clip_frac"] = float(np.mean(np.abs(d / 0.2) > 32767))
        cols.append(q)
        meta["labels"].append("FP1-FP2"); meta["dim"].append("uV")
        meta["phys_min"].append(-6553.4); meta["phys_max"].append(6553.4)
        meta["dig_min"].append(-32767); meta["dig_max"].append(32767)
        meta["derived"].append(" + ".join(("" if s > 0 else "−") + H["labels"][k] for k, s in chain))
        fs = H["nsamp"][chain[0][0]] / H["dur"]
    else:
        meta["missing"].append("FP1-FP2")
    if not cols:
        return dict(name=name, error="no usable frontal channels", labels=H["labels"])
    n = min(len(c) for c in cols)
    arr = np.stack([c[:n] for c in cols], 1)
    meta.update(fs=fs, n=int(n))
    arr.astype("<i2").tofile(out_dir / f"{name}.ch.bin")
    (out_dir / f"{name}.ch.json").write_text(json.dumps(meta))
    return dict(name=name, n=int(n), fs=fs, labels=meta["labels"], derived=meta["derived"])


def select_files(summaries: dict) -> list:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from chbmit import parse_summary
    files = []
    for case in CASES:
        p = summaries[case]
        table = parse_summary(p)
        sz = [f for f, s in table.items() if s]
        free = [f for f, s in table.items() if not s]
        extra = free[:2] if case == "chb01" else free[:1]
        files += [f"{case}/{f}" for f in sz + extra]
    return files


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--local", default=None, help="folder holding chbXX/ EDFs (e.g. an attached Kaggle dataset)")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--all", action="store_true", help="every recording (≈42 GB download)")
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)

    local = None
    if a.local:
        hits = list(Path(a.local).rglob("chb01-summary.txt"))
        local = hits[0].parent.parent if hits else None
        print("local copy:", local)

    summaries = {}
    for c in CASES:
        dst = out / f"{c}-summary.txt"
        if not dst.exists():
            src = (local / c / f"{c}-summary.txt") if local else None
            dst.write_bytes(src.read_bytes() if src and src.exists() else _get(S3 + f"{c}/{c}-summary.txt"))
        summaries[c] = dst

    if a.all:
        from chbmit import parse_summary
        files = [f"{c}/{f}" for c in CASES for f in parse_summary(summaries[c])]
    else:
        files = select_files(summaries)
    todo = [f for f in files if not (out / (Path(f).stem + ".ch.json")).exists()]
    print(f"{len(files)} recordings selected, {len(todo)} to fetch", flush=True)

    def job(f):
        name = Path(f).stem
        lp = (local / f) if local else None
        if lp is not None and lp.exists():
            buf = lp.read_bytes()
        else:
            buf = _get(S3 + urllib.parse.quote(f))
        return extract(buf, "chbmit/1.0.0/" + f, out, name)

    log = []
    t0 = time.time()
    with ThreadPoolExecutor(a.workers) as ex:
        futs = {ex.submit(job, f): f for f in todo}
        for i, fu in enumerate(as_completed(futs), 1):
            f = futs[fu]
            try:
                r = fu.result()
            except Exception as e:                       # noqa: BLE001
                r = dict(name=f, error=repr(e))
            log.append(r)
            if i % 10 == 0 or "error" in r:
                print(f"[{i}/{len(todo)}] {f} {r.get('error', '')}  ({time.time()-t0:.0f}s)", flush=True)
    with open(out / "fetch_log.jsonl", "a") as fh:
        for r in log:
            fh.write(json.dumps(r) + "\n")
    errs = [r for r in log if "error" in r]
    print(f"done: {len(log) - len(errs)} ok, {len(errs)} errors")
    for r in errs:
        print("  ", r)


if __name__ == "__main__":
    main()
