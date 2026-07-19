# llmcost

Estimate and compare LLM API costs across providers, fully offline.

`llmcost` answers "what does this workload cost on each model?" instantly:
give it token counts and it prints a ranked cost table across OpenAI,
Anthropic, Google, xAI, and DeepSeek models, or projects daily traffic to
monthly spend for one model. It runs entirely from an embedded, versioned
pricing snapshot -- no network access, no API keys, no dependencies beyond
the Python standard library.

## Accuracy disclaimer

The embedded pricing table is a snapshot **as of 2026-07-19**. Provider
prices change, introductory rates expire, and models get renamed or retired.
The numbers here are for quick comparison only -- the authoritative prices
always live with the providers:

| Provider  | Source                                                    |
| --------- | --------------------------------------------------------- |
| anthropic | https://platform.claude.com/docs/en/about-claude/pricing  |
| openai    | https://developers.openai.com/api/docs/pricing            |
| google    | https://ai.google.dev/gemini-api/docs/pricing             |
| xai       | https://docs.x.ai/docs/models                             |
| deepseek  | https://api-docs.deepseek.com/quick_start/pricing         |

Run `llmcost models` to see the snapshot date and every embedded price, and
use `--pricing your-table.json` to replace the table entirely with your own
numbers (schema below).

Known snapshot caveats, recorded in each entry's `notes` field:

- `claude-sonnet-5` uses introductory pricing (2/10 per MTok) through
  2026-08-31; standard pricing (3/15) applies from 2026-09-01.
- `gemini-3.1-pro-preview`, `grok-4.5`, and `grok-4.3` are tiered by prompt
  size; the embedded prices are the under-200k-token tier.
- Google multimodal models bill audio input at a higher rate; the embedded
  prices are the text/image/video rate.
- OpenAI batch pricing is roughly a 50% discount but exact per-model batch
  prices are not embedded, so `--batch` falls back to standard rates for
  OpenAI models.

## Install

```bash
# as a tool (recommended)
uv tool install llmcost
# or
pipx install llmcost

# from source
git clone https://github.com/printemps-tokyo/llmcost
cd llmcost
uv tool install .
# or just run it without installing:
PYTHONPATH=src python3 -m llmcost --help
```

Requires Python 3.11+. No runtime dependencies.

## Quickstart

Compare a workload across every model:

```console
$ llmcost --in 500k --out 120k
Cost per request for 500,000 in / 120,000 out tokens (USD, prices as of 2026-07-19)
MODEL                   PROVIDER   INPUT    OUTPUT   TOTAL
deepseek-v4-flash       deepseek   $0.0700  $0.0336  $0.1036
gpt-5.4-nano            openai     $0.1000  $0.1500  $0.2500
gemini-3.1-flash-lite   google     $0.1250  $0.1800  $0.3050
deepseek-v4-pro         deepseek   $0.2175  $0.1044  $0.3219
gemini-2.5-flash        google     $0.1500  $0.3000  $0.4500
gpt-5.4-mini            openai     $0.3750  $0.5400  $0.9150
grok-4.3                xai        $0.6250  $0.3000  $0.9250
claude-haiku-4-5        anthropic  $0.5000  $0.6000  $1.1000
gpt-5.6-luna            openai     $0.5000  $0.7200  $1.2200
grok-4.5                xai        $1.0000  $0.7200  $1.7200
gemini-3.5-flash        google     $0.7500  $1.0800  $1.8300
claude-sonnet-5         anthropic  $1.0000  $1.2000  $2.2000
gemini-3.1-pro-preview  google     $1.0000  $1.4400  $2.4400
gpt-5.6-terra           openai     $1.2500  $1.8000  $3.0500
claude-sonnet-4-6       anthropic  $1.5000  $1.8000  $3.3000
claude-opus-4-8         anthropic  $2.5000  $3.0000  $5.5000
gpt-5.6-sol             openai     $2.5000  $3.6000  $6.1000
claude-fable-5          anthropic  $5.0000  $6.0000  $11.0000
```

Project daily traffic to monthly spend for one model:

```console
$ llmcost --model claude-sonnet-5 --in 2m --out 500k --per day --month
Cost per month for 2,000,000 in / 500,000 out tokens (USD, prices as of 2026-07-19)
MODEL            PROVIDER   INPUT    OUTPUT   TOTAL
claude-sonnet-5  anthropic  $120.00  $150.00  $270.00
```

List the embedded pricing table:

```console
$ llmcost models
Pricing snapshot as of 2026-07-19 (USD per 1M tokens)
MODEL                   PROVIDER   INPUT  OUTPUT  CACHED-IN  BATCH-IN  BATCH-OUT
claude-fable-5          anthropic  10     50      1          5         25
claude-opus-4-8         anthropic  5      25      0.50       2.50      12.50
claude-sonnet-5         anthropic  2      10      0.20       1         5
...
```

