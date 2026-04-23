from elasticsearch import AsyncElasticsearch
from fastapi import (
    HTTPException,
    Request,
    APIRouter,
    UploadFile,
    File,
    Depends,
    Form,
    Path,
    Query,
    status,
)
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.database import get_db
from app.core.config import get_settings
from app.core.templates import templates
from app.db.schemas import BlogCreate, BlogUpdate
from app.auth.dependencies import get_user_id, get_user_id_optional
from app.core.client import get_es
from app.services.blog import BlogService
from app.utils.timer import ElapsedTime
import uuid

settings = get_settings()
router = APIRouter(prefix="/blogs", tags=["blogs"])


@router.get("/")
async def get_all_blogs(
    request: Request,
    page: int = Query(1, ge=1, description="페이지 번호"),
    db: AsyncSession = Depends(get_db),
    user_id: int | None = Depends(get_user_id_optional),
):
    total_pages, current_page = await BlogService.get_pagination(
        db, page=page, per_page=settings.BLOGS_PER_PAGE
    )
    blogs = await BlogService.get_all_blogs(
        db, page=current_page, per_page=settings.BLOGS_PER_PAGE
    )

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "session_user": user_id,
            "blogs": blogs,
            "current_page": current_page,
            "total_pages": total_pages,
            "search_query": "",
            "search_type": "title_content",
            "search_mode": False,
            "ai_search_mode": False,
            "nlq": "",
            "image_ext": None,
            "date_from": "",
            "date_to": "",
        },
    )


@router.get("/show/{id}")
async def get_blog_by_id(
    request: Request,
    id: int = Path(..., ge=1, description="조회할 블로그 글 ID"),
    db: AsyncSession = Depends(get_db),
    user_id: int | None = Depends(get_user_id_optional),
):
    blog = await BlogService.get_blog_by_id(db, id=id)
    is_valid_auth = bool(user_id)

    return templates.TemplateResponse(
        request=request,
        name="show_blog.html",
        context={
            "blog": blog,
            "user_id": user_id,
            "is_valid_auth": is_valid_auth,
        },
    )


