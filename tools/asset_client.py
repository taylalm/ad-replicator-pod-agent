#!/usr/bin/env python3
"""ModelArk private asset library (Assets API) for Seedance 2.0 / 2.5 trusted inputs, referenced as asset://<id>.

Docs (read 25 Oct 2026): private-virtual-avatar-library-guide-preview, create-asset-group-api, create-asset-api,
get-asset-api. Endpoint POST https://ark.ap-southeast-1.byteplusapi.com/?Action=<Action>&Version=2024-01-01,
access-key (AK/SK) signature HMAC-SHA256 with credential scope <date>/ap-southeast-1/ark/request and signed headers
content-type;host;x-content-sha256;x-date (as in the CreateAsset request example). The API key does not work here.

Credentials come from the environment (BYTEPLUS_ACCESS_KEY / BYTEPLUS_SECRET_KEY, plus BYTEPLUS_SESSION_TOKEN for temporary STS keys, or VOLC_ACCESSKEY / VOLC_SECRETKEY)
or from the private file ~/.byteplus/asset_keys.env (BYTEPLUS_KEY_FILE overrides the path; outside the repo, chmod 600).
They are never printed or written.

Prerequisites (console, once): Advanced Creation Rights activated; authorization letter signed on the first group.
Only upload assets we own that do not resemble a real person (our own AI people, stills, clips). Our own unedited
Seedance videos/last frames and Seedream text-to-image faces are already trusted for 30 days without the library.

  asset_client.py create-group --name dzt-ai-cast [--description ...]
  asset_client.py upload --group <id> --url <https url> --type Image|Video|Audio [--name ...] [--wait]
  asset_client.py get <asset_id> | list [--group <id>] | delete <asset_id>
  add --dry-run to print the request without sending it
"""
import argparse
import datetime
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HOST = "ark.ap-southeast-1.byteplusapi.com"
REGION, SERVICE, VERSION = "ap-southeast-1", "ark", "2024-01-01"


KEY_FILE = os.path.expanduser(os.environ.get("BYTEPLUS_KEY_FILE", "~/.byteplus/asset_keys.env"))


def keys():
    if os.path.isfile(KEY_FILE):  # KEY=value lines; values are loaded into this process only, never printed
        for line in open(KEY_FILE):
            k, sep, v = line.strip().removeprefix("export ").partition("=")
            if sep and not k.startswith("#") and v.strip() and k.strip() not in os.environ:
                os.environ[k.strip()] = v.strip().strip("'\"")
    ak = os.environ.get("BYTEPLUS_ACCESS_KEY") or os.environ.get("VOLC_ACCESSKEY")
    sk = os.environ.get("BYTEPLUS_SECRET_KEY") or os.environ.get("VOLC_SECRETKEY")
    if not ak or not sk:
        sys.exit("Set BYTEPLUS_ACCESS_KEY and BYTEPLUS_SECRET_KEY (an IAM user's access key with ark:*Asset* permission).")
    return ak, sk


def _h(key, msg):
    return hmac.new(key, msg.encode(), hashlib.sha256).digest()


