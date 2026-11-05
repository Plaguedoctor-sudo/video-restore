from __future__ import annotations

import os
from pathlib import Path

from . import telegram


def resolve(ref: str, workdir: Path, *, api_id: int | None = None,
            api_hash: str | None = None, session: str = "vr_session") -> Path:
    """Turn a local path or t.me link into a local file."""
    if not telegram.is_link(ref):
        p = Path(ref).expanduser()
        if not p.exists():
            raise FileNotFoundError(ref)
        return p

    if api_id is None or api_hash is None:
        for env_path in (workdir / ".env", Path(".env")):
            if env_path.exists():
                for line in env_path.read_text().splitlines():
                    if "=" in line and not line.strip().startswith("#"):
                        k, v = line.split("=", 1)
                        os.environ.setdefault(k.strip(), v.strip().strip("'\""))
                break

    if api_id is None:
        raw_id = os.environ.get("TELEGRAM_API_ID") or os.environ.get("TG_API_ID")
        if raw_id:
            try:
                api_id = int(raw_id)
            except ValueError:
                pass
    if api_hash is None:
        api_hash = os.environ.get("TELEGRAM_API_HASH") or os.environ.get("TG_API_HASH")

    channel, msg_id = telegram.parse_link(ref)
    dest = workdir / f"{channel}_{msg_id}.mp4"
    if dest.exists():
        return dest
    try:
        return telegram.fetch_public(channel, msg_id, dest)
    except Exception:
        if api_id and api_hash:
            return telegram.fetch_authed(ref, dest, api_id, api_hash, session)
        raise