@router.get("/search")
async def search_blogs(
    request: Request,
    q: str = Query("", description="검색어"),
    search_type: str = Query(
        "title_content", enum=["title_content", "author"], description="검색 타입"
    ),
    image_ext: str | None = Query(
        None, enum=["jpg", "jpeg", "png", "none"], description="ES 필터 옵션"
    ),
    date_from: str | None = Query(None, description="ES 필터 옵션"),
    date_to: str | None = Query(None, description="ES 필터 옵션"),
    page: int = Query(1, ge=1, description="페이지 번호"),
    user_id: int | None = Depends(get_user_id_optional),
    es: AsyncElasticsearch = Depends(get_es),
):
    if not q or not q.strip():
        return RedirectResponse("/blogs/", status_code=status.HTTP_303_SEE_OTHER)
    q = q.strip()

    try:
        async with ElapsedTime("router.blog.search_blogs"):
            blogs, total_pages, current_page = await BlogService.search_blogs(
                es,
                q=q,
                search_type=search_type,
                image_ext=image_ext,
                date_from=date_from,
                date_to=date_to,
                page=page,
            )
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "user_id": user_id,
                "blogs": blogs,
                "current_page": current_page,
                "total_pages": total_pages,
                "search_query": q,
                "search_type": search_type,
                "image_ext": image_ext,
                "date_from": date_from or "",
                "date_to": date_to or "",
                "search_mode": True,
                "ai_search_mode": False,
                "nlq": "",
            },
        )
    except HTTPException:
        raise
    except Exception:
        return RedirectResponse("/blogs/", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/ai-search")
async def ai_search_blogs(
    request: Request,
    nlq: str = Query("", description="자연어 검색어"),
    page: int = Query(1, ge=1, description="페이지 번호"),
    user_id: int | None = Depends(get_user_id_optional),
    es=Depends(get_es),
):
    if not nlq or not nlq.strip():
        return RedirectResponse("/blogs/", status_code=status.HTTP_303_SEE_OTHER)
    nlq = nlq.strip()

    try:
        thread_id = str(uuid.uuid4())
        result = await BlogService.ai_search_blogs(
            es,
            nlq=nlq,
            page=page,
            thread_id=thread_id,
        )

        if result.get("review_required"):
            return templates.TemplateResponse(
                request=request,
                name="human_review.html",
                context={
                    "user_id": user_id,
                    "thread_id": result.get("thread_id"),
                    "review_payload": result.get("review_payload"),
                    "nlq": nlq,
                    "page": page,
                },
            )

        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "user_id": user_id,
                "blogs": result.get("search_results", []),
                "current_page": result.get("current_page", page),
                "total_pages": result.get("total_pages", 0),
                "search_query": "",
                "nlq": nlq,
                "search_type": "title_content",
                "image_ext": None,
                "date_from": "",
                "date_to": "",
                "search_mode": True,
                "ai_search_mode": True,
            },
        )
    except HTTPException:
        raise
    except Exception:
        return RedirectResponse("/blogs/", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/ai-search/review")
async def review_ai_search_blogs(
    request: Request,
    thread_id: str = Form(...),
    human_decision: str = Form(...),
    nlq: str = Form(""),
    page: int = Form(1),
    user_id: int | None = Depends(get_user_id_optional),
    es=Depends(get_es),
):
    try:
        result = await BlogService.resume_ai_search_blogs(
            es,
            human_decision=human_decision,
            thread_id=thread_id,
            page=page,
        )

        if result.get("review_required"):
            return templates.TemplateResponse(
                request=request,
                name="human_review.html",
                context={
                    "user_id": user_id,
                    "thread_id": result.get("thread_id"),
                    "review_payload": result.get("review_payload"),
                    "nlq": nlq,
                    "page": page,
                },
            )

        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "user_id": user_id,
                "blogs": result.get("search_results", []),
                "current_page": result.get("current_page", page),
                "total_pages": result.get("total_pages", 0),
                "search_query": "",
                "nlq": nlq,
                "search_type": "title_content",
                "image_ext": None,
                "date_from": "",
                "date_to": "",
                "search_mode": True,
                "ai_search_mode": True,
            },
        )
    except HTTPException:
        raise
    except Exception:
        return RedirectResponse("/blogs/", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/new")
def create_blog_ui(
    request: Request,
    user_id: int = Depends(get_user_id),
):
    return templates.TemplateResponse(
        request=request, name="new_blog.html", context={"user_id": user_id}
    )


@router.post("/new")
async def create_blog(
    title=Form(...),
    content=Form(...),
    imagefile: UploadFile | None = File(None),
    user_id: int = Depends(get_user_id),
    db: AsyncSession = Depends(get_db),
):
    author_id = user_id
    image_loc = await BlogService.upload_file(author_id=author_id, imagefile=imagefile)
    await BlogService.create_blog(
        db,
        BlogCreate(
            title=title, author_id=author_id, content=content, image_loc=image_loc
        ),
    )
    return RedirectResponse("/blogs", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/modify/{id}")
async def update_blog_ui(
    request: Request,
    id: int = Path(..., ge=1, description="수정할 블로그 글 ID"),
    user_id: int = Depends(get_user_id),
    db: AsyncSession = Depends(get_db),
):
    blog = await BlogService.get_blog_by_id(db, id=id)
    return templates.TemplateResponse(
        request=request,
        name="modify_blog.html",
        context={"blog": blog, "user_id": user_id},
    )


@router.put("/modify/{id}")
async def update_blog(
    id: int = Path(..., ge=1, description="수정할 블로그 글 ID"),
    title=Form(...),
    content=Form(...),
    imagefile: UploadFile | None = File(None),
    user_id: int = Depends(get_user_id),
    db: AsyncSession = Depends(get_db),
):
    blog = await BlogService.get_blog_by_id(db, id=id)
    image_loc = await BlogService.upload_file(
        author_id=blog.author_id, imagefile=imagefile
    )

    blog_data = BlogUpdate(
        id=id,
        title=title,
        content=content,
        image_loc=image_loc,
        author_id=blog.author_id,
    )
    await BlogService.update_blog(
        db,
        user_id=user_id,
        image_loc_old=blog.image_loc,
        blog_data=blog_data,
    )
    return RedirectResponse(f"/blogs/show/{id}", status_code=status.HTTP_303_SEE_OTHER)


@router.delete("/delete/{id}")
async def delete_blog(
    id: int = Path(..., ge=1, description="삭제할 블로그 글 ID"),
    user_id: int = Depends(get_user_id),
    db: AsyncSession = Depends(get_db),
):
    await BlogService.delete_blog(db, user_id=user_id, id=id)
    return JSONResponse(
        content="메시지가 삭제되었습니다", status_code=status.HTTP_200_OK
    )
