"""Project files kept in a TOS bucket, so they outlive the agent session's file links (about a day).

Everything of a job lives under jobs/<job-id>/ in the bucket: its records (job.json, events.json, costs.json,
cost_cache.json and the site's own records such as captions_doc.json) and files/<name> for every file of the job.
The site copies each file there while the run happens, serves files from the bucket with short-lived signed links, and
a fresh server instance rebuilds its job list from the bucket.

Configuration (environment of the function): TOS_BUCKET, TOS_ENDPOINT, TOS_REGION. Credentials, in this order:
- the IAM role bound to the veFaaS function: the platform adds temporary keys to every request
  (x-faas-access-key-id, x-faas-secret-access-key, x-faas-session-token, valid up to 12 hours); the server keeps the
  newest ones (remember_request_credentials);
- TOS_ACCESS_KEY / TOS_SECRET_KEY (+ TOS_SECURITY_TOKEN) for local runs.
Without a bucket or credentials every call is a no-op and the site works as before.
"""
from __future__ import annotations

import os
import tempfile
import threading
import time
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional

PREFIX = "jobs/"
CRED_MAX_AGE = 10 * 3600  # request keys last up to 12 h; use them for 10
_LOCK = threading.Lock()
_CRED: Dict[str, object] = {}
_CLIENT: Dict[str, object] = {}
_STATE = {"last_error": None, "uploads": 0, "bytes": 0}


def bucket() -> str:
    return os.environ.get("TOS_BUCKET", "").strip()


def remember_request_credentials(headers) -> None:
    """Called for every request: the role's temporary keys, when the platform sends them."""
    ak = headers.get("x-faas-access-key-id")
    sk = headers.get("x-faas-secret-access-key")
    token = headers.get("x-faas-session-token")
    if ak and sk and token:
        with _LOCK:
            if _CRED.get("ak") != ak or _CRED.get("token") != token:
                _CRED.update(ak=ak, sk=sk, token=token, at=time.time(), source="function role")


def _credentials() -> Optional[dict]:
    with _LOCK:
        if _CRED.get("ak") and time.time() - float(_CRED.get("at") or 0) < CRED_MAX_AGE:
            return dict(_CRED)
    ak, sk = os.environ.get("TOS_ACCESS_KEY"), os.environ.get("TOS_SECRET_KEY")
    if ak and sk:
        return {"ak": ak, "sk": sk, "token": os.environ.get("TOS_SECURITY_TOKEN") or None, "source": "environment"}
    return None


def enabled() -> bool:
    return bool(bucket()) and _credentials() is not None


def _client():
    cred = _credentials()
    if not bucket() or not cred:
        return None
    key = f"{cred['ak']}|{cred.get('token') or ''}"
    with _LOCK:
        if _CLIENT.get("key") != key:
            import tos
            _CLIENT.update(key=key, client=tos.TosClientV2(
                cred["ak"], cred["sk"], os.environ.get("TOS_ENDPOINT", "tos-ap-southeast-1.bytepluses.com"),
                os.environ.get("TOS_REGION", "ap-southeast-1"), security_token=cred.get("token"),
                connection_time=10, socket_timeout=120, max_retry_count=2,
                enable_crc=False))  # the vendored crcmod is pure Python: slow on big videos
        return _CLIENT["client"]


def key(job_id: str, rel: str) -> str:
    return f"{PREFIX}{job_id}/{rel}"


def _fail(e: Exception) -> None:
    _STATE["last_error"] = f"{type(e).__name__}: {str(e)[:300]}"


def put_file(job_id: str, rel: str, path: Path) -> bool:
    c = _client()
    if not c or not path.is_file():
        return False
    try:
        c.put_object_from_file(bucket(), key(job_id, rel), str(path))
        _STATE["uploads"] += 1
        _STATE["bytes"] += path.stat().st_size
        return True
    except Exception as e:
        _fail(e)
        return False


