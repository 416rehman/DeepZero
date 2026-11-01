# loldrivers_filter

A `MapProcessor` that filters samples whose SHA-256 matches an entry in the
LOLDrivers database.

The database is fetched once and compared locally. Sample data is not uploaded.

## Where the database comes from

In order:

1. `db_path`, if set. Absolute as given, otherwise resolved against the working
   directory and then against the pipeline directory, the same way every other
   path-taking config in this project resolves.
2. `<working dir>/.cache/<stage name>/loldrivers.io.json`, if it exists and is
   younger than `cache_ttl_days`.
3. an HTTPS GET of `https://www.loldrivers.io/api/drivers.json`, with a
   `deepzero/<version>` user agent taken from the installed package and a 30
   second timeout. It is written to a temporary file and moved into place, so an
   interrupted download cannot leave a half-written cache behind.

All of this happens once, in `setup()`, before any sample is processed. Every
entry's `KnownVulnerableSamples[].SHA256` is read into a lowercased set; nothing
else in the database is looked at.

The sample's own hash is the first `sha256` found in its history, in the order
the stages recorded their output, so whichever earlier stage recorded one
supplies it. `pe_ingest` does. No stage is named in the lookup, which is what
lets this sit after any ingest that records a hash.

## When the database is missing, nothing is excluded

The run goes on. A database that could not be fetched is no reason to lose a
corpus, so every sample passes and each one records `loldrivers_checked: false`.
That flag is the whole point: without it, a run where the fetch failed is
indistinguishable from a run where nothing matched, and every known-vulnerable
driver in the corpus would be reported as new. A report that reads "not in
loldrivers" out of a sample whose `loldrivers_checked` is false is reading a
lookup that never happened.

The same false is recorded for a sample no upstream stage gave a `sha256`, for
the same reason: the comparison did not take place.

There is one case worth setting `db_path` for. When the cached copy is older than
`cache_ttl_days`, it is not used; a refresh is attempted, and if that download
fails the result is no database at all. The stale file is still on disk, untouched
and perfectly readable, and it is not read. So a machine that goes offline for
longer than the TTL silently stops filtering. Pointing `db_path` at that file, or
raising `cache_ttl_days`, is the way to keep filtering without network access.

A database that parses as JSON but is not a list of entries yields zero hashes
and behaves exactly like a missing one, with a log line saying it loaded 0.

## What it emits

Every key below lands in `history["<stage name>"].data` and is available to any
later stage's prompt, filter or ranking metric.

| Key | Meaning |
|---|---|
| `loldrivers_checked` | whether the database was actually consulted for this sample |

A sample that matched is filtered out of the run carrying
`loldrivers_checked: true` and the reason `already in loldrivers.io database`, so
the run's own state says why it went rather than leaving it merely absent.

## Config

| Field | Default | Meaning |
|---|---|---|
| `db_path` | none | a copy of the database to read instead of fetching one |
| `cache_ttl_days` | `7` | how old the cached copy may be before a refresh is attempted |

This processor declares a `Config` dataclass, so a key it does not accept is
reported as ignored rather than silently doing nothing.

`validate()` checks one thing: that a `db_path` which was set actually resolves
to a file. A path that resolves to nothing is a typo rather than a request to go
to the network, and saying so before the run beats quietly downloading a
different database than the one that was asked for. Everything else is deferred:
no network call is made at validation time, and a fetch that fails during the run
is a warning naming what went wrong, not an error.

## In a pipeline

Straight after the stage that records the hash, and before anything expensive:

```yaml
stages:
  - name: discover
    processor: pe_ingest/pe_ingest.py

  - name: loldrivers_filter
    processor: loldrivers_filter/loldrivers_filter.py

  # only what is left reaches ghidra
  - name: decompile
    processor: ghidra_decompile/ghidra_decompile.py
```

On a machine with no network, keep a copy beside the pipeline and name it:

```yaml
  - name: loldrivers_filter
    processor: loldrivers_filter/loldrivers_filter.py
    config:
      db_path: drivers.json
```
