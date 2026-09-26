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
    # 只让「页面」链接打开 App;接口、日历订阅、静态资源仍交给浏览器 / 系统日历
    excluded = ["/api/*", "/cal/*", "/assets/*", "/.well-known/*", "/sw.js", "/manifest.webmanifest", "/*.png"]
    body = {
        "applinks": {
            "apps": [],
            "details": [
                {
                    "appIDs": [app_id],
                    "components": [*({"/": p, "exclude": True} for p in excluded), {"/": "*"}],
                    "appID": app_id,  # iOS 12 及更早的旧格式
                    "paths": [*(f"NOT {p}" for p in excluded), "*"],
                }
            ],
        },
        "webcredentials": {"apps": [app_id]},
    }
    return JSONResponse(body, media_type="application/json")
