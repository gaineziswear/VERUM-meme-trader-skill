"""Read-only public data adapters. Each provider result carries source and freshness."""
from __future__ import annotations

import asyncio
import os
import time
from typing import Any

import httpx

DEX = "https://api.dexscreener.com"
RUGCHECK = "https://api.rugcheck.xyz/v1"
GOPLUS = "https://api.gopluslabs.io/api/v1"
JUPITER = "https://api.jup.ag"
GECKO = "https://api.geckoterminal.com/api/v2"
JUPITER_API_KEY = os.getenv("JUPITER_API_KEY", "").strip()
_JUPITER_LOCK = asyncio.Lock()
_JUPITER_LAST_CALL = 0.0
SOLANA_RPC = "https://api.mainnet-beta.solana.com"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


async def get_json(url: str, params: dict[str, Any] | None = None,
                   timeout: float = 12.0,
                   extra_headers: dict[str, str] | None = None) -> tuple[Any | None, dict[str, Any]]:
    started = time.monotonic()
    try:
        headers = {"Accept": "application/json", "User-Agent": "VERUM-Meme-Intelligence/0.1"}
        headers.update(extra_headers or {})
        async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return response.json(), {"status": "OK", "fetched_at": time.time(),
                                      "latency_ms": int((time.monotonic() - started) * 1000),
                                      "http_status": response.status_code}
    except Exception as exc:
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        return None, {"status": "RATE_LIMITED" if status_code == 429 else "UNAVAILABLE",
                      "fetched_at": time.time(),
                      "latency_ms": int((time.monotonic() - started) * 1000),
                      "http_status": status_code, "error": type(exc).__name__}


async def post_json(url: str, payload: dict[str, Any],
                    timeout: float = 12.0) -> tuple[Any | None, dict[str, Any]]:
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=timeout, headers={
            "Accept": "application/json", "User-Agent": "VERUM-Meme-Intelligence/0.1"
        }) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            return response.json(), {"status": "OK", "fetched_at": time.time(),
                                     "latency_ms": int((time.monotonic() - started) * 1000),
                                     "http_status": response.status_code}
    except Exception as exc:
        return None, {"status": "UNAVAILABLE", "fetched_at": time.time(),
                      "latency_ms": int((time.monotonic() - started) * 1000),
                      "error": type(exc).__name__}


async def dex_pairs(mint: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    data, meta = await get_json(f"{DEX}/tokens/v1/solana/{mint}")
    return (data if isinstance(data, list) else []), {**meta, "source": "DexScreener"}


async def rugcheck_report(mint: str) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    data, meta = await get_json(f"{RUGCHECK}/tokens/{mint}/report")
    return (data if isinstance(data, dict) else None), {**meta, "source": "RugCheck"}


async def goplus_report(mint: str) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    data, meta = await get_json(f"{GOPLUS}/solana/token_security",
                                params={"contract_addresses": mint})
    result = data.get("result") if isinstance(data, dict) else None
    if isinstance(result, dict):
        value = result.get(mint) or next(iter(result.values()), None)
        return (value if isinstance(value, dict) else None), {**meta, "source": "GoPlus"}
    return None, {**meta, "source": "GoPlus"}


async def jupiter_candles(mint: str, limit: int = 500) -> tuple[Any | None, dict[str, Any]]:
    params = {"interval": "1_MINUTE", "to": int(time.time()),
              "candles": max(60, min(1000, limit)), "type": "price"}
    data, meta = await get_json(f"https://datapi.jup.ag/v2/charts/{mint}", params=params, timeout=15)
    return data, {**meta, "source": "Jupiter OHLCV"}


async def gecko_candles(pool_address: str, limit: int = 500) -> tuple[Any | None, dict[str, Any]]:
    params = {"aggregate": 1, "limit": max(60, min(1000, limit)),
              "currency": "usd", "token": "base"}
    data, meta = await get_json(
        f"{GECKO}/networks/solana/pools/{pool_address}/ohlcv/minute",
        params=params, timeout=15,
    )
    return data, {**meta, "source": "GeckoTerminal OHLCV"}


async def token_decimals(mint: str) -> tuple[int | None, dict[str, Any]]:
    body = {"jsonrpc": "2.0", "id": 1, "method": "getTokenSupply",
            "params": [mint, {"commitment": "confirmed"}]}
    data, meta = await post_json(SOLANA_RPC, body, timeout=10)
    try:
        decimals = int(data["result"]["value"]["decimals"])
        return decimals, {**meta, "source": "Solana RPC"}
    except (KeyError, TypeError, ValueError):
        return None, {**meta, "status": "UNAVAILABLE",
                      "source": "Solana RPC", "error": "decimals_unavailable"}


async def jupiter_quote(input_mint: str, output_mint: str, amount: int,
                        slippage_bps: int = 100) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    global _JUPITER_LAST_CALL
    async with _JUPITER_LOCK:
        interval = 1.05 if JUPITER_API_KEY else 2.1
        wait = interval - (time.monotonic() - _JUPITER_LAST_CALL)
        if wait > 0:
            await asyncio.sleep(wait)
        _JUPITER_LAST_CALL = time.monotonic()
        headers = {"x-api-key": JUPITER_API_KEY} if JUPITER_API_KEY else None
        params = {"inputMint": input_mint, "outputMint": output_mint,
                  "amount": amount, "slippageBps": slippage_bps,
                  "instructionVersion": "V2"}
        data, meta = await get_json(
            f"{JUPITER}/swap/v1/quote", params=params, timeout=15, extra_headers=headers,
        )
        if meta.get("status") == "RATE_LIMITED":
            await asyncio.sleep(2.1)
            data, meta = await get_json(
                f"{JUPITER}/swap/v1/quote", params=params, timeout=15, extra_headers=headers,
            )
            _JUPITER_LAST_CALL = time.monotonic()
    return (data if isinstance(data, dict) and data.get("outAmount") else None), {
        **meta, "source": "Jupiter Swap quote (V2 instructions)", "quote_at": time.time()
    }


async def solana_signatures(address: str, limit: int = 100) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    body = {"jsonrpc": "2.0", "id": 1, "method": "getSignaturesForAddress",
            "params": [address, {"limit": max(1, min(100, limit))}]}
    data, meta = await post_json(SOLANA_RPC, body, timeout=12)
    rows = data.get("result") or [] if isinstance(data, dict) else []
    return rows, {**meta, "source": "Solana RPC"}


async def latest_profiles() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    data, meta = await get_json(f"{DEX}/token-profiles/latest/v1")
    rows = [row for row in (data or []) if isinstance(row, dict)
            and row.get("chainId") == "solana" and row.get("tokenAddress")]
    return rows, {**meta, "source": "DexScreener latest profiles"}
