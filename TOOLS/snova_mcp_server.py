#!/usr/bin/env python3

import asyncio
import os
import shlex
import sys
from typing import Optional

# Prefer the official MCP Python SDK if available; fall back to fastmcp if installed under a different name.
try:
    from mcp.server.fastmcp import FastMCP  # type: ignore
except Exception:  # pragma: no cover - import fallback
    try:
        from fastmcp import FastMCP  # type: ignore
    except Exception as import_error:  # pragma: no cover
        sys.stderr.write(
            "ERROR: Could not import MCP server library. Install 'mcp' (preferred) or 'fastmcp'.\n"
        )
        raise import_error

SERVER_NAME = "snova-adapter"
SERVER_VERSION = "0.1.0"

DEFAULT_SNOVA_PATH = os.environ.get("SNOVA_PATH", "/Users/rgoldin/Downloads/snova")
DEFAULT_CONNECTION_NAME = os.environ.get("SNOVA_CONNECTION", "default")
DEFAULT_LOG_LEVEL = os.environ.get("SNOVA_LOG_LEVEL", "INFO")

server = FastMCP(
    SERVER_NAME,
    version=SERVER_VERSION,
    description="Thin MCP stdio adapter that proxies the Snova CLI via --print",
)

async def run_snova_print(
    prompt_text: str,
    connection_name: str,
    snova_path: str,
    log_level: str,
    timeout_seconds: Optional[float] = 180.0,
) -> str:
    """Run the Snova CLI with --print to get a single response for the provided prompt.

    This executes the Snova binary using the given Snowflake connection profile name.
    """
    if not prompt_text or not prompt_text.strip():
        return ""

    command_parts = [
        snova_path,
        "-c",
        connection_name,
        "--log-level",
        log_level,
        "--print",
        prompt_text,
    ]

    # Ensure the binary exists and is executable
    if not os.path.exists(snova_path):
        raise FileNotFoundError(f"Snova binary not found at path: {snova_path}")
    if not os.access(snova_path, os.X_OK):
        raise PermissionError(f"Snova binary is not executable: {snova_path}")

    process = await asyncio.create_subprocess_exec(
        *command_parts,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=os.getcwd(),
    )

    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            process.communicate(), timeout=timeout_seconds
        )
    except asyncio.TimeoutError:
        try:
            process.kill()
        except Exception:
            pass
        raise TimeoutError(
            f"Snova command timed out after {timeout_seconds} seconds: {shlex.join(command_parts)}"
        )

    stdout_text = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
    stderr_text = stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else ""

    if process.returncode != 0:
        # Surface stderr to the caller to aid debugging in Cursor
        raise RuntimeError(
            f"Snova exited with code {process.returncode}. Command: {shlex.join(command_parts)}\nSTDERR:\n{stderr_text.strip()}"
        )

    # Prefer stdout; snova --print should print a single response and exit
    # Strip trailing newlines for a cleaner MCP response
    return stdout_text.rstrip("\n")


@server.tool()
async def snova_print(
    prompt: str,
    connection: Optional[str] = None,
    snova_path: Optional[str] = None,
    log_level: Optional[str] = None,
    timeout_seconds: Optional[float] = 180.0,
) -> str:
    """Call Snova to get a one-shot response for a prompt using --print.

    - prompt: The text prompt to send to Snova.
    - connection: Snowflake connection name from ~/.snowflake/connections.toml (defaults to 'default').
    - snova_path: Absolute path to the Snova binary (defaults to /Users/rgoldin/Downloads/snova or SNOVA_PATH env).
    - log_level: Logging level for Snova (DEBUG, INFO, WARNING, ERROR, CRITICAL). Defaults to INFO.
    - timeout_seconds: Maximum time to allow the Snova process to run before failing.
    """
    resolved_connection = (connection or DEFAULT_CONNECTION_NAME).strip()
    resolved_snova_path = (snova_path or DEFAULT_SNOVA_PATH).strip()
    resolved_log_level = (log_level or DEFAULT_LOG_LEVEL).strip()

    result_text = await run_snova_print(
        prompt_text=prompt,
        connection_name=resolved_connection,
        snova_path=resolved_snova_path,
        log_level=resolved_log_level,
        timeout_seconds=timeout_seconds,
    )

    return result_text


if __name__ == "__main__":
    # Run the server over stdio so Cursor can launch it directly
    server.run_stdio()

