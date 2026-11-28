kind: fixed
reason: v1.0 plan step 3 sub-step 3, direct request: "Remove the old numbering reading now."

The numbering before v0.11.0 (vX.Y.Z with X from 2 to 10) is no longer read as 0.x: version.to_zero_x,
LEGACY_FIRST_MAJOR and zero_x_string are gone, and updater.parse_version, version.release_key and
plugins/manifest.parse_app_version read plain numbers, so a SlideMage 2 sorts above every 1.x and a plugin or theme
range such as ">=9.0" now asks for SlideMage 9. The one conversion left is per project file: project.json written
before this release (no "version_scheme" key) is read through project.stored_version, which turns an old-numbering
version into its 0.x form, in project_status, compat.checked_version and compat.evaluate; record_project_open
rewrites those values once and writes version_scheme = 1, after which the file is read as written. Deck snapshots
write the key too. Tests: tests/test_version_scheme.py (replaces test_zero_x_string.py), test_beta_versions.py
(v2.0.0 from v1.x is a major step), test_project_format.py.

NEW: SlideMage is ready for version 2 numbers.
- Plugins and themes must state the SlideMage version they need in the current numbering (">=1.0"); one that still
  says ">=9.0" is shown as needing a newer SlideMage. Update such a plugin to its newest release.
- Projects last opened with a very old SlideMage are recognised as before; nothing changes for them.
