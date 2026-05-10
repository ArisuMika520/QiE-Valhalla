from __future__ import annotations

import gzip
import json
import time
import zlib
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .cookie import cookie_header_from_mapping, parse_cookie_header, qq_gtk


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
DEFAULT_SEC_CH_UA = (
    '"Chromium";v="124", "Google Chrome";v="124", "Not.A/Brand";v="99"'
)
DEFAULT_SEC_CH_UA_PLATFORM = '"Windows"'


class QQAPIError(RuntimeError):
    pass


@dataclass(frozen=True)
class QQResponse:
    endpoint: str
    request_data: dict[str, Any]
    data: dict[str, Any]


class QQClient:
    base_url = "https://qun.qq.com"

    def __init__(
        self,
        cookie_header: str,
        timeout: float = 15,
        user_agent: str | None = None,
        accept_language: str | None = None,
        sec_ch_ua: str | None = None,
        sec_ch_ua_platform: str | None = None,
    ) -> None:
        self.cookies = parse_cookie_header(cookie_header)
        self.cookie_header = cookie_header_from_mapping(self.cookies)
        self.timeout = timeout
        self.user_agent = user_agent or DEFAULT_USER_AGENT
        self.accept_language = accept_language or "zh-CN,zh;q=0.9"
        self.sec_ch_ua = sec_ch_ua or DEFAULT_SEC_CH_UA
        self.sec_ch_ua_platform = sec_ch_ua_platform or DEFAULT_SEC_CH_UA_PLATFORM

    @property
    def skey(self) -> str:
        return self.cookies.get("skey", "")

    @property
    def p_skey(self) -> str:
        return self.cookies.get("p_skey", "")

    def request_qun_mgr(self, action: str, data: dict[str, Any] | None = None) -> QQResponse:
        if not self.skey:
            raise QQAPIError("缺少 skey，无法计算 qun_mgr 接口需要的 bkn。")
        body = dict(data or {})
        bkn = qq_gtk(self.skey)
        body.setdefault("bkn", bkn)
        query = urlencode({"bkn": bkn, "ts": str(int(time.time() * 1000))})
        endpoint = f"/cgi-bin/qun_mgr/{action}"
        url = f"{self.base_url}{endpoint}?{query}"
        response = self._post_form(url, body)
        self._raise_for_qq_error(response, action)
        return QQResponse(endpoint=endpoint, request_data=body, data=response)

    def request_qun_tag(self, action: str, data: dict[str, Any] | None = None) -> QQResponse:
        if not self.p_skey:
            raise QQAPIError("缺少 p_skey，无法计算 qunapi 接口需要的 g_tk。")
        query = urlencode({"g_tk": qq_gtk(self.p_skey), "ts": str(int(time.time() * 1000))})
        endpoint = f"/cgi-bin/qunapi/qun_tag/{action}"
        url = f"{self.base_url}{endpoint}?{query}"
        body = dict(data or {})
        response = self._post_json(url, body)
        self._raise_for_qq_error(response, action)
        return QQResponse(endpoint=endpoint, request_data=body, data=response)

    def get_group_list(self) -> QQResponse:
        return self.request_qun_mgr("get_group_list", {})

    def search_group_members(
        self,
        group_id: str | int,
        start: int,
        end: int,
        *,
        sort: int | None = None,
        key: str | None = None,
        gender: int | None = None,
        extra_filters: dict[str, Any] | None = None,
    ) -> QQResponse:
        payload: dict[str, Any] = {
            "gc": str(group_id),
            "st": int(start),
            "end": int(end),
        }
        if sort is not None:
            payload["sort"] = sort
        if key:
            payload["key"] = key
        if gender is not None and gender != -1:
            payload["g"] = gender
        if extra_filters:
            payload.update({k: v for k, v in extra_filters.items() if v not in (None, "")})
        return self.request_qun_mgr("search_group_members", payload)

    def get_search_options(self) -> QQResponse:
        return self.request_qun_tag("get_search_options", {})

    def _headers(self, content_type: str) -> dict[str, str]:
        return {
            "Host": "qun.qq.com",
            "Connection": "keep-alive",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "sec-ch-ua": self.sec_ch_ua,
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": self.sec_ch_ua_platform,
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/plain, */*",
            "Content-Type": content_type,
            "X-Requested-With": "XMLHttpRequest",
            "Origin": self.base_url,
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
            "Referer": f"{self.base_url}/member.html",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": self.accept_language,
            "Cookie": self.cookie_header,
        }

    def _post_form(self, url: str, data: dict[str, Any]) -> dict[str, Any]:
        body = urlencode(data, doseq=True).encode("utf-8")
        return self._send(url, body, self._headers("application/x-www-form-urlencoded;charset=UTF-8"))

    def _post_json(self, url: str, data: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return self._send(url, body, self._headers("application/json;charset=UTF-8"))

    def _send(self, url: str, body: bytes, headers: dict[str, str]) -> dict[str, Any]:
        request = Request(url, data=body, headers=headers, method="POST")
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
                encoding = (response.headers.get("Content-Encoding") or "").lower()
        except HTTPError as exc:
            detail = self._decode_error_body(exc)
            raise QQAPIError(f"HTTP {exc.code}: {detail[:300]}") from exc
        except URLError as exc:
            raise QQAPIError(f"网络请求失败：{exc.reason}") from exc
        raw = self._decompress(raw, encoding)
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            text = raw.decode("utf-8", errors="replace")
            raise QQAPIError(f"接口没有返回 JSON，前 300 字符：{text[:300]}") from exc
        if not isinstance(parsed, dict):
            raise QQAPIError("接口返回不是 JSON object。")
        return parsed

    @staticmethod
    def _decompress(raw: bytes, encoding: str) -> bytes:
        if not encoding or encoding == "identity":
            return raw
        if encoding == "gzip":
            return gzip.decompress(raw)
        if encoding == "deflate":
            try:
                return zlib.decompress(raw)
            except zlib.error:
                return zlib.decompress(raw, -zlib.MAX_WBITS)
        if encoding == "br":
            try:
                import brotli  # type: ignore[import-not-found]
            except ImportError as exc:
                raise QQAPIError(
                    "服务端返回 br 压缩，但未安装 brotli 库；请 `pip install brotli`。"
                ) from exc
            return brotli.decompress(raw)
        raise QQAPIError(f"不支持的 Content-Encoding：{encoding}")

    @classmethod
    def _decode_error_body(cls, exc: HTTPError) -> str:
        try:
            raw = exc.read()
        except Exception:
            return ""
        encoding = (exc.headers.get("Content-Encoding") if exc.headers else "") or ""
        try:
            raw = cls._decompress(raw, encoding.lower())
        except QQAPIError:
            pass
        return raw.decode("utf-8", errors="replace")

    @staticmethod
    def _raise_for_qq_error(data: dict[str, Any], action: str) -> None:
        code = data.get("ec", data.get("errcode", data.get("retcode")))
        if code in (None, 0, "0"):
            return
        message = data.get("em") or data.get("errmsg") or data.get("retmsg") or data.get("message")
        if code in (4, 10001, "4", "10001"):
            raise QQAPIError(f"{action} 登录态失效：{message or code}")
        raise QQAPIError(f"{action} 返回错误 {code}：{message or data}")
