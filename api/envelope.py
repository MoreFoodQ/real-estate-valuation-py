"""回應信封。

前端的 `axiosService.ts` 攔截器用 `'error' in body && 'data' in body` 判斷
回應是不是標準格式，所以**每一個回應都必須是 `{data, error}`**，
包括錯誤回應。FastAPI 預設的錯誤是 `{"detail": "..."}`，不改寫的話
前端只會看到 axios 的通用訊息，後端寫的錯誤說明整段被吃掉。

契約全文見 `api/CONTRACT.md`。
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


def ok(data: Any) -> dict[str, Any]:
    return {"data": jsonable(data), "error": None}


def fail(code: int, message: str) -> JSONResponse:
    """錯誤回應。`error.code` 放 HTTP 狀態碼（前端型別如此註解）。"""
    return JSONResponse(
        status_code=code,
        content={"data": None, "error": {"code": code, "message": message}},
    )


def jsonable(value: Any) -> Any:
    """把 kernel 回傳的 Decimal 轉成 JSON 能表達的數字。

    kernel 全程用 Decimal 是為了不讓二進位浮點誤差污染修正率與價格
    （官方答案 212,958 與 212,959 只差 1 元，就是這個誤差的量級）。
    轉換只發生在最外層輸出，計算過程一路都還是 Decimal。
    """
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return fail(exc.status_code, str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        # 422 是前端攔截器有特別處理的狀態碼，訊息要說得出哪個欄位不對。
        parts = [
            "%s：%s" % (".".join(str(x) for x in e.get("loc", [])), e.get("msg", ""))
            for e in exc.errors()
        ]
        return fail(422, "請求內容不合規：" + "；".join(parts))

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        return fail(500, "%s：%s" % (type(exc).__name__, exc))
