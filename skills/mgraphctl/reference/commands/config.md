# `config`

Conventions, argument resolution, paging defaults, exit codes and environment variables
are in [`../commands.md`](../commands.md).

The optional TOML file at `~/.mgraphctl/config.toml` (or `--config PATH` / `MGRAPHCTL_CONFIG`).
Nothing in it is secret; the token cache stays in the OS keychain or a separate file.

### `config path`

| Option | Default | Meaning |
|---|---|---|
| `--json` | off | `{"path", "exists"}`. |

- **Graph:** none.
- **Scopes:** none.
- **Notes:** prints the path the other commands read, whether or not it exists.

### `config show`

| Option | Default | Meaning |
|---|---|---|
| `--json` | off | `{"path", "settings": {key: value}, "sources": {key: flag|env|file|default}, "unknownKeys"}`. |

- **Graph:** none.
- **Scopes:** none.
- **Notes:** one row per key with its effective value and where it came from. Keys in the file
  that mgraphctl does not know are listed, not rejected. A file that is not valid TOML fails
  this and every other command with `error[CONFIG]` (exit 2).

### `config init`

| Option | Default | Meaning |
|---|---|---|
| `--force` | off | Overwrite an existing file. |
| `--json` | off | `{"path", "overwritten"}`. |

- **Graph:** none.
- **Scopes:** none.
- **Notes:** writes a template with every key commented out at its default, mode `0600` in a
  `0700` directory. Refuses to overwrite without `--force` (`error[USAGE]`).

### `config set KEY VALUE`

| Option | Default | Meaning |
|---|---|---|
| `--json` | off | `{"path", "key", "value"}`. |

- **Graph:** none.
- **Scopes:** none.
- **Notes:** replaces the key's line in place (uncommenting a template line), or appends it;
  every comment survives. Creates the file when there is none. `KEY` must be one of the config
  keys; `debug`, `retries`, `timeout_ms` and `retry_base_ms` take non-negative integers, `tz`
  an IANA name and `token_store` one of `auto`, `keyring`, `file` — anything else is
  `error[USAGE]` and the file is untouched.

### `config unset KEY`

| Option | Default | Meaning |
|---|---|---|
| `--json` | off | `{"path", "key", "removed"}` — `removed` is false when the key was not set. |

- **Graph:** none.
- **Scopes:** none.
- **Notes:** comments the key's line out, so the environment variable or the default applies.
