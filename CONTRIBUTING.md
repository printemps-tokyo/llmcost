# Contributing

Thanks for your interest in contributing to a printemps-tokyo project.

## Development

1. Fork / clone the repository
2. Create a branch: `git switch -c feat/your-change`
3. Make your change and verify locally:
   ```bash
   uv run python -m unittest discover -s tests
   uv build
   python -m compileall src
   ```
4. Commit and open a pull request

The project is intentionally stdlib-only: no runtime dependencies, and tests
use `unittest` rather than pytest. Please keep it that way.

## Pricing data changes

`src/llmcost/pricing.json` is an accuracy-critical snapshot. When updating it:

- Verify every price against the provider's official pricing page
- Update `as_of` to the verification date and keep `sources` current
- Prices are strings (never JSON floats) so they stay exact through `Decimal`
- Run the test suite; the schema tests will catch structural mistakes

## Commit messages

[Conventional Commits](https://www.conventionalcommits.org/) are preferred
(`feat:`, `fix:`, `docs:`, `chore:`, `refactor:`, `test:`).

## Pull requests

- Keep one PR focused on a single purpose
- CI (tests / build) must be green
- Update the README and tests when behavior changes

## Bug reports and requests

Please open an [issue](../../issues) using the templates.
