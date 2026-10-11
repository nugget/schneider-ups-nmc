# APC UPS NMC: Home Assistant custom integration, shipped through HACS.
#
# New here, or back after a long time? Run `just` to see every recipe, then:
#
#   just setup       install the toolchain and check git/gh are ready
#   just status      where the repo, releases and open PRs stand
#
# Production broke after a Home Assistant upgrade?
#
#   just ha-drift    compare our pins and test harness with the newest HA
#   just ha-upgrade  move the test harness to the newest HA, then `just ci`
#
# Changing code: branch from main, edit, `just fix`, `just ci`, open a PR.
# `main` only accepts signed commits through reviewed PRs, and `just ci` is the
# same gate GitHub Actions runs, so run it before every push.
#
# Shipping a release takes two steps, run from an up-to-date main, because
# main only accepts reviewed PRs:
#
#   just release-prepare 0.2.1   gate, bump the version, open the release PR
#   (get the PR reviewed and merged)
#   just release-publish 0.2.1   tag the release commit, create the GitHub Release
#
# Then replace the generated GitHub release notes with a written summary.
#
# AGENTS.md has the full conventions; README.md has the user-facing docs.

manifest := "custom_components/schneider_ups_nmc/manifest.json"

# List recipes.
[private]
default:
    @just --list --unsorted

# --- Getting started ---------------------------------------------------------

# Install the locked toolchain and check git and gh are ready to ship.
[group('start here')]
setup:
    #!/usr/bin/env bash
    set -euo pipefail
    for tool in uv gh git; do
      command -v "$tool" >/dev/null || { echo "missing: $tool" >&2; exit 1; }
    done
    uv sync --locked
    gh auth status >/dev/null 2>&1 \
      || echo "warning: gh is not signed in; run 'gh auth login' before releasing"
    [[ "$(git config --get commit.gpgsign || true)" == "true" ]] \
      || echo "warning: commit signing is off; main rejects unsigned commits"
    [[ "$(git config --get tag.gpgsign || true)" == "true" ]] \
      || echo "note: release tags are signed with 'git tag -s' regardless"
    echo "ready: Python $(uv run python -c 'import platform; print(platform.python_version())')," \
      "Home Assistant $(uv run python -c 'from importlib.metadata import version; print(version("homeassistant"))')"

# Show branch state, versions, the latest release and open PRs.
[group('start here')]
status:
    #!/usr/bin/env bash
    set -euo pipefail
    git fetch --quiet origin main --tags || echo "warning: could not fetch origin"
    branch="$(git branch --show-current)"
    echo "branch           $branch$( [[ -n "$(git status --porcelain)" ]] && echo ' (uncommitted changes)')"
    echo "manifest         $(uv run python scripts/release_metadata.py current) here," \
      "$(uv run python scripts/release_metadata.py current origin/main) on origin/main"
    echo "tested against   Home Assistant $(uv run python -c 'from importlib.metadata import version; print(version("homeassistant"))')," \
      "minimum $(uv run python -c 'import json; print(json.load(open("hacs.json")).get("homeassistant", "unset"))') in hacs.json"
    latest="$(gh release view --json tagName -q .tagName 2>/dev/null || git describe --tags --abbrev=0 origin/main 2>/dev/null || true)"
    echo "latest release   ${latest:-none}"
    if [[ -n "$latest" ]]; then
      echo
      echo "Unreleased on origin/main since $latest:"
      unreleased="$(git log --oneline --no-merges "$latest..origin/main")"
      echo "${unreleased:-(none)}" | sed 's/^/  /'
    fi
    echo
    echo "Open pull requests:"
    if prs="$(gh pr list --state open 2>/dev/null)"; then
      echo "${prs:-(none)}" | sed 's/^/  /'
    else
      echo "  (gh unavailable; run 'gh auth login')"
    fi

# --- Everyday development ----------------------------------------------------

# Format and auto-fix lint findings in place.
[group('develop')]
fix:
    uv run ruff format .
    uv run ruff check --fix .

# Plain unittest modules and Home Assistant pytest modules
# (tests/test_homeassistant_*.py) use separate runners; both must pass.
[doc('Run every test: unittest modules, then Home Assistant pytest modules.')]
[group('develop')]
test: test-unit test-ha

# Run Home Assistant pytest tests, e.g. `just test-ha -k syslog -x`.
[group('develop')]
test-ha *args:
    PYTHONDONTWRITEBYTECODE=1 uv run pytest -q {{ args }}

# Run plain unittest tests, e.g. `just test-unit tests.test_syslog`.
[group('develop')]
test-unit *args:
    PYTHONDONTWRITEBYTECODE=1 uv run python -m unittest {{ if args == "" { "discover -s tests" } else { args } }}

# Full local gate; GitHub Actions runs exactly this. Run before every push.
[group('develop')]
ci: lock-check format-check lint doclint typecheck spellcheck json yaml test

# --- Individual checks (all run by `just ci`) --------------------------------

