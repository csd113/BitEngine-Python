# Bitcoin & Electrs Node Manager

A macOS desktop application for running and monitoring a self-sovereign Bitcoin full node and Electrs indexer — with a clean, native-feeling GUI, live terminal output, and one-click controls.

---

## Features

- **Side-by-side terminals** — live stdout from `bitcoind` and `electrs` displayed in real time
- **Traffic-light status indicators** — Running / Synced / Ready for each node, driven by actual RPC data and log parsing
- **Live block height** — polled every 5 seconds via Bitcoin JSON-RPC; displayed in the toolbar
- **Cookie authentication** — reads the `.cookie` file bitcoind writes on startup; no hardcoded credentials, no RPC auth errors
- **Configurable paths** — choose your Binaries folder, Bitcoin data directory, and Electrs DB directory via a collapsible path panel with folder pickers
- **Persistent config** — paths saved to `~/Library/Application Support/BitcoinNodeManager/` so they survive app updates and work correctly inside a `.app` bundle
- **Graceful shutdown** — stop Electrs only, or stop both nodes (Bitcoin via RPC `stop`, Electrs via `SIGTERM`)
- **Binary updater** — detects versioned builds from `~/Downloads/bitcoin_builds/binaries/` and copies the newest ones to your Binaries folder
- **Single-instance lock** — prevents the macOS double-launch bug that causes the app to flash open, close, and reopen
- **`.app` ready** — designed and tested for PyInstaller packaging

---

## Screenshots

> _TODO: add screenshots here_

---

## Requirements

| Dependency | Version | Notes |
|---|---|---|
| Python | 3.8+ | Standard library only, plus `requests` |
| `requests` | any | `pip install requests` |
| macOS | 11+ (Big Sur) | Designed for macOS; may work on Linux with minor changes |
| Bitcoin Core | 25+ | `bitcoind` binary |
| Electrs | 0.10+ | `electrs` binary |

---

## Directory Structure

The app expects your binaries and node data to live somewhere on disk. The defaults (configurable in the UI) are:

```
~/Documents/BitcoinNodeManager/      ← default data root when running as .app
├── Binaries/
│   ├── bitcoind
│   ├── bitcoin-cli
│   ├── bitcoin-tx
│   ├── bitcoin-util
│   └── electrs
├── BitcoinChain/                     ← bitcoind -datadir
│   ├── bitcoin.conf                  ← auto-created if missing
│   ├── .cookie                       ← written by bitcoind on each start
│   └── debug.log
└── ElectrsDB/                        ← electrs --db-dir
```

> **External SSD users:** point all three paths at your SSD via the Directory Paths panel. The app remembers them between launches.

---

## Installation

### 1. Install the Python dependency

```bash
pip install requests
```

### 2. Place your binaries

Copy `bitcoind`, `bitcoin-cli`, `bitcoin-tx`, `bitcoin-util`, and `electrs` into your Binaries folder (default: `~/Documents/BitcoinNodeManager/Binaries/`) and make them executable:

```bash
chmod +x ~/Documents/BitcoinNodeManager/Binaries/*
```

### 3. Run the script

```bash
python3 bitcoin_node_manager.py
```

---

## Building a macOS .app with PyInstaller

### Install PyInstaller

```bash
pip install pyinstaller
```

### Build

```bash
pyinstaller \
  --name="BitcoinNodeManager" \
  --windowed \
  --onefile \
  bitcoin_node_manager.py
```

> Omit `--icon=app_icon.icns` if you don't have an icon file.

### Move the app

```bash
mv dist/BitcoinNodeManager.app /Applications/
# or onto your external SSD:
mv dist/BitcoinNodeManager.app /Volumes/YourSSD/
```

> **Important:** do not run the app directly from the `dist/` build folder. Move it first, then launch it.

---

## Usage

### Starting nodes

1. Open **Bitcoin & Electrs Node Manager**
2. Confirm your directory paths in the **Directory Paths** panel (top of the window). Click **Save Paths** if you change anything.
3. Click **Launch** in the Bitcoin panel. Watch the terminal for output.
4. Wait for the **Running** indicator to turn green before launching Electrs.
5. Click **Launch** in the Electrs panel. Electrs will begin syncing its index from the Bitcoin chain.
6. When both panels show **Running**, **Synced**, and **Ready** in green, your node stack is fully operational.

### Status indicators

| Indicator | Meaning |
|---|---|
| **Running** | The process is alive |
| **Synced** | Bitcoin: `verificationprogress > 99.99%` and block height ≈ header height. Electrs: log output confirms index is caught up |
| **Ready** | Both Running and Synced are true |

### Shutting down