def call(action, body, dry_run=False):
    payload = json.dumps(body).encode()
    now = datetime.datetime.now(datetime.timezone.utc)
    x_date, day = now.strftime("%Y%m%dT%H%M%SZ"), now.strftime("%Y%m%d")
    body_hash = hashlib.sha256(payload).hexdigest()
    query = urllib.parse.urlencode(sorted({"Action": action, "Version": VERSION}.items()))
    token = None
    if not dry_run:
        keys()  # loads the key file, including a session token for temporary (STS) keys
        token = os.environ.get("BYTEPLUS_SESSION_TOKEN") or os.environ.get("VOLC_SESSION_TOKEN")
    head = f"content-type:application/json\nhost:{HOST}\nx-content-sha256:{body_hash}\nx-date:{x_date}\n"
    signed = "content-type;host;x-content-sha256;x-date"
    if token:  # temporary credentials: the token travels in X-Security-Token and is signed with the other headers
        head += f"x-security-token:{token}\n"
        signed += ";x-security-token"
    canonical = "\n".join(["POST", "/", query, head, signed, body_hash])
    scope = f"{day}/{REGION}/{SERVICE}/request"
    if dry_run:
        return {"dry_run": True, "url": f"https://{HOST}/?{query}", "body": body, "scope": scope, "signed_headers": signed}
    ak, sk = keys()
    to_sign = "\n".join(["HMAC-SHA256", x_date, scope, hashlib.sha256(canonical.encode()).hexdigest()])
    k = _h(_h(_h(_h(sk.encode(), day), REGION), SERVICE), "request")
    sig = hmac.new(k, to_sign.encode(), hashlib.sha256).hexdigest()
    req = urllib.request.Request(f"https://{HOST}/?{query}", data=payload, method="POST", headers={
        "Content-Type": "application/json", "Host": HOST, "X-Date": x_date, "X-Content-Sha256": body_hash,
        "Authorization": f"HMAC-SHA256 Credential={ak}/{scope}, SignedHeaders={signed}, Signature={sig}",
        **({"X-Security-Token": token} if token else {})})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            out = json.loads(r.read())
    except urllib.error.HTTPError as e:
        txt = e.read().decode(errors="replace")[:1000]
        try:
            out = json.loads(txt)
        except ValueError:
            out = {"http_status": e.code, "error": txt}
        out.setdefault("http_status", e.code)
    import re  # the service may echo the access key id in error messages: never print it
    out = json.loads(re.sub(r"\bAK[A-Za-z0-9]{8,}", lambda m: m.group(0)[:4] + "…", json.dumps(out)).replace(ak, "<access key>").replace(token or "\0", "<token>"))
    meta = out.get("ResponseMetadata") or {}
    if meta.get("Error"):
        return {"error": meta["Error"], "request_id": meta.get("RequestId")}
    return out.get("Result", out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["create-group", "upload", "get", "list", "delete"])
    ap.add_argument("id", nargs="?")
    ap.add_argument("--name")
    ap.add_argument("--description", default="")
    ap.add_argument("--group")
    ap.add_argument("--url")
    ap.add_argument("--type", choices=["Image", "Video", "Audio"])
    ap.add_argument("--project", default="default")
    ap.add_argument("--wait", action="store_true", help="upload: poll GetAsset until Active or Failed (max 15 min)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if a.cmd == "create-group":
        res = call("CreateAssetGroup", {"Name": a.name, "Description": a.description, "ProjectName": a.project}, a.dry_run)
    elif a.cmd == "upload":
        if not (a.group and a.url and a.type):
            sys.exit("upload needs --group, --url and --type")
        body = {"GroupId": a.group, "URL": a.url, "AssetType": a.type, "ProjectName": a.project}
        if a.name:
            body["Name"] = a.name[:64]
        res = call("CreateAsset", body, a.dry_run)
        if a.wait and res.get("Id"):
            end = time.time() + 900
            while time.time() < end:
                g = call("GetAsset", {"Id": res["Id"], "ProjectName": a.project})
                if g.get("Status") in ("Active", "Failed"):
                    res = {"Id": res["Id"], "Status": g.get("Status"), "uri": f"asset://{res['Id']}"}
                    break
                time.sleep(5)
    elif a.cmd == "get":
        res = call("GetAsset", {"Id": a.id, "ProjectName": a.project}, a.dry_run)
        res.pop("URL", None)  # presigned link: not needed for inference (asset:// is used)
    elif a.cmd == "list":
        f = {"GroupType": "AIGC"}
        if a.group:
            f["GroupIds"] = [a.group]
        res = call("ListAssets", {"Filter": f, "MaxResults": 50, "SortBy": "CreateTime", "SortOrder": "Desc"}, a.dry_run)
        for it in res.get("Items") or []:
            it.pop("URL", None)
    else:
        res = call("DeleteAsset", {"Id": a.id, "ProjectName": a.project}, a.dry_run)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
