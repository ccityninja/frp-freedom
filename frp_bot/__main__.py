#!/usr/bin/env python3
"""
FRP Bot — Main Orchestrator & CLI
"""

import json
import logging
import time
from pathlib import Path

import typer
from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from core.detector import DeviceDetector, DeviceInfo, identify_chipset
from core.method_selector import BypassMethod, MethodSelector
from tools.wrappers import ExecutionResult, get_executor

app = typer.Typer(name="frp-bot", help="Android FRP Bypass Orchestrator — Authorized Recovery Only")
console = Console()

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers=[RichHandler(console=console, rich_tracebacks=True)]
)
logger = logging.getLogger("frp-bot")


class FRPBot:
    """Main orchestrator"""

    def __init__(self, config_dir: Path = None):
        self.config_dir = config_dir or Path(__file__).parent.parent / "config"
        self.detector = DeviceDetector()
        self.selector = MethodSelector()
        self.session_log: list[dict] = []
        self.session_id = time.strftime("%Y%m%d_%H%M%S")

    def detect_devices(self) -> list[DeviceInfo]:
        """Detect all connected devices"""
        console.print("[bold cyan]Scanning for devices...[/bold cyan]")
        devices = self.detector.detect_all()

        if not devices:
            console.print("[red]No devices detected.[/red]")
            console.print("Check: USB cable, USB debugging, device mode (ADB/Fastboot/EDL/BROM/Download), drivers")
            return []

        # Enrich with chipset identification
        for dev in devices:
            dev.chipset = identify_chipset(dev)

        return devices

    def display_devices(self, devices: list[DeviceInfo]):
        """Pretty print detected devices"""
        table = Table(title="Detected Devices", show_header=True, header_style="bold magenta")
        table.add_column("#", style="dim")
        table.add_column("Serial")
        table.add_column("Brand")
        table.add_column("Model")
        table.add_column("Chipset")
        table.add_column("Android")
        table.add_column("Sec Patch")
        table.add_column("Connection")
        table.add_column("USB VID:PID")

        for i, dev in enumerate(devices):
            table.add_row(
                str(i + 1),
                dev.serial[:30],
                dev.brand or "?",
                dev.model or "?",
                dev.chipset or "?",
                dev.android_version or "?",
                dev.security_patch or "?",
                dev.connection_type,
                f"{dev.usb_vid}:{dev.usb_pid}" if dev.usb_vid else "?"
            )
        console.print(table)

    def select_methods(self, device: DeviceInfo) -> list[BypassMethod]:
        """Get ranked bypass methods for a device"""
        device_dict = {
            "brand": device.brand,
            "model": device.model,
            "chipset": device.chipset,
            "android_version": device.android_version,
            "security_patch": device.security_patch,
            "connection_type": device.connection_type,
            "serial": device.serial,
            "usb_vid": device.usb_vid,
            "usb_pid": device.usb_pid,
            "properties": device.properties,
        }
        return self.selector.select_methods(device_dict)

    def display_methods(self, methods: list[BypassMethod]):
        """Pretty print available methods"""
        table = Table(title="Available Bypass Methods (ranked)", show_header=True, header_style="bold green")
        table.add_column("Priority", justify="right")
        table.add_column("Tool")
        table.add_column("Function")
        table.add_column("Success Rate", justify="right")
        table.add_column("Requires")
        table.add_column("Conditions")

        for m in methods[:10]:  # Top 10
            table.add_row(
                str(m.priority),
                m.tool,
                m.function,
                f"{m.success_rate:.0%}",
                ", ".join(m.requires) if m.requires else "—",
                str(m.conditions)[:60] + "..." if len(str(m.conditions)) > 60 else str(m.conditions)
            )
        console.print(table)

    def execute_method(self, device: DeviceInfo, method: BypassMethod, dry_run: bool = False) -> ExecutionResult:
        """Execute a single bypass method"""
        console.print(Panel(f"[bold]Executing:[/bold] {method.tool}.{method.function}", border_style="yellow"))

        if dry_run:
            console.print("[yellow]DRY RUN — skipping actual execution[/yellow]")
            return ExecutionResult(True, "DRY RUN", "", 0.0)

        executor = get_executor(method.tool)
        if not executor:
            return ExecutionResult(False, "", f"No executor for tool: {method.tool}", 0.0)

        # Merge device info with method params
        params = {**method.params}

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
            transient=True,
        ) as progress:
            task = progress.add_task(f"Running {method.tool}...", total=None)
            result = executor.execute({
                "serial": device.serial,
                "brand": device.brand,
                "model": device.model,
                "chipset": device.chipset,
                "connection_type": device.connection_type,
                "properties": device.properties,
            }, params)
            progress.update(task, completed=True)

        # Log result
        log_entry = {
            "timestamp": time.time(),
            "session_id": self.session_id,
            "device_serial": device.serial,
            "tool": method.tool,
            "function": method.function,
            "success": result.success,
            "duration_sec": result.duration_sec,
            "output": result.output[-2000:] if result.output else "",
            "error": result.error[-2000:] if result.error else "",
            "artifacts": result.artifacts,
        }
        self.session_log.append(log_entry)

        if result.success:
            console.print(f"[green]✓ Success[/green] ({result.duration_sec:.1f}s)")
            if result.output:
                console.print(f"[dim]{result.output[:500]}[/dim]")
        else:
            console.print(f"[red]✗ Failed[/red] ({result.duration_sec:.1f}s)")
            if result.error:
                console.print(f"[red]{result.error[:500]}[/red]")

        return result

    def auto_bypass(self, device: DeviceInfo, max_attempts: int = 3, dry_run: bool = False) -> bool:
        """Try methods in priority order until one succeeds"""
        methods = self.select_methods(device)
        if not methods:
            console.print("[red]No applicable methods found for this device[/red]")
            return False

        self.display_methods(methods)

        for i, method in enumerate(methods[:max_attempts]):
            console.print(f"\n[bold]Attempt {i+1}/{max_attempts}[/bold]")
            result = self.execute_method(device, method, dry_run=dry_run)
            if result.success:
                if dry_run:
                    console.print(Panel(
                        "[bold yellow]DRY RUN COMPLETE — nothing was executed, no changes made[/bold yellow]",
                        border_style="yellow",
                    ))
                    return True
                console.print(Panel("[bold green]FRP BYPASS SUCCESSFUL[/bold green]", border_style="green"))
                return True
            console.print("[yellow]Method failed, trying next...[/yellow]")

        console.print(Panel("[bold red]All methods exhausted — FRP bypass failed[/bold red]", border_style="red"))
        return False

    def save_session_log(self, path: Path = None):
        """Save session log as JSONL"""
        if not path:
            path = Path(f"logs/session_{self.session_id}.jsonl")
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            for entry in self.session_log:
                f.write(json.dumps(entry) + "\n")
        console.print(f"[dim]Session log saved to {path}[/dim]")


