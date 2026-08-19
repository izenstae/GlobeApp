"""Credential setup CLI.

python -m app.auth.cli setup --provider acled
python -m app.auth.cli status
python -m app.auth.cli refresh --provider acled
"""

import argparse
import asyncio
import getpass
import sys
from datetime import UTC, datetime

from app.auth.manager import CredentialManager
from app.auth.providers import REGISTRY
from app.db import dispose_engine, get_session_factory
from app.models.credentials import AUTH_STATIC_KEY

PROMPTS: dict[str, list[tuple[str, bool]]] = {
    # provider -> [(field, secret)]
    "acled": [("username", False), ("password", True)],
    "firms": [("api_key", True)],
}


async def cmd_setup(provider: str) -> int:
    if provider not in REGISTRY:
        print(f"unknown provider {provider!r}; known: {', '.join(sorted(REGISTRY))}")
        return 2
    creds: dict[str, str] = {}
    for field, secret in PROMPTS.get(provider, [("api_key", True)]):
        value = getpass.getpass(f"{field}: ") if secret else input(f"{field}: ")
        if not value:
            print("aborted: empty value")
            return 2
        creds[field] = value
    manager = CredentialManager(get_session_factory())
    try:
        await manager.register(provider, **creds)
    except Exception as exc:
        # Fail loudly rather than storing credentials that were never validated.
        print(f"setup FAILED for {provider}: {exc}")
        return 1
    finally:
        await manager.aclose()
    print(f"{provider}: credentials validated and stored.")
    return 0


async def cmd_status() -> int:
    manager = CredentialManager(get_session_factory())
    try:
        creds = await manager.status()
        if not creds:
            print("no credentials stored")
            return 0
        header = f"{'provider':<10} {'status':<9} {'expires in':<12} {'last refresh':<22} failures"
        print(header)
        print("-" * len(header))
        now = datetime.now(UTC)
        for c in creds:
            if c.auth_type == AUTH_STATIC_KEY:
                expires = "static"
            elif c.access_expires_at is None:
                expires = "-"
            else:
                mins = int((c.access_expires_at - now).total_seconds() // 60)
                expires = f"{mins} min"
            last = (
                c.last_refreshed_at.strftime("%Y-%m-%d %H:%M UTC") if c.last_refreshed_at else "-"
            )
            print(f"{c.provider:<10} {c.status:<9} {expires:<12} {last:<22} {c.refresh_failures}")
        return 0
    finally:
        await manager.aclose()


async def cmd_refresh(provider: str) -> int:
    manager = CredentialManager(get_session_factory())
    try:
        await manager.force_refresh(provider)
        print(f"{provider}: refreshed.")
        return 0
    except Exception as exc:
        print(f"refresh FAILED for {provider}: {exc}")
        return 1
    finally:
        await manager.aclose()


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.auth.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    p_setup = sub.add_parser("setup", help="interactive first-time credential setup")
    p_setup.add_argument("--provider", required=True)
    sub.add_parser("status", help="print credential status table")
    p_refresh = sub.add_parser("refresh", help="force a refresh now")
    p_refresh.add_argument("--provider", required=True)
    args = parser.parse_args()

    async def run() -> int:
        try:
            if args.command == "setup":
                return await cmd_setup(args.provider)
            if args.command == "status":
                return await cmd_status()
            return await cmd_refresh(args.provider)
        finally:
            await dispose_engine()

    sys.exit(asyncio.run(run()))


if __name__ == "__main__":
    main()