# Check formatting without changing files.
[group('checks')]
format-check:
    uv run ruff format --check .

# Lint with ruff.
[group('checks')]
lint:
    uv run ruff check .

# Check docstrings match signatures.
[group('checks')]
doclint:
    uv run pydoclint custom_components tests scripts

# Type check with pyright.
[group('checks')]
typecheck:
    uv run pyright

# Catch typos in code and docs.
[group('checks')]
spellcheck:
    uv run codespell --ignore-words-list hass AGENTS.md README.md info.md custom_components tests scripts hacs.json justfile pyproject.toml .github/workflows

# Validate the JSON that Home Assistant and HACS load.
[group('checks')]
json:
    uv run python -m json.tool {{ manifest }} > /dev/null
    uv run python -m json.tool custom_components/schneider_ups_nmc/strings.json > /dev/null
    uv run python -m json.tool custom_components/schneider_ups_nmc/translations/en.json > /dev/null
    uv run python -m json.tool hacs.json > /dev/null

# Validate GitHub Actions workflows.
[group('checks')]
yaml:
    uv run yamllint .github/workflows

# Check uv.lock matches pyproject.toml.
[group('checks')]
lock-check:
    uv lock --check

# Format in place (`just fix` also applies lint fixes).
[group('checks')]
format:
    uv run ruff format .

# --- Dependencies and Home Assistant upgrades --------------------------------

# Exits non-zero if a requirement would stop the integration from loading.
[doc('Compare our requirements and test harness with the newest Home Assistant.')]
[group('dependencies')]
ha-drift:
    uv run python scripts/ha_drift.py

# HARNESS is a pytest-homeassistant-custom-component version, not a Home
# Assistant version; each harness release tracks one Home Assistant release.
[doc('Move the test harness to the newest Home Assistant (or HARNESS release).')]
[group('dependencies')]
ha-upgrade harness="latest":
    #!/usr/bin/env bash
    set -euo pipefail
    harness='{{ harness }}'
    if [[ "$harness" == latest ]]; then
      harness="$(uv run python -c 'import json, urllib.request; print(json.load(urllib.request.urlopen("https://pypi.org/pypi/pytest-homeassistant-custom-component/json", timeout=15))["info"]["version"])')"
    fi
    uv add --dev "pytest-homeassistant-custom-component==$harness"
    echo
    echo "Harness $harness runs Home Assistant" \
      "$(uv run python -c 'from importlib.metadata import version; print(version("homeassistant"))')."
    echo "Next: just ci, fix what the new core breaks, and decide whether"
    echo "hacs.json \"homeassistant\" (the minimum HACS will install on) must move too."

# Refresh uv.lock after editing dependencies in pyproject.toml.
[group('dependencies')]
lock:
    uv lock

# --- Releases ----------------------------------------------------------------

