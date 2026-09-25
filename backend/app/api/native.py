"""原生 App 相关的公开文件:Apple 的 apple-app-site-association(Universal Links,把网页链接直接在 App 里打开)。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from ..deps import SettingsDep

public_router = APIRouter(tags=["native"])


@public_router.get("/.well-known/apple-app-site-association", include_in_schema=False)
def apple_app_site_association(settings: SettingsDep) -> JSONResponse:
    if not (settings.apple_team_id and settings.ios_bundle_id):
        raise HTTPException(status_code=404)
    app_id = f"{settings.apple_team_id}.{settings.ios_bundle_id}"
    body = {
        "applinks": {"apps": [], "details": [{"appID": app_id, "paths": ["*"]}]},
        "webcredentials": {"apps": [app_id]},
    }
    return JSONResponse(body, media_type="application/json")
