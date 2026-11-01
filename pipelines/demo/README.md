# Try DeepZero locally

This example demonstrates pipeline execution, metadata filtering, persisted state,
and HTML reports using two harmless text files. It does not perform vulnerability
analysis or call an LLM. After installing DeepZero's base dependencies, the demo
needs no network access, API keys, Ghidra, or driver corpus.

Run these commands from the repository root (PowerShell or a POSIX shell):

```sh
deepzero run pipelines/demo/samples -p pipelines/demo/pipeline.yaml
deepzero status -p pipelines/demo/pipeline.yaml
deepzero report -p pipelines/demo/pipeline.yaml --open
```

The `discover` stage finds two files and records their SHA-256 hashes and sizes.
The `keep_larger_files` stage keeps `hello.txt` and filters out `tiny.txt` because
it contains fewer than 32 bytes. A filtered file is an expected outcome, not an
error. The generated report shows the samples and their stage results; it does
not establish whether a file is safe or vulnerable.

Run the first command again to resume the saved run. DeepZero keeps state and
reports under `work/demo/<corpus-key>/`; the CLI prints the report location.

To explore the YAML configuration, change `min_size_bytes` and run with a new
work directory so previous results do not get reused:

```sh
deepzero run pipelines/demo/samples -p pipelines/demo/pipeline.yaml -w work/demo-experiment
```

For real analysis prerequisites and pipeline configuration, see the
[documentation](https://blog.ahmadz.ai/DeepZero/en/overview/quickstart.html).
