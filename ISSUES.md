# Known Issues

## [OPEN] Codex: bwrap `--argv0` fails inside sandbox

**Symptom:** Running `codex` inside a bubbly-agents sandbox produces:
```
bwrap: Unknown option --argv0
```
Codex uses bwrap internally for its own sandboxing. Nested bwrap (bwrap inside bwrap)
fails because the inner process cannot create new user namespaces from within the outer
sandbox.

**Workaround:** Add `use_legacy_landlock = true` under `[features]` in
`~/.codex/config.toml` inside the sandbox. This switches codex from bwrap to Linux
landlock for its internal sandboxing, which works inside an existing bwrap sandbox.

Also ensure `approval_policy` and `sandbox_mode` are at the **top level** of the file,
not nested under a `[projects]` section:

```toml
model           = "o4-mini"
approval_policy = "untrusted"
sandbox_mode    = "danger-full-access"

[features]
use_legacy_landlock = true
```

`sandbox_mode = "danger-full-access"` is safe here because bubbly-agents provides the
actual isolation boundary. `approval_policy = "untrusted"` keeps human approval before
any command runs.

**References:**
- https://github.com/openai/codex/issues/15283
- https://www.vincentschmalbach.com/breaking-out-of-the-codex-sandbox-while-keeping-approval-controls/

---

## [CLOSED] Symlink resolution: mounting `/bin` breaks Homebrew symlinks

**Symptom:** Mounting only `/home/linuxbrew/.linuxbrew/bin` as an extra path caused
symlinks like `bin/codex → Caskroom/codex/0.116.0/codex-x86_64-unknown-linux-musl`
to break inside the sandbox — the Caskroom target was not mounted.

**Fix:** Mount the parent `/home/linuxbrew/.linuxbrew` instead. All symlinks within
the same mounted tree resolve correctly.

Via CLI:
```bash
sandbox-ctl user create --user myuser --extra-path /home/linuxbrew/.linuxbrew
```

Via profile:
```ini
[sandbox]
ro-bind = /home/linuxbrew/.linuxbrew:/home/linuxbrew/.linuxbrew
```

---

## [CLOSED] Profile `bind` entry parsing: `:ro` suffix corrupted dest path

**Symptom:** In `profile.conf`, `bind = /src:/dest:ro` produced a dest of `/dest:ro`
(with the `:ro` suffix included in the path), and the read-only intent was silently
ignored — all profile bind mounts were read-write.

**Fix:** `sandbox/profiles.py` `load_profile` now uses a 3-part split and respects
both the `ro-bind` key and the `:ro` inline suffix. Fixed in commit `e9dcd01`.

---

## [CLOSED] `write_profile` dropped `[sandbox]` section on save

**Symptom:** Saving a profile via `write_profile` silently discarded all bind entries
and the sandbox hostname, so profiles did not round-trip through save/load.

**Fix:** `write_profile` now writes a `[sandbox]` section with `bind`/`ro-bind`
entries and hostname. Fixed in commit `e9dcd01`.

---

## [CLOSED] Launcher word-splitting on paths with spaces

**Symptom:** If a path entered in the TUI's "Extra host paths" field contained a space
(e.g. two paths pasted as one), the unquoted bash array in the generated launcher
word-split the entry into multiple elements. This shifted bwrap's argument positions,
causing bwrap to attempt to exec the path as a command:
```
bwrap: execvp /home/linuxbrew/.linuxbrew: Permission denied
```

**Fix:** `sandbox/launcher.py` now single-quotes all path values in `EXTRA_MOUNT_ARGS`.
The TUI label and placeholder were also updated to clarify one path per entry.
Fixed in commits `8014d08` and `bac5353`.