def copy_url(job_id: str, rel: str, url: str) -> bool:
    """A file that only exists behind a download link (e.g. a session file): stream it to a temporary file, upload."""
    if not _client():
        return False
    fd, tmp = tempfile.mkstemp(prefix="tos_", suffix=Path(rel).suffix)
    os.close(fd)
    try:
        with urllib.request.urlopen(url, timeout=300) as r, open(tmp, "wb") as out:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                out.write(chunk)
        return put_file(job_id, rel, Path(tmp))
    except Exception as e:
        _fail(e)
        return False
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def get_bytes(job_id: str, rel: str) -> Optional[bytes]:
    c = _client()
    if not c:
        return None
    try:
        return c.get_object(bucket(), key(job_id, rel)).read()
    except Exception as e:
        if "404" not in str(e) and "NoSuchKey" not in str(e):
            _fail(e)
        return None


def download(job_id: str, rel: str, dest: Path) -> bool:
    data = get_bytes(job_id, rel)
    if data is None:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    tmp.write_bytes(data)
    os.replace(tmp, dest)
    return True


def signed_url(job_id: str, rel: str, expires: int = 3600) -> Optional[str]:
    c = _client()
    if not c:
        return None
    try:
        import tos
        return c.pre_signed_url(tos.HttpMethodType.Http_Method_Get, bucket(), key(job_id, rel), expires=expires).signed_url
    except Exception as e:
        _fail(e)
        return None


def list_keys(prefix: str) -> List[dict]:
    """[{key, size}] under a prefix (all pages)."""
    c = _client()
    if not c:
        return []
    out, token = [], None
    try:
        while True:
            r = c.list_objects_type2(bucket(), prefix=prefix, continuation_token=token, max_keys=1000)
            out += [{"key": o.key, "size": o.size} for o in (r.contents or [])]
            if not r.is_truncated:
                break
            token = r.next_continuation_token
    except Exception as e:
        _fail(e)
    return out


def list_jobs() -> List[str]:
    """Job ids that have a job.json in the bucket."""
    c = _client()
    if not c:
        return []
    ids, token = [], None
    try:
        while True:
            r = c.list_objects_type2(bucket(), prefix=PREFIX, delimiter="/", continuation_token=token, max_keys=1000)
            ids += [p.prefix[len(PREFIX):].strip("/") for p in (r.common_prefixes or [])]
            if not r.is_truncated:
                break
            token = r.next_continuation_token
    except Exception as e:
        _fail(e)
    return [i for i in ids if i.startswith("job-")]


def delete_job(job_id: str) -> int:
    """Removes everything of a job from the bucket. Returns how many objects were deleted."""
    c = _client()
    if not c:
        return 0
    import tos
    keys = [o["key"] for o in list_keys(f"{PREFIX}{job_id}/")]
    for i in range(0, len(keys), 1000):
        try:
            c.delete_multi_objects(bucket(), [tos.models2.ObjectTobeDeleted(k) for k in keys[i:i + 1000]], quiet=True)
        except Exception as e:
            _fail(e)
    return len(keys)


def status() -> dict:
    cred = _credentials()
    return {"bucket": bucket() or None, "configured": bool(bucket()), "credentials": (cred or {}).get("source"),
            "uploads": _STATE["uploads"], "bytes": _STATE["bytes"], "last_error": _STATE["last_error"]}


def self_test() -> dict:
    """Write, read, sign and delete one small object: proves the bucket, the endpoint and the permissions."""
    out = status()
    if not enabled():
        out["ok"] = False
        out["error"] = "no bucket configured" if not bucket() else "no credentials yet (the function role's keys arrive with requests)"
        return out
    probe = f"_selftest/{int(time.time())}.txt"
    c = _client()
    try:
        import io
        c.put_object(bucket(), probe, content=io.BytesIO(b"ok"))
        back = c.get_object(bucket(), probe).read()
        url = c.pre_signed_url(__import__("tos").HttpMethodType.Http_Method_Get, bucket(), probe, expires=60).signed_url
        with urllib.request.urlopen(url, timeout=30) as r:
            via_link = r.read()
        c.delete_object(bucket(), probe)
        out.update(ok=back == b"ok" and via_link == b"ok", read_back=back == b"ok", signed_link=via_link == b"ok")
    except Exception as e:
        out.update(ok=False, error=f"{type(e).__name__}: {str(e)[:400]}")
    return out
