# FRP Repair Studio — Design

**Intent:** One local app: plug in any Android phone → it identifies the device and USB mode, checks which repair tools are actually present, tells you the next physical step, and runs verified steps on confirmation.

**Goals:** auto-detect (ADB→Fastboot→EDL→BROM→Download), per-device ranked methods, guided mode-entry steps, live logs, tool inventory (installed vs source-only), confirm-before-destructive.

**Non-goals:** guaranteed unlock for every phone (firmware/bootloader/auth loaders decide); cloud services; invented success rates.

**Anti-goals:** a button that blindly tries every exploit; showing "successful" on dry-run; guessing tool compatibility.

**Approach chosen:** local web dashboard (stdlib `http.server`) served from the repo, reusing `core/detector.py`, `core/method_selector.py`, `tools/wrappers.py`. Dropped: Typer-only UX (no guidance), Qt app (heavier deps).

**Safety rules (enforced server-side):**
- Every execute call is dry-run unless `dry_run:false` AND, for anything outside `SAFE_FUNCTIONS={printinfo,printgpt,read_partitions}`, the payload carries `confirm:"ERASE"`.
- Dry-run never touches an executor — returns the planned call only.
- API never exposes `success_rate`; every method ships `compatibility:"unverified"` until proven on hardware.

**Parts:** `app/tool_inventory.py` (installed vs downloaded), `app/server.py` (JSON API + guide), `app/static/index.html` (dashboard UI), tests in `tests/test_app.py`.

**Builder calls left open:** guide wording per chipset lane; poll interval (4s default).