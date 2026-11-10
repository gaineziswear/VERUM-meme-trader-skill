"""Supabase REST/Auth adapter with strict bearer-token forwarding and no service-role use."""
from __future__ import annotations
import os
from typing import Any
import httpx
from fastapi import HTTPException, Request

SAFE_CONSTRAINT_ERRORS = {
    "max_open_positions_reached", "duplicate_open_position", "insufficient_paper_cash",
    "max_total_exposure_reached", "max_risk_per_trade_exceeded", "daily_loss_limit_reached",
    "consecutive_loss_protection", "portfolio_drawdown_protection", "slippage_limit_reached",
    "invalid_trade_parameters", "open_position_not_found", "invalid_exit_quote",
}

class SupabaseStore:
    def __init__(self) -> None:
        self.url = os.getenv("SUPABASE_URL", "").rstrip("/")
        self.api_key = os.getenv("SUPABASE_PUBLISHABLE_KEY") or os.getenv("SUPABASE_ANON_KEY") or ""
        self.timeout = float(os.getenv("SUPABASE_HTTP_TIMEOUT", "12"))

    def ready(self) -> bool:
        return bool(self.url and self.api_key)

    def _headers(self, access_token: str | None = None, prefer: str | None = None) -> dict[str, str]:
        headers = {"apikey": self.api_key, "Accept": "application/json", "Content-Type": "application/json"}
        if access_token:
            headers["Authorization"] = "Bearer " + access_token
        if prefer:
            headers["Prefer"] = prefer
        return headers

    async def _request(self, method: str, path: str, *, access_token: str | None = None,
                       params: dict[str, Any] | None = None, payload: Any = None,
                       prefer: str | None = None) -> Any:
        if not self.ready():
            raise HTTPException(status_code=503, detail="database_not_configured")
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.request(method, self.url + path,
                    headers=self._headers(access_token, prefer), params=params, json=payload)
            if response.status_code >= 400:
                message = ""
                code = ""
                try:
                    body = response.json()
                    message = str(body.get("message") or body.get("msg") or "")
                    code = str(body.get("code") or "")
                except (ValueError, AttributeError):
                    pass
                if message in SAFE_CONSTRAINT_ERRORS or code == "23505":
                    raise HTTPException(status_code=409, detail=message or "duplicate_open_position")
                if response.status_code in (401, 403):
                    raise HTTPException(status_code=response.status_code,
                                        detail="invalid_session" if response.status_code == 401 else "access_denied")
                raise HTTPException(status_code=503, detail="database_request_failed")
            if response.status_code == 204 or not response.content:
                return []
            return response.json()
        except HTTPException:
            raise
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="database_timeout")
        except httpx.HTTPError:
            raise HTTPException(status_code=503, detail="database_unavailable")
        except ValueError:
            raise HTTPException(status_code=502, detail="database_invalid_response")

    async def user(self, access_token: str) -> dict[str, Any]:
        result = await self._request("GET", "/auth/v1/user", access_token=access_token)
        if not isinstance(result, dict) or not result.get("id"):
            raise HTTPException(status_code=401, detail="invalid_session")
        return result

    async def select(self, table: str, access_token: str | None = None,
                     params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        result = await self._request("GET", "/rest/v1/" + table, access_token=access_token, params=params)
        return result if isinstance(result, list) else []

    async def insert(self, table: str, payload: Any, access_token: str | None = None) -> Any:
        return await self._request("POST", "/rest/v1/" + table, access_token=access_token,
                                   payload=payload, prefer="return=representation")

    async def upsert(self, table: str, payload: Any, access_token: str | None = None,
                     on_conflict: str | None = None) -> Any:
        params = {"on_conflict": on_conflict} if on_conflict else None
        return await self._request("POST", "/rest/v1/" + table, access_token=access_token,
            params=params, payload=payload, prefer="resolution=merge-duplicates,return=representation")

    async def patch(self, table: str, access_token: str | None,
                    params: dict[str, Any], payload: Any) -> Any:
        return await self._request("PATCH", "/rest/v1/" + table, access_token=access_token,
            params=params, payload=payload, prefer="return=representation")

    async def rpc(self, name: str, payload: dict[str, Any], access_token: str | None = None) -> Any:
        return await self._request("POST", "/rest/v1/rpc/" + name,
                                   access_token=access_token, payload=payload)

store = SupabaseStore()

async def authenticated_user(request: Request) -> dict[str, Any]:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="authentication_required")
    token = header[7:].strip()
    if not token or len(token) > 8192:
        raise HTTPException(status_code=401, detail="invalid_session")
    user = await store.user(token)
    return {"id": user["id"], "access_token": token, "email": user.get("email")}
