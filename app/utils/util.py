from datetime import date, datetime, time
from pathlib import Path
from app.core.config import get_settings

settings = get_settings()


def parse_query_date_start(raw: str | None) -> datetime | None:
    if raw is None or not str(raw).strip():
        return None

    s = str(raw).strip()[:10]
    d = date.fromisoformat(s)
    return datetime.combine(d, time.min)


def parse_query_date_end(raw: str | None) -> datetime | None:
    if raw is None or not str(raw).strip():
        return None

    s = str(raw).strip()[:10]
    d = date.fromisoformat(s)
    return datetime.combine(d, time(23, 59, 59, 999999))


def truncate_text(text: str, limit: int = 150) -> str:
    """텍스트의 길이가 길 경우 생략하고 줄임표를 사용"""
    if len(text) <= limit:
        return text
    return text[:limit] + ".."


def newline_to_br(text: str) -> str:
    """
    html에서는 python의 이스케이프 시퀀스('\n' 등)를 사용할 수 없음
    따라서 줄바꿈을 위해서는 태그 <br>을 사용함
    """
    if text is not None:
        res = text.replace("\n", "<br>")
        return res


def calc_pagination(*, total: int, page: int, per_page: int) -> tuple[int, int]:
    """페이지네이션 계산"""
    total_pages = max(1, (total + per_page - 1) // per_page)
    current_page = max(1, min(page, total_pages))
    return total_pages, current_page


def calc_required_size(*, page: int, per_page: int) -> int:
    """knn을 위한 k값 계산"""
    return page * per_page


def resolve_image_loc(image_loc: str | None) -> str:
    """image_loc이 None인 경우 기본 이미지 경로로 수정"""
    return image_loc or "/static/default/blog_default_v2.jpeg"


def extract_image_ext(image_loc: str | None) -> str | None:
    """
    image_loc 에서 파일 확장자 추출
    resolve_image_loc() 와 함께 사용시 호출 순서 유의. 기본 이미지 경로를 받을 위험 있음
    """
    if not image_loc or "." not in image_loc:
        return None
    return Path(image_loc).suffix[1:].lower()
