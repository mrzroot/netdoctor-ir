# Pending workflow

`ci.yml` is the project's GitHub Actions CI (ruff, mypy, catalog validation, pytest on
Python 3.10–3.13, build + wheel smoke test).

It lives here temporarily because the token used for the initial push did not have the
`workflow` scope, which GitHub requires for creating files under `.github/workflows/`.
To enable it:

```bash
gh auth refresh -h github.com -s workflow
git mv .github/pending-workflows/ci.yml .github/workflows/ci.yml
git commit -m "ci: enable GitHub Actions" && git push
```
