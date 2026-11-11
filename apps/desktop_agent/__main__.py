"""Desktop agent for Personal OS.

    uv run python -m apps.desktop_agent pair --code ABCD-EFGH   # once, with a code from the Hub
    uv run python -m apps.desktop_agent run                     # connect and wait for actions
    uv run python -m apps.desktop_agent forget                  # delete the stored token

The token is kept in Windows Credential Manager (keyring) and never printed.
Exit codes of `run`: 0 stopped, 2 not paired, 3 token rejected (pair again), 4 replaced.
"""

import argparse
import asyncio
import json
import logging
import sys
import urllib.error
import urllib.parse
import urllib.request

from apps.desktop_agent.config import AgentConfig, this_platform
from apps.desktop_agent.connection import AgentExit, run_agent
from apps.desktop_agent.controller import load_controller
from apps.desktop_agent.executor import Executor
from apps.desktop_agent.token_store import KeyringTokenStore

logger = logging.getLogger("apps.desktop_agent")


def _pair(config: AgentConfig, code: str) -> int:
    url = urllib.parse.urlsplit(config.hub_url)
    if url.scheme != "https" and url.hostname not in ("127.0.0.1", "localhost", "::1"):
        print(f"warning: {config.hub_url} is plain http to another machine; the code and the")
        print("token would cross the network unencrypted (ADR 0014 D4: loopback until S4)")
    body = json.dumps(
        {"code": code, "device_name": config.device_name, "platform": this_platform()}
    ).encode()
    request = urllib.request.Request(
        config.hub_url.rstrip("/") + "/devices/pair",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            paired = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        print(f"pairing refused (HTTP {exc.code}): the code is wrong, used or expired")
        return 1
    except OSError as exc:
        print(f"could not reach the Hub at {config.hub_url}: {exc}")
        return 1
    KeyringTokenStore(config.keyring_service).set(paired["token"])
    print(f"paired as device {paired['device_id']}; token stored in keyring")
    return 0


def _run(config: AgentConfig) -> int:
    executor = Executor(load_controller())
    try:
        reason = asyncio.run(run_agent(config, KeyringTokenStore(config.keyring_service), executor))
    except KeyboardInterrupt:
        reason = AgentExit.stopped
    finally:
        executor.close()
    logger.info("agent stopped: %s", reason.name)
    return int(reason)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m apps.desktop_agent",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--hub-url", help="default: POS_AGENT_HUB_URL or http://127.0.0.1:8765")
    parser.add_argument("--keyring-service", help="default: personal-os-agent")
    parser.add_argument("--device-name", help="default: this computer's name")
    commands = parser.add_subparsers(dest="command", required=True)
    pair = commands.add_parser("pair", help="pair with the Hub using a one-time code")
    pair.add_argument("--code", required=True)
    commands.add_parser("run", help="connect to the Hub and execute actions")
    commands.add_parser("forget", help="delete this agent's token from keyring")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = AgentConfig.from_env(
        hub_url=args.hub_url, keyring_service=args.keyring_service, device_name=args.device_name
    )
    if args.command == "pair":
        return _pair(config, args.code)
    if args.command == "forget":
        KeyringTokenStore(config.keyring_service).delete()
        print("token deleted")
        return 0
    return _run(config)


if __name__ == "__main__":
    sys.exit(main())
