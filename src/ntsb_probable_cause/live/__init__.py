"""The live shadow: code each closed case once, through a queue, and record it (S3.3).

This package holds the queue, the fetching, the morning and the closure records. It works on the
open split only (decision 0024): nothing a live case produces reaches a committed file, a
development command or the model's fixed texts (decision 0160).
"""
