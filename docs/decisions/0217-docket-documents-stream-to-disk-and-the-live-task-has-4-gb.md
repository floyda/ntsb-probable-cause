# 0217 — Docket documents stream to disk, and the live task has 4 GB

From an investigation of the live nights, 2026-11-01. Amends nothing; it changes how
[0176](0176-the-docket-is-frozen-by-its-hashes.md)'s documents are fetched and read, not what is
kept or hashed.

## Context

1. **No live night finished from 2026-10-22 to 2026-11-01.** Each one wrote its
   `nights/<date>/started` marker and then stopped. It wrote no run folder, no manifest, no log
   lines and no alert. The missed-night alarm (decision 0177) was in ALARM from 2026-10-23. In
   that time 39 closed cases joined the queue.
2. **AWS gave the reason when the task was run once with `--dry-run`:** exit code 137,
   "OutOfMemoryError: container killed due to memory usage", 59 seconds after it started. The task
   had 1 GB (1024 MiB). Python's output is buffered when it is not written to a terminal, and a
   kill throws it away. That is why the log streams were empty.
3. **The cause is one document.** The first queued case's docket holds a 30-page scan of
   1,098,930,589 bytes (about 1.1 GB) with no text layer. The queue keeps its order, so every
   night met the same document first.
4. **The client held each document whole in memory twice.** `DocketClient._get` returned
   `response.content`, the full body, and `extract_pdf` then gave pypdf the bytes. pypdf builds
   its objects from whatever it is given. Handed a path, it reads the whole file into memory
   first; only an open file handle is read as it goes.
5. **Measured by hand on this Mac, 2026-11-01**, on that docket's 10 PDF documents. Peak memory
   of the process (resident set size):

   | Step | Before | After |
   |---|---|---|
   | Download, all 10 documents | 1.1 GB or more (the body is held whole) | 77 MB (streamed to disk) |
   | Read the 1.1 GB scan | 2,278 MB (from bytes) | 1,155 MB (from an open file) |
   | Read the 76 MB document | 265 MB | 187 MB |
   | Read each of the other 8 | about 115 MB | about 115 MB |
   | The night's docket fetch for that case | 3,626 MB (one dry run) | 1,221 MB (`prefetch_docket`, this change) |

   Every one of the 10 documents gave the same character count and the same SHA-256 of its
   extracted text both ways. **These figures come from probes run by hand, not a committed
   script**, because the document belongs to an open case: decision 0024 keeps an open case's
   identifiers and documents out of git and out of development work. They are numbers only, and
   the case is not named here.

## Decision

1. **A caching docket client streams each document to disk.** `DocketClient.document_file`
   writes the body 1 MiB at a time to `<index>.bin.partial`, hashing as it writes, renames it into
   place, then records the hash in `fetch.json`, as before. A cached file's hash is checked a
   piece at a time. A transport error while the body arrives is retried like one before it.
   `document()` still returns bytes, read back from that file, so every other caller is
   unchanged.
2. **`extract_pdf` accepts a file**, read through an open handle, and gives the same result as
   for the file's bytes.
3. **`read_docket` reads a file whenever the client caches.** It still reads bytes for a
   read-and-discard client, which writes nothing (decision 0040), and for evidence v2, whose
   transcriptions are keyed by the document's bytes. The live night, `ntsb-eval run` and the loop
   all cache, so all of them read from files.
4. **The live task has 4 GB** (4096 MiB at 0.5 vCPU, the most Fargate allows at that CPU), and
   sets `PYTHONUNBUFFERED=1` so a night killed mid-way still leaves its lines in the log.

## Why

1. **Disk alone does not fit 1 GB.** Reading the scan from a file still peaks at 1,155 MB, because
   pypdf reads each page's content stream in full to look for text. Raising memory alone would
   need about 3.6 GB for this document and more for a larger one. Together, this document peaks
   near 1.2 GB against 4 GB, more than three times its size.
2. **Every document is still read.** A size limit would protect against any future file. But it
   would skip a large document that has text, and it would change what evidence the agent sees.
   Andy chose not to (2026-11-01).
3. **The evidence does not change.** The extracted text is the same, so the hashes in
   `dockets.json` (0185) and every earlier measurement are unaffected.
4. **The cost is small (judgement, not measured).** Fargate bills memory by the GB-hour, and the
   nights that finished took 35 minutes or less, so 3 GB more costs a few cents a night at most.
5. **The empty logs hid the cause for eleven days.** Unbuffered output costs nothing.

## What this rules out

- **A size limit on documents.** It is the stronger guarantee: no single file can stop a night.
  It was not chosen, because it changes the evidence. A document that needs more than about
  3.5 GB to read will kill the night again, and the queue will stall behind it as it did here.
  Only then is a limit worth its cost.
- **More memory alone, with no change in code.** At about 3.6 GB this document would sit at the
  edge of 4 GB.
- **A different PDF library**, such as `pypdfium2`, which may read text with less memory. Its text
  could differ from pypdf's, and every measured result rests on pypdf's.
- **Skipping a case whose docket fails to read.** A case stuck at the head of the queue is a
  fault to fix, not one to step around without anyone noticing.

## Status

Accepted.