# Step 1 of 2: run the gate and open a PR bumping the version to VERSION.
[group('release')]
release-prepare version: _require-main
    #!/usr/bin/env bash
    set -euo pipefail
    version="$(uv run python scripts/release_metadata.py normalize '{{ version }}')"
    tag="v$version"
    branch="release/$tag"

    if [[ -n "$(git status --porcelain)" ]]; then
      echo "commit or stash your changes first; the release branch starts from origin/main" >&2
      exit 1
    fi
    if git rev-parse -q --verify "refs/tags/$tag" >/dev/null \
      || git ls-remote --exit-code --tags origin "refs/tags/$tag" >/dev/null 2>&1; then
      echo "$tag is already tagged; pick a new version" >&2
      exit 1
    fi
    if [[ "$(uv run python scripts/release_metadata.py current origin/main)" == "$version" ]]; then
      echo "origin/main is already at $version; publish it with: just release-publish $version"
      exit 0
    fi
    open_pr="$(gh pr list --head "$branch" --state open --json url -q '.[0].url')"
    if [[ -n "$open_pr" ]]; then
      echo "the $tag release PR is already open: $open_pr"
      echo "after it merges, run: just release-publish $version"
      exit 0
    fi
    if git rev-parse -q --verify "refs/heads/$branch" >/dev/null; then
      echo "local branch $branch already exists; delete it with: git branch -D $branch" >&2
      exit 1
    fi

    git switch --quiet -c "$branch" origin/main

    # If the gate, commit or PR step fails, put the operator back where they
    # started so fix-and-rerun works without manual git cleanup. Only delete
    # the remote branch if this run pushed it.
    pushed=0
    rollback() {
      echo "release-prepare failed; rolling back to your previous branch" >&2
      git reset --quiet --hard
      git switch --quiet -
      git branch --quiet -D "$branch"
      if [[ "$pushed" == 1 ]]; then
        git push --quiet origin --delete "$branch" || true
      fi
    }
    trap rollback ERR

    uv run python scripts/release_metadata.py set "$version"
    uv lock
    just ci
    git add {{ manifest }} pyproject.toml uv.lock
    # main rejects unsigned commits; sign explicitly so a missing signing
    # setup fails here and rolls back instead of producing an unmergeable PR.
    git commit --quiet -S -m "chore: release $tag"
    git push --quiet -u origin "$branch"
    pushed=1
    gh pr create --base main --head "$branch" --title "chore: release $tag" \
      --body "Bumps the release version to \`$version\` in \`manifest.json\`, \`pyproject.toml\` and \`uv.lock\`.

    After this merges, run \`just release-publish $version\` to tag the release commit and create the GitHub Release."
    trap - ERR
    git switch --quiet -
    echo
    echo "Next: get the PR reviewed and merged, then run: just release-publish $version"

# Step 2 of 2, after the release PR merges: tag it and create the GitHub Release.
[group('release')]
release-publish version: _require-main
    #!/usr/bin/env bash
    set -euo pipefail
    version="$(uv run python scripts/release_metadata.py normalize '{{ version }}')"
    tag="v$version"
    # Pre-releases (0.3.0-rc.1) must not become the release HACS installs.
    kind="--latest"
    if [[ "$version" == *-* ]]; then
      kind="--prerelease"
    fi

    git fetch --quiet origin main --tags
    on_main="$(uv run python scripts/release_metadata.py current origin/main)"
    if [[ "$on_main" != "$version" ]]; then
      echo "origin/main is at $on_main, not $version. Run 'just release-prepare $version' and merge its PR first." >&2
      exit 1
    fi
    if git rev-parse -q --verify "refs/tags/$tag" >/dev/null \
      || git ls-remote --exit-code --tags origin "refs/tags/$tag" >/dev/null 2>&1; then
      if url="$(gh release view "$tag" --json url -q .url 2>/dev/null)"; then
        echo "$tag is already released: $url" >&2
      else
        echo "$tag is tagged but has no GitHub Release; create it with:" >&2
        echo "  gh release create $tag --verify-tag --title $tag --generate-notes $kind" >&2
      fi
      exit 1
    fi

    # Tag the commit that set this version, not the tip of main, so later
    # merges never sneak into the release. `git log -S` also lists the commit
    # that later removed the string, so confirm the manifest really says it.
    commit=""
    for candidate in $(git log --format=%H -S"\"version\": \"$version\"" origin/main -- {{ manifest }}); do
      if [[ "$(uv run python scripts/release_metadata.py current "$candidate")" == "$version" ]]; then
        commit="$candidate"
        break
      fi
    done
    if [[ -z "$commit" ]]; then
      echo "could not find the commit on origin/main that set version $version" >&2
      exit 1
    fi

    # Right after a merge, CI may not have registered any runs yet; no runs
    # is not the same as green, so wait for at least one.
    checks="$(gh api "repos/{owner}/{repo}/commits/$commit/check-runs" \
      --jq '"\(.total_count)\t" + ([.check_runs[] | select(.conclusion != "success" and .conclusion != "skipped" and .conclusion != "neutral") | .name] | join(", "))')"
    total="${checks%%$'\t'*}"
    unfinished="${checks#*$'\t'}"
    if [[ "$total" == 0 ]]; then
      echo "no checks have reported on $(git rev-parse --short "$commit") yet; wait for CI and rerun" >&2
      exit 1
    fi
    if [[ -n "$unfinished" ]]; then
      echo "checks on $(git rev-parse --short "$commit") are not green yet: $unfinished" >&2
      exit 1
    fi

    git tag -s "$tag" "$commit" -m "$tag"
    if ! git push --quiet origin "refs/tags/$tag"; then
      git tag -d "$tag" >/dev/null
      echo "pushing $tag failed; removed the local tag so a rerun starts clean" >&2
      exit 1
    fi
    gh release create "$tag" --verify-tag --title "$tag" --generate-notes "$kind"
    echo
    echo "Next: replace the generated notes with a written summary (see AGENTS.md,"
    echo "\"HACS & Release Engineering\"): gh release edit $tag --notes-file notes.md"

# Releases ship what is merged on main, and the recipes call scripts/ from the
# checkout, so both steps start from a main that matches origin/main exactly.
[private]
_require-main:
    #!/usr/bin/env bash
    set -euo pipefail
    git fetch --quiet origin main --tags
    branch="$(git branch --show-current)"
    if [[ "$branch" != main ]]; then
      echo "Releases run from main, but you're on ${branch:-a detached HEAD}. Run:" >&2
      echo "  git switch main && git pull" >&2
      echo "then rerun this command." >&2
      exit 1
    fi
    read -r ahead behind < <(git rev-list --left-right --count HEAD...origin/main)
    if [[ "$ahead" != 0 ]]; then
      echo "Your main has $ahead commit(s) that aren't on origin/main, and releases" >&2
      echo "only ship merged work. Move them to a branch and open a PR, or drop them:" >&2
      echo "  git reset --keep origin/main" >&2
      exit 1
    fi
    if [[ "$behind" != 0 ]]; then
      echo "Your main is $behind commit(s) behind origin/main. Run:" >&2
      echo "  git pull" >&2
      echo "then rerun this command." >&2
      exit 1
    fi
