from __future__ import annotations

from http.cookies import SimpleCookie


REQUIRED_COOKIES = ("skey", "p_skey", "p_uin")


def parse_cookie_header(cookie_header: str) -> dict[str, str]:
    """解析浏览器复制出来的 Cookie header。"""
    cookie = SimpleCookie()
    cookie.load(cookie_header or "")
    return {key: morsel.value for key, morsel in cookie.items()}


def cookie_header_from_mapping(cookies: dict[str, str]) -> str:
    return "; ".join(f"{key}={value}" for key, value in cookies.items() if value)


def missing_required_cookies(cookies: dict[str, str]) -> list[str]:
    return [name for name in REQUIRED_COOKIES if not cookies.get(name)]


def mask_secret(value: str, keep: int = 3) -> str:
    if not value:
        return "<空>"
    if len(value) <= keep * 2:
        return value[0] + "***"
    return f"{value[:keep]}***{value[-keep:]}"


def mask_cookie_header(cookie_header: str) -> str:
    cookies = parse_cookie_header(cookie_header)
    return "; ".join(f"{key}={mask_secret(value)}" for key, value in cookies.items())


def _js_to_int32(value: int) -> int:
    value &= 0xFFFFFFFF
    return value if value < 0x80000000 else value - 0x100000000


def _js_left_shift(value: int, bits: int) -> int:
    return _js_to_int32(_js_to_int32(value) << bits)


def qq_gtk(skey: str) -> str:
    """复刻 QQ 前端的 skey -> bkn/g_tk 计算。"""
    hash_value = 5381
    for char in skey or "":
        hash_value += _js_left_shift(hash_value, 5) + ord(char)
    return str(_js_to_int32(hash_value) & 0x7FFFFFFF)