## Token amounts

`--in`, `--out`, and `--cached` accept plain integers and `k` / `m`
suffixes (case-insensitive): `500000`, `500k`, `2m`, `1.5m`, `0.25m`.
Commas and underscores are allowed as digit separators. Negative amounts
and values that do not resolve to a whole number of tokens are rejected.

## Flags

| Flag                    | Meaning                                                                       |
| ----------------------- | ----------------------------------------------------------------------------- |
| `--in`, `--input-tokens`  | Input (prompt) tokens per request                                           |
| `--out`, `--output-tokens`| Output (completion) tokens per request                                      |
| `--cached N`            | Portion of input tokens served from the provider cache, billed at the cached-input rate where the model has one |
| `--model NAME`, `-m`    | Model to include (repeatable). Exact match wins, then unique prefix, then unique substring; ambiguous queries fail listing the candidates. Default: all models |
| `--provider NAME`       | Only models from this provider (`anthropic`, `openai`, `google`, `xai`, `deepseek`) |
| `--batch`               | Apply batch API pricing where the model has it (rows are marked `(batch)`; models without batch prices fall back to standard rates) |
| `--per request\|day\|month` | The period the token amounts describe (default: `request`)                |
| `--requests N`          | Requests per period to scale by (default: 1)                                  |
| `--month`               | Project a `--per day` workload to a 30-day month                              |
| `--json` / `--csv`      | Machine-readable output instead of the table                                  |
| `--sort cost\|name`     | Sort by total cost ascending (default) or by model name                       |
| `--top N`               | Only show the first N rows after sorting                                      |
| `--pricing FILE`        | Replace the embedded pricing table with your own JSON file                    |
| `models`                | Subcommand: list the pricing table with its as-of date (`--provider`, `--json`, `--pricing` supported) |

Notes on semantics:

- All money math uses `decimal.Decimal`; there is no float rounding anywhere
  in the cost path. Table output rounds to 4 decimals under $100 and 2
  decimals from $100 up; JSON and CSV carry the exact decimal strings.
- With `--batch`, all input tokens are billed at the batch input rate;
  cached-input pricing is not applied, because providers do not publish a
  combined batch+cached rate.
- `--month` requires `--per day` (multiplies by 30) or `--per month`
  (labeling only).

## Pricing override schema

`--pricing FILE` accepts a JSON object with the same schema as the embedded
table. Prices are strings (or integers) in USD per 1M tokens -- floats are
rejected so values stay exact through `Decimal`:

```json
{
  "as_of": "2026-07-19",
  "currency": "USD",
  "sources": { "myprovider": "https://example.com/pricing" },
  "models": [
    {
      "provider": "myprovider",
      "model": "my-model",
      "input": "1.25",
      "output": "5",
      "cached_input": "0.125",
      "batch_input": "0.625",
      "batch_output": "2.50",
      "notes": "optional free text"
    }
  ]
}
```

Rules: `as_of` must be an ISO date; `models` must be non-empty; every entry
needs a non-empty `provider` and `model` plus positive `input` and `output`
prices; `cached_input`, `batch_input`, `batch_output`, and `notes` are
optional; duplicate provider/model pairs are rejected.

## JSON output schema

```json
{
  "as_of": "2026-07-19",
  "currency": "USD",
  "period": "request",
  "input_tokens": 500000,
  "output_tokens": 120000,
  "cached_tokens": 0,
  "requests": 1,
  "multiplier": 1,
  "batch": false,
  "results": [
    {
      "model": "claude-sonnet-5",
      "provider": "anthropic",
      "input_cost": "1",
      "cached_cost": "0",
      "output_cost": "1.2",
      "total": "2.2",
      "batch_applied": false,
      "notes": "Introductory pricing through 2026-08-31; ..."
    }
  ]
}
```

Costs are decimal strings, not floats. `multiplier` is the total scale
factor applied (`requests`, times 30 when projecting a day to a month).

## CSV output schema

```csv
model,provider,input_cost,cached_cost,output_cost,total,batch_applied
deepseek-v4-flash,deepseek,0.07,0,0.0336,0.1036,false
```

## Development

Stdlib-only at runtime and for tests (unittest, no pytest):

```bash
uv run python -m unittest discover -s tests   # tests
uv build                                      # sdist + wheel
uvx --from ./dist/llmcost-*.whl llmcost --help  # install smoke test
python -m compileall src                      # syntax check
```

## Scope

`llmcost` does cost math only. It does not count tokens -- pair it with your
provider's tokenizer or token-counting endpoint to measure a workload, then
feed the numbers in.

## License

MIT
