# Releasing saicode

saicode is published to PyPI by the `Release` workflow
(`.github/workflows/release.yml`) using **Trusted Publishing**: PyPI trusts this
repository's workflow through OpenID Connect, so no API token or password is
stored anywhere.

| Trigger | What happens |
| ------- | ------------ |
| **Actions → Release → Run workflow** | CI, then publish to **TestPyPI** (rehearsal) |
| **Publishing a GitHub Release** | CI, tag check, publish to **PyPI**, attach the files to the release |

Every release runs the full CI first and publishes exactly the files CI built and
checked. Nothing is rebuilt between the checks and the upload.

---

## One-time setup

Do this once, before the first release.

### 1. Accounts

1. Create accounts on [pypi.org](https://pypi.org/account/register/) and
   [test.pypi.org](https://test.pypi.org/account/register/). They are separate sites
   with separate accounts.
2. Turn on two-factor authentication on both (PyPI requires it for uploads).

### 2. Pending publishers

A pending publisher reserves the project name for this workflow and creates the
project on its first upload.

On **PyPI**: *Your account → Publishing → Add a new pending publisher → GitHub*

| Field | Value |
| ----- | ----- |
| PyPI Project Name | `saicode` |
| Owner | `the-schoolofai` |
| Repository name | `saicode` |
| Workflow name | `release.yml` |
| Environment name | `pypi` |

On **TestPyPI**: the same form with the same values, except
**Environment name** = `testpypi`.

> Set up the pending publisher soon. Until the first upload, anyone can still
> register the name `saicode`.

### 3. GitHub environments

In the repository: *Settings → Environments → New environment*

- **`pypi`**
  - *Required reviewers*: add the maintainers, so every PyPI release waits for a
    manual approval.
  - *Deployment branches and tags*: **Selected branches and tags**, add the tag rule
    `v*`.
- **`testpypi`**: no protection rules are needed.

> Required reviewers on a **private** repository need a paid GitHub plan
> (Team or Enterprise). On the Free plan, set the tag rule anyway and treat
> publishing the GitHub Release as the approval step.

---

## Release checklist

### 1. Prepare

1. Choose the version ([Semantic Versioning](https://semver.org); while `0.x`, a
   minor release may break compatibility).
2. Set `__version__` in `src/saicode/__init__.py`. This is the only place the
   version is written.
3. In `CHANGELOG.md`, move the **Unreleased** entries into a new section
   `## [X.Y.Z] - YYYY-MM-DD` and update the compare links at the bottom.
4. Commit (`Release X.Y.Z`), push to `main` and wait for CI to pass.

### 2. Rehearse on TestPyPI

Recommended for every release, required for the first one.

1. *Actions → Release → Run workflow* on `main`.
2. Install from TestPyPI in a clean environment and try it:

   ```bash
   uv tool install --index-url https://test.pypi.org/simple/ \
     --extra-index-url https://pypi.org/simple/ \
     --index-strategy unsafe-best-match saicode==X.Y.Z
   saicode --version
   saicode config
   ```

3. Check the project page on test.pypi.org: README rendering, links, metadata.

A version can be uploaded to TestPyPI only once. To rehearse again, use a
pre-release version such as `X.Y.Zrc1`, then `X.Y.Zrc2`.

### 3. Publish

1. *Releases → Draft a new release*.
2. *Choose a tag*: type `vX.Y.Z` and select *Create new tag on publish*, target `main`.
3. Title `saicode X.Y.Z`; paste the changelog section as the description.
   Tick *Set as a pre-release* for `rc`, `a` or `b` versions.
4. *Publish release*. The workflow starts, runs CI and checks the tag against the
   built version, then waits for approval of the `pypi` environment (if
   configured). Approve it in the workflow run.

### 4. Verify

```bash
uv tool install saicode==X.Y.Z    # on a clean machine or after `uv tool uninstall saicode`
saicode --version
```

- `https://pypi.org/project/saicode/` shows the new version and its README.
- The GitHub Release has the `.whl` and `.tar.gz` files attached.

---

## When something goes wrong

- **The tag check failed.** The tag and `__version__` differ. Delete the GitHub
  Release *and* the tag, fix the version on `main`, and publish the release again.
  Nothing was uploaded.
- **CI failed during the release.** Nothing was uploaded. Fix the problem on `main`,
  delete the release and tag, and release again.
- **A broken version reached PyPI.** A version number can never be uploaded twice,
  even after deletion. Do not delete it: **yank** it (*PyPI → Manage project →
  Releases → Options → Yank*) with a short reason, then release a fixed patch
  version. A yanked version stays installable only when pinned exactly, so
  nobody's existing setup breaks.
- **"invalid-publisher" from PyPI.** The pending publisher values do not match the
  run. Check the owner, repository, workflow file name (`release.yml`) and
  environment name (`pypi` or `testpypi`).
