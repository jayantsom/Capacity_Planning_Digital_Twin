# Documentation

This app reads the repository Markdown files at request time.

## Ownership

- `config.yaml` owns the navigation order.
- Every page slug is unique.
- Every Markdown path has one navigation owner.
- The browser renders text with safe DOM APIs.
- Raw HTML in Markdown is not executed.

## Test

```powershell
# Run only the Documentation app tests.
uv run pytest documentation/tests -q
```
