---
layout: default
title: Built-in Processors
order: 1
---

## Built-in Processors

| Identifier | Type | Functionality |
| ---------- | ---- | ------------- |
| `file_discovery` | Ingest | Recursive filesystem traversal and cryptographic hashing. |
| `metadata_filter` | Map | Boolean constraint checking and field deduplication. |
| `hash_exclude` | Map | Cryptographic exclusions against inline lists or flat files. |
| `generic_llm` | Map | Jinja2 template rendering, LLM invocation, and response parsing. |
| `generic_command` | Map | Arbitrary shell execution with contextual variable substitution. |
| `top_k` | Reduce | Truncates sample set based on numeric scalar values. |
| `sort` | Reduce | Deterministic sample reordering without dataset reduction. |
