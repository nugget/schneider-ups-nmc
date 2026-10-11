# AGENTS.md

APC UPS NMC is a Home Assistant custom integration for APC by Schneider Electric
UPS Network Management Card devices. The first support target is NMC3 hardware,
but the repository and Home Assistant domain intentionally leave room for other
Schneider Electric/APC NMC generations. The release artifact is a
HACS-installable repository containing one integration under
`custom_components/schneider_ups_nmc/`.

This repo should feel like a Home Assistant Core integration even while it is
distributed through HACS. Aim for Home Assistant's Integration Quality Scale,
with platinum as the north star: excellent user experience, strict code
quality, robust diagnostics, thoughtful documentation, and efficient local
communication.

Everything below is what you need to contribute code.

## Build & Test

All workflows go through [just](https://just.systems/). Run `just` for the
grouped recipe list; the top of the `justfile` is an orientation guide for
operators returning after a long gap. Prefer the project recipes over invoking
underlying tools directly; the justfile keeps local validation aligned with
GitHub Actions.

```bash
just setup         # Install the locked toolchain; check gh auth and signing
just status        # Branch state, versions, latest release, open PRs
just fix           # Ruff format and auto-fix lint findings
just test          # Every test (unittest modules, then HA pytest modules)
just test-ha -k x  # HA pytest tests with pytest arguments
just test-unit     # Plain unittest tests (pass a module to narrow)
just ci            # Full local gate, identical to GitHub Actions
just ha-drift      # Compare pins and harness with the newest Home Assistant
just ha-upgrade    # Move the test harness to the newest Home Assistant
just release-prepare 0.2.1  # Gate, bump the version, open the release PR
just release-publish 0.2.1  # After that PR merges: tag it, create the GitHub Release
```

`just ci` must pass locally before every push. Do not rely on GitHub Actions to
catch what could have been caught locally. The individual checks it runs
(`format-check`, `lint`, `doclint`, `typecheck`, `spellcheck`, `json`, `yaml`,
`lock-check`) are also recipes.

Release and Home Assistant helper logic lives in `scripts/`. It uses the
standard library plus `packaging`, which Home Assistant already ships, and is
held to the same lint, type, docstring and test gates as the integration.

## Code Conventions

- **Python 3.14+** required (matches Home Assistant 2026.10).
- **Conventional commits**: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`,
  `chore:`.
- **Prefer the standard library and Home Assistant helpers**. Add third-party
  dependencies only when they remove real complexity and after the trade-off is
  understood. When a vendor protocol library grows beyond integration glue,
  prefer a standalone async Python library so the Home Assistant code can stay
  focused on entities, config entries, diagnostics, and repairs.
- **Async first**: never block the event loop with network or disk I/O. If a
  dependency is synchronous, isolate it behind Home Assistant's executor helpers
  or replace it with an async path.
- **Typed code**: new code should be fully typed. Avoid `Any` unless the
  boundary is genuinely dynamic and document the shape as soon as it crosses
  into our code.
- **Error handling**: handle errors explicitly. Convert setup failures to the
  appropriate Home Assistant exceptions, surface user-fixable config problems in
  the flow, and avoid broad exception handling unless the boundary requires it.
- **Logging**: use module loggers. DEBUG is for protocol detail, INFO is rare
  operator-facing lifecycle context, WARNING is degraded behavior, and ERROR is
  broken behavior. Never log secrets, credentials, community strings, raw SNMPv3
  keys, or full diagnostics payloads.
- **Constants and enums**: use Home Assistant constants for device classes,
  state classes, units, platforms, and config keys whenever one exists. Avoid
  free-form strings for Home Assistant contracts.
- **Entity descriptions**: platform entities should be driven by typed entity
  descriptions where practical. Keep names, translation keys, device classes,
  units, state classes, and value transforms close together.
- **Tests**: keep risky behavior under focused tests. Prefer table-driven tests
  for protocol decoding, entity description mappings, config-flow validation,
  and syslog/event parsing.
- **Documentation**: see the [Documentation](#documentation) section below. The
  short version: docstrings are a reader-facing contract, not source narration.

## Home Assistant Integration Conventions

- **UI setup only**: device and service integrations are configured through
  config flows. Do not add YAML configuration for this integration.
- **Config entries own connection data**: store connection-critical data in
  `ConfigEntry.data`; use options only for settings that are not needed to make
  the connection.
- **Validate before storing**: the config flow should test reachability and
  credentials before creating an entry. Local validation errors should point at
  the bad field; network/device failures should use clear base errors.
- **Unique config entries**: do not allow the same UPS/NMC to be configured
  twice. Prefer stable device identifiers from the card over hostnames or IPs
  when available.
- **Runtime data belongs on the entry**: store runtime coordinators and clients
  in `ConfigEntry.runtime_data`, not module globals.
- **Unload cleanly**: support config-entry unloading and close protocol clients,
  listeners, dispatchers, and background tasks on every failure and unload path.
- **Use coordinators deliberately**: SNMP polling should flow through a
  `DataUpdateCoordinator` so entities share one coherent device snapshot. Push
  sources, such as syslog, should update coordinator data with
  `async_set_updated_data` when they provide authoritative state.
- **Entity lifecycle matters**: subscribe to push/event sources in
  `async_added_to_hass` and unsubscribe in removal/unload paths. Disabled
  entities should not create unnecessary device load.
- **Availability is explicit**: mark entities unavailable when the NMC cannot
  be reached or the relevant value is absent. Do not preserve stale values as if
  they are fresh.
- **Translations are first-class**: maintain `strings.json` and
  `translations/en.json` together. Config-flow fields, errors, exceptions,
  entity names, and icon translations should be translatable when they surface
  to users.
- **Diagnostics are useful and safe**: implement diagnostics that help users and
  maintainers debug real installations, but redact secrets and avoid dumping raw
  credential-bearing config or oversized protocol payloads.
- **Repairs beat mystery failures**: when user intervention is needed, prefer a
  repair issue or reauth/reconfigure flow over unexplained logs.
- **Device registry quality**: provide stable identifiers, manufacturer, model,
  firmware, serial, configuration URL, and suggested area when the NMC exposes
  them safely.
- **Docs track behavior**: if setup, entities, polling behavior, supported
  devices, limitations, or troubleshooting changes, update user-facing docs in
  the same PR.

## NMC Architecture Notes

- The integration code lives under
  `custom_components/schneider_ups_nmc/`.
- `snmp.py` owns SNMP protocol interaction and value normalization. Keep
  Home Assistant entity code out of the protocol layer.
- `coordinator.py` owns refresh cadence, data snapshots, and setup refresh
  semantics.
- Platform modules (`sensor.py`, `binary_sensor.py`, and future platforms)
  should translate coordinator snapshots into Home Assistant entities without
  performing their own network I/O.
- `config_flow.py` owns user input, validation, duplicate prevention, and
  entry creation.
- `diagnostics.py` owns redacted support data and should stay boring, bounded,
  and predictable.
- `syslog.py` owns local push/event parsing. Syslog can complement polling but
  should not become the sole source of truth unless the NMC event stream proves
  complete and durable.
- Keep Home Assistant boundaries honest. Avoid shared "utility" helpers until
  two real call sites prove the abstraction belongs there.

## Documentation

Docstrings are a product surface for contributors and maintainers. A reader
should understand how to use a public class, function, entity description, or
protocol type without opening every call site.

Public symbols carry the contract: inputs, outputs, exceptions, side effects,
and Home Assistant lifecycle expectations. Private symbols answer a different
question: why this exists in its current form. The test for whether a private
comment is earning its place:

> If a contributor deleted this symbol in a PR, would the surrounding code make
> clear why that is wrong?

If no, document the why. If yes, no comment needed.

Documentation is part of the reader-facing interface. A PR that changes behavior
without updating affected docs, docstrings, translations, or diagnostics is
incomplete in the same way a PR that changes behavior without updating tests is
incomplete.

## HACS & Release Engineering

- Keep exactly one integration under `custom_components/` for HACS.
- All runtime files required by Home Assistant belong inside
  `custom_components/schneider_ups_nmc/`.
- Keep `manifest.json`, `hacs.json`, `README.md`, translations, and brand assets
  aligned with each release.
- `manifest.json` must include clear ownership, documentation, issue tracker,
  integration type, IoT class, requirements, and version metadata.
- Release tags are semver tags with a leading `v`, such as `v0.1.0` or
  `v0.1.0-rc.1`.
- Prefer GitHub releases for user-facing HACS installs and upgrades once the
  integration is ready for users.
- Releases take two explicit steps because `main` only accepts signed commits
  through reviewed PRs. Run both from a `main` that matches `origin/main`;
  anywhere else they exit with the commands to get there.
  `just release-prepare <version>` branches
  `release/v<version>` from `origin/main`; writes the non-prefixed version,
  such as `0.1.0`, into `manifest.json` and `pyproject.toml`; refreshes
  `uv.lock`; runs the full local gate; and opens a `chore: release v<version>`
  PR. If any step fails it rolls back to the operator's previous branch. After
  the PR merges, `just release-publish <version>` finds the commit on
  `origin/main` that set the version (not the tip of `main`), checks its GitHub
  checks are green, pushes a signed `v`-prefixed tag such as `v0.1.0`, and
  creates the GitHub Release so HACS sees it as a release. Each step refuses
  with a pointer to the right one when run at the wrong time. Both accept
  either `0.1.0` or `v0.1.0` and normalize the two release surfaces.
- When Home Assistant ships a release, run `just ha-drift`. It exits non-zero
  if a manifest requirement conflicts with core's pinned packages, which is a
  setup failure for every user on that release. `just ha-upgrade` moves the
  test harness forward; decide in the same PR whether the `hacs.json`
  `homeassistant` minimum moves too.
- Every release gets a narrative GitHub release-note pass after the automated
  release is created. Do not leave GitHub's generated "What's Changed" list as
  the final release copy. Start the body with exactly one top-level `#` heading
  that describes the scope and spirit of the release instead of repeating the
  tag. Let that heading set the tone; this is prose, and a little personality is
  better than anodyne metadata. Explain the release theme and user impact, group
  related changes into readable sections, and keep PR links or the full
  changelog as supporting detail.
- Do not hardcode release-only behavior in integration source; keep version and
  packaging metadata in manifest/release automation.

## Security & Privacy

- Do not log secrets, SNMP community strings, SNMPv3 auth/privacy passphrases,
  session tokens, or raw credentials.
- Redact diagnostics before returning them to Home Assistant.
- Keep network listeners explicit about bind address, port, protocol, and
  teardown behavior.
- Treat syslog and SNMP payloads as local operational data. Bound logged payloads
  and avoid retaining raw event streams unless the user explicitly asks for a
  capture workflow.
- If persistent storage, repair data, or auth flows are added, document the
  operator-visible defaults and failure modes in the same PR.

## Pull Requests

- Run `just ci` locally before pushing.
- Keep PRs focused: one logical change per PR.
- Use conventional commit format for PR titles and commits.
- Reference issues with `Refs #NNN` or `Closes #NNN` when applicable.
- Update tests, docs, translations, and diagnostics in the same PR when behavior
  changes.
- Reply to actionable review comments with what changed, and resolve review
  threads after the fix is pushed and verified.

## Common Review Feedback

- **Blocking I/O in async paths** - protocol and file operations must not stall
  the Home Assistant event loop.
- **Misleading config-flow errors** - distinguish local validation problems from
  unreachable devices and authentication failures.
- **Leaked clients or listeners** - close SNMP engines, syslog listeners, and
  background tasks on setup failure and unload.
- **Stale state** - unavailable or absent values should not look fresh.
- **Untranslated user text** - user-visible names, config labels, errors, and
  exceptions should flow through Home Assistant translations.
- **Unsafe diagnostics** - redact secrets and keep diagnostic payloads bounded.
- **Unit drift** - use Home Assistant unit and device-class constants instead of
  raw strings.
- **Quality-scale drift** - keep implementation, tests, docs, diagnostics,
  repairs, and release metadata moving together toward platinum.
