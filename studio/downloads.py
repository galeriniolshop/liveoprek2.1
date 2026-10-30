from __future__ import annotations
import hashlib
import hmac
import time
from urllib.parse import urlencode
from .config import secret
from . import store


def signature(asset_id, expires):
    from upload_server import upload_token
    msg = f"{asset_id}:{expires}".encode()
    return hmac.new(upload_token().encode(), msg, hashlib.sha256).hexdigest()


def download_url(asset_id):
    a = store.asset(asset_id)
    base = secret("UPLOAD_PUBLIC_URL").rstrip("/")
    if not base:
        return None
    if not base.startswith(("https://", "http://")):
        raise ValueError("UPLOAD_PUBLIC_URL harus URL HTTP(S).")
    expires = int(time.time())+600
    return base+"/api/download?"+urlencode({"asset": a["id"], "expires": expires, "signature": signature(a["id"], expires)})