| Button | Effect |
|---|---|
| **Shutdown Bitcoind & Electrs** | Sends `SIGTERM` to Electrs, then sends `stop` via Bitcoin RPC |
| **Shutdown Electrs Only** | Sends `SIGTERM` to Electrs; Bitcoin keeps running |

---

## Configuration

### Directory Paths panel

The collapsible **Directory Paths** panel at the top of the window lets you set:

| Field | What it controls |
|---|---|
| **Binaries Folder** | Where the app looks for `bitcoind` and `electrs` executables |
| **Bitcoin Data Directory** | Passed to `bitcoind` as `-datadir`; also where the `.cookie` file is read from |
| **Electrs DB Directory** | Passed to `electrs` as `--db-dir` |

Click **Save Paths** to persist your choices to:
```
~/Library/Application Support/BitcoinNodeManager/node_manager_config.json
```

This file is separate from the `.app` bundle and survives app updates.

### bitcoin.conf

If no `bitcoin.conf` exists in your Bitcoin data directory, one is created automatically:

```ini
# Bitcoin Core — auto-generated by Node Manager
server=1
txindex=1
rpcport=8332
rpcallowip=127.0.0.1
# Cookie authentication is active by default.
```

Cookie authentication is used by default (no `rpcuser`/`rpcpassword` needed). The app reads the `.cookie` file bitcoind writes on each start, so RPC calls are always authenticated correctly.

### Electrs launch command

The app runs electrs with:

```bash
electrs \
  --network bitcoin \
  --daemon-dir <BitcoinDataDirectory> \
  --db-dir <ElectrsDBDirectory> \
  --electrum-rpc-addr 127.0.0.1:50001
```

Electrs auto-discovers the `.cookie` file from `--daemon-dir`, matching the behaviour of the equivalent manual shell command.

---

## Updating Binaries

If you use **BitForge** to compile custom Bitcoin and Electrs binaries:

1. Build your binaries with BitForge — they'll appear in `~/Downloads/bitcoin_builds/binaries/` structured like:
   ```
   ~/Downloads/bitcoin_builds/binaries/
   ├── bitcoin-27.0/
   │   ├── bitcoind
   │   ├── bitcoin-cli
   │   └── ...
   └── electrs-0.10.5/
       └── electrs
   ```
2. Click **Update Binaries…** in the toolbar
3. The app finds the highest-versioned folder for each binary, copies it to your Binaries folder, and sets executable permissions

If the `bitcoin_builds` folder isn't found, the app will offer to open BitForge or direct you to download it from [github.com/csd113/BitForge-Python](https://github.com/csd113/BitForge-Python).

---

## Troubleshooting

### "Binary Not Found" on launch
- Confirm the **Binaries Folder** path in the Directory Paths panel points to the folder containing `bitcoind` / `electrs`
- Check the files are executable: `chmod +x /path/to/Binaries/*`

### Bitcoin terminal shows RPC password errors
- This should not happen with the current version — the app uses cookie auth
- If it does, check that `bitcoin.conf` does **not** set `rpcauth=` or `rpcpassword=` (which would conflict with cookie auth)
- Delete the old `bitcoin.conf` and let the app regenerate it

### Electrs fails to connect to Bitcoin
- Make sure Bitcoin is **fully started** before launching Electrs (Running indicator is green)
- Confirm the Bitcoin Data Directory path is correct — Electrs reads the `.cookie` file from there
- Check the Electrs terminal for the specific error

### App opens, closes, then reopens
- This was a macOS double-launch bug fixed by the single-instance `fcntl` lock
- If it still happens, check that only one copy of the app exists in your Applications/SSD

### Block height stuck at "Connecting…"
- Bitcoin RPC is not yet ready — wait 20–30 seconds after launching `bitcoind`
- Verify `server=1` is set in `bitcoin.conf`

---

## Architecture Notes

| Area | Implementation |
|---|---|
| **Threading** | Each node runs in a daemon thread. All UI/state mutations go through `root.after(0, ...)` — tkinter is single-threaded |
| **Terminal output** | Thread-safe `queue.Queue` per node, drained every 100 ms by the main thread |
| **RPC auth** | `.cookie` file preferred; falls back to `rpcuser`/`rpcpassword` from `bitcoin.conf` |
| **Button rendering** | `tk.Button` is replaced by `MacButton` (a `tk.Label` subclass) because macOS's Aqua renderer ignores `bg`/`fg` on native buttons |
| **Single instance** | `fcntl.flock(LOCK_EX \| LOCK_NB)` on `/tmp/BitcoinNodeManager.lock` held for process lifetime |
| **Config storage** | `~/Library/Application Support/BitcoinNodeManager/` on macOS — never inside the `.app` bundle |

---

## License

This application is provided as-is for personal use.
