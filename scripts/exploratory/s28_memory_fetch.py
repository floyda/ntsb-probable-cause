"""Draw the memory sample's three batches and fetch batch 1's dockets, with a disk guard (spec §4.1).

Status
    One-shot, complete (S2.8 design, 2026-09-28/29). Exploratory measurements behind
    docs/specs/2026-09-29-s28-coding-lookup-design.md, kept so its ad-hoc figures can be
    re-derived. Nothing here is a result and nothing imports it: S2.8's committed scripts
    re-derive every figure the stage relies on.

Development cases only. The statistics pool is every development C/F/L case outside dev-400
and dev-seal-400 (decision 0094); dev-seal-400 is read only as a list of ids to exclude. The
run folders named on the command line are dev-400 arm B runs. Codes and counts only are
printed; no case is named.

Usage (from the repository root, NTSB_DATA_DIR pointed at the main checkout's data/):
    uv run python scripts/exploratory/s28_memory_fetch.py <scratch folder for the drawn ids>
"""

import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, ".")
from ntsb_probable_cause.docket.client import DocketClient
from ntsb_probable_cause.docket.manifest import read_docket
from ntsb_probable_cause.errors import DocketError
from ntsb_probable_cause.splits import Split
from ntsb_probable_cause.scoring import samples
from ntsb_probable_cause.settings import Settings

OUT = Path(sys.argv[1])
SEEDS = (20260928, 20260929, 20260930)
MIN_FREE = 15 * 1024**3


def log(msg: str) -> None:
    print(time.strftime("%H:%M:%S"), msg, flush=True)


settings = Settings()
processed = settings.data_dir / "processed"
batches_file = OUT / "memory_batches.json"
if batches_file.exists():
    batches = json.loads(batches_file.read_text())
else:
    excluded = set(samples.sample_ids("dev-400")) | set(samples.sample_ids("dev-seal-400"))
    batches = []
    for seed in SEEDS:
        drawn = samples.draw(processed, Split.DEV, per_slice=200, seed=seed, exclude=frozenset(excluded))
        ids = [n for n, _ in drawn]
        assert all(int(str(d)[:4]) <= 2019 for _, d in drawn), 'non-development case'
        excluded |= set(ids)
        batches.append(ids)
        log(f"drew {len(ids)} with seed {seed}")
    batches_file.write_text(json.dumps({"seeds": SEEDS, "batches": batches}, indent=1))
    batches = json.loads(batches_file.read_text())
ids = batches["batches"][0]
sealed = set(samples.sample_ids("dev-seal-400")) | set(samples.sample_ids("dev-400"))
assert not set(ids) & sealed, "a sample case was drawn"
raws = samples.load_cases(processed, ids)
log(f"batch 1: {len(raws)} cases; docket cache {settings.docket_dir}")
done = failed = 0
with DocketClient(settings.docket_dir, seconds_per_request=settings.docket_seconds_per_request) as client:
    for position, raw in enumerate(raws, start=1):
        free = shutil.disk_usage(settings.docket_dir).free
        if free < MIN_FREE:
            log(f"STOPPED by the disk guard before case {position}: {free / 1024**3:.1f} GB free")
            break
        mkey = raw.get("mKey")
        if not isinstance(mkey, int):
            log(f"{position}/{len(raws)}: no mKey")
            failed += 1
            continue
        try:
            docket = read_docket(client, mkey)
        except DocketError as error:
            log(f"{position}/{len(raws)}: listing failed ({type(error).__name__})")
            failed += 1
            continue
        done += 1
        log(f"{position}/{len(raws)}: {len(docket.documents)} documents; {free / 1024**3:.1f} GB free")
log(f"FINISHED: {done} fetched, {failed} failed; {shutil.disk_usage(settings.docket_dir).free / 1024**3:.1f} GB free")