@app.command()
def detect(
    verbose: bool = typer.Option(False, "-v", "--verbose", help="Verbose output"),
):
    """Detect connected Android devices"""
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    bot = FRPBot()
    devices = bot.detect_devices()
    if devices:
        bot.display_devices(devices)


@app.command()
def methods(
    serial: str = typer.Argument(None, help="Device serial (optional, picks first if omitted)"),
    verbose: bool = typer.Option(False, "-v", "--verbose", help="Verbose output"),
):
    """Show ranked bypass methods for a device"""
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    bot = FRPBot()
    devices = bot.detect_devices()
    if not devices:
        raise typer.Exit(1)

    if serial:
        device = next((d for d in devices if d.serial == serial), None)
        if not device:
            console.print(f"[red]Device {serial} not found[/red]")
            raise typer.Exit(1)
    else:
        device = devices[0]

    bot.display_devices([device])
    methods = bot.select_methods(device)
    bot.display_methods(methods)


@app.command()
def bypass(
    serial: str = typer.Argument(None, help="Device serial (optional, picks first if omitted)"),
    method: str = typer.Option(None, "--method", "-m", help="Force specific tool.function (e.g., mtkclient.erase_partitions)"),
    max_attempts: int = typer.Option(3, "--max-attempts", "-n", help="Max methods to try in auto mode"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be executed without running"),
    verbose: bool = typer.Option(False, "-v", "--verbose", help="Verbose output"),
):
    """Execute FRP bypass on a device"""
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    console.print(Panel(
        "[bold red]AUTHORIZED DEVICE RECOVERY ONLY[/bold red]\n"
        "Only run on devices you own or have explicit written authorization for.\n"
        "Backup partitions before erase. No cloud calls — all local.",
        border_style="red"
    ))

    bot = FRPBot()
    devices = bot.detect_devices()
    if not devices:
        raise typer.Exit(1)

    if serial:
        device = next((d for d in devices if d.serial == serial), None)
        if not device:
            console.print(f"[red]Device {serial} not found[/red]")
            raise typer.Exit(1)
    else:
        device = devices[0]

    bot.display_devices([device])

    if method:
        # Force specific method
        tool, func = method.split(".", 1) if "." in method else (method, "")
        methods = bot.select_methods(device)
        target = next((m for m in methods if m.tool == tool and (not func or m.function == func)), None)
        if not target:
            console.print(f"[red]Method {method} not applicable for this device[/red]")
            raise typer.Exit(1)
        result = bot.execute_method(device, target, dry_run=dry_run)
        success = result.success
    else:
        # Auto mode
        success = bot.auto_bypass(device, max_attempts=max_attempts, dry_run=dry_run)

    bot.save_session_log()
    raise typer.Exit(0 if success else 1)


@app.command()
def install_tools():
    """Install all supported open-source tools"""
    console.print("[bold]Installing FRP bypass tools...[/bold]")

    tools = [
        ("mtkclient", "pip install mtkclient"),
        ("edl", "pip install edl"),
        ("nPhoneCLI", "pip install git+https://github.com/nlckysolutions/nPhoneCLI"),
        ("frp-freedom", "pip install git+https://github.com/youngrichu/frp-freedom"),
        ("kirin_toolkit", "git clone https://github.com/FrgfA4ftfzTdfyyyr5f6tESD3/huawei_kirin_toolkit ~/huawei_kirin_toolkit"),
        ("mtk_studio", "git clone https://github.com/sukitanzil23/mtk-studio ~/mtk-studio && pip install -r ~/mtk-studio/requirements.txt"),
        ("SPDClient", "pip install spdclient"),  # For Linux/Termux
    ]

    for name, cmd in tools:
        console.print(f"\n[cyan]Installing {name}...[/cyan]")
        console.print(f"[dim]$ {cmd}[/dim]")
        # Note: We don't auto-run — user should review and run manually
        # This is intentional for safety

    console.print("\n[bold green]Install commands listed above. Run them manually after review.[/bold green]")
    console.print("[dim]Linux: also install udev rules and USB-DK drivers[/dim]")


@app.command()
def version():
    """Show version"""
    console.print("frp-bot v0.1.0 — Android FRP Bypass Orchestrator")


if __name__ == "__main__":
    app()
