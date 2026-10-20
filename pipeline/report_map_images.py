"""PDF에 넣을 지도 타일만 같은 출처의 이미지로 전달한다."""
from urllib.parse import urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


MAX_IMAGE_BYTES = 2 * 1024 * 1024
IMAGE_PATHS = {
    "mts.kakaocdn.net": "/api/v1/tile/",
    **{f"mts{i}.kakaocdn.net": "/api/v1/tile/" for i in range(4)},
    "map.daumcdn.net": "/map_2d/",
    **{f"map{i}.daumcdn.net": "/map_2d/" for i in range(5)},
    "t1.daumcdn.net": "/mapjsapi/",
    "t1.kakaocdn.net": "/mapjsapi/",
    "tile.openstreetmap.org": "/",
}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch_image(url):
    parts = urlsplit(url)
    prefix = IMAGE_PATHS.get(parts.hostname)
    if (parts.scheme not in {"http", "https"} or not prefix
            or parts.username or parts.password or parts.port is not None
            or parts.query or parts.fragment or not parts.path.startswith(prefix)
            or any(value in parts.path.lower() for value in ("..", "%", "\\"))
            or not parts.path.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp"))):
        raise ValueError("허용된 지도 이미지가 아니에요.")
    # HTTP로 표시된 카카오 타일도 서버에서는 HTTPS로만 읽는다. 리다이렉트는 금지한다.
    secure_url = urlunsplit(("https", parts.hostname, parts.path, "", ""))
    request = Request(secure_url, headers={"User-Agent": "Zippick-Report/1.0"})
    with build_opener(NoRedirect()).open(request, timeout=10) as response:
        mime = response.headers.get_content_type()
        if mime not in {"image/png", "image/jpeg", "image/gif", "image/webp"}:
            raise ValueError("지도 이미지 형식을 확인하지 못했어요.")
        body = response.read(MAX_IMAGE_BYTES + 1)
        if not body or len(body) > MAX_IMAGE_BYTES:
            raise ValueError("지도 이미지 크기를 확인하지 못했어요.")
        return body, mime
