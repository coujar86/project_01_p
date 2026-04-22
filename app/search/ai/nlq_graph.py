from datetime import datetime
from functools import lru_cache
from langgraph.graph import StateGraph, START, END
from langgraph.graph.state import CompiledStateGraph
from app.search.ai.nlq_core import (
    BlogNLQContext,
    BlogNLQState,
    get_blog_nlq,
    get_blog_nlq_correction,
)
from app.search.blog_search import ai_search_blogs_es
from app.core.logging import get_logger

logger = get_logger(__name__)
blog_nlq = get_blog_nlq()
blog_nlq_correction = get_blog_nlq_correction()

MAX_REVISION_COUNT = 3
INVALID_Q_SET = {
    "글",
    "게시글",
    "포스트",
    "문서",
    "블로그",
    "posts",
    "post",
    "blogs",
    "blog",
}


async def prepare_prompt_input(state: BlogNLQState) -> BlogNLQState:
    nlq = state.get("nlq", "").strip()
    if not nlq:
        return {**state, "error": "검색어가 비어 있습니다."}

    current_date = state.get("current_date") or datetime.now()
    return {
        **state,
        "nlq": nlq,
        "current_date": current_date,
    }


async def extract_search_params(state: BlogNLQState) -> BlogNLQState:
    if state.get("error"):
        return state

    try:
        nlq = state["nlq"]
        current_date = state["current_date"]
    except KeyError:
        return {**state, "error": "nlq 또는 current_date가 state에 없습니다."}

    try:
        parsed = await blog_nlq.runnable.ainvoke(
            {"nlq": nlq, "current_date": current_date.strftime("%Y-%m-%d %H:%M:%S")}
        )
        # logger.error(f"[AI PARSED] {parsed}")
        return {**state, "parsed": parsed}
    except Exception as e:
        return {**state, "error": f"LLM 파싱 실패: {str(e)}"}


async def validate_parsed_result(state: BlogNLQState) -> BlogNLQState:
    logger.error("[Validate execute]")
    if state.get("error"):
        return {**state, "next_action": "end"}

    parsed = state.get("parsed")
    # logger.error(f"[parsed]: {parsed}")
    if parsed is None:
        return {
            **state,
            "error": "파싱 결과가 없습니다.",
            "next_action": "end",
        }
    if not parsed.q or not parsed.q.strip():
        return {
            **state,
            "error": "검색어(q) 추출이 실패하였습니다.",
            "next_action": "end",
        }

    if parsed.q.strip().lower() in INVALID_Q_SET:
        return {
            **state,
            "error": "검색어가 너무 모호합니다. 주제를 조금 더 구체적으로 입력해 주세요.",
            "next_action": "end",
        }

    now = state["current_date"]
    filters = parsed.filters
    if filters:
        if (
            filters.date_from
            and filters.date_to
            and filters.date_from > filters.date_to
        ):
            return {
                **state,
                "error": "시작 날짜가 종료 날짜보다 늦습니다.",
                "next_action": "suggest_revision",
            }

        if filters.date_from and filters.date_from > now:
            return {
                **state,
                "error": "미래 날짜는 검색할 수 없습니다.",
                "next_action": "suggest_revision",
            }

    return {**state, "next_action": "execute_search"}


async def execute_search(state: BlogNLQState, runtime) -> BlogNLQState:
    es = runtime.context.es
    parsed = state["parsed"]
    page = state["page"]

    try:
        search_results, total_pages, current_page = await ai_search_blogs_es(
            es=es, parsed=parsed, page=page
        )
        logger.error(f"[pages]: {total_pages}, {current_page}")
        # logger.error(f"[RES]: {search_results}")

        return {
            **state,
            "search_results": search_results,
            "total_pages": total_pages,
            "current_page": current_page,
        }
    except Exception as e:
        return {**state, "error": f"ES 검색 중 오류 발생: {str(e)}"}


async def suggest_revision(state: BlogNLQState) -> BlogNLQState:
    parsed = state.get("parsed")
    if parsed is None:
        return {
            **state,
            "error": "교정할 수 있는 parsed가 없습니다.",
            "next_action": "end",
        }

    count = state.get("revision_count", 0)
    if count >= MAX_REVISION_COUNT:
        return {
            **state,
            "error": "parsed 교정 횟수가 초과하였습니다.",
            "next_action": "end",
        }

    try:
        corrected = await blog_nlq_correction.runnable.ainvoke(
            {
                "error": state.get("error", ""),
                "parsed": parsed.model_dump_json(),
                "current_date": state["current_date"].strftime("%Y-%m-%d %H:%M:%S"),
            }
        )

        logger.error(f"[BEFORE]: {parsed}")
        logger.error(f"[AFTER]: {corrected}")
        return {
            **state,
            "parsed": corrected,
            "revision_count": count + 1,
            "error": None,
            "next_action": "validate_result",
        }
    except Exception as e:
        return {**state, "error": f"조건 교정 실패: {str(e)}", "next_action": "end"}


async def analyze_search_result(state: BlogNLQState) -> BlogNLQState:
    if state.get("error"):
        return {**state, "next_action": "end"}

    search_results = state.get("search_results", [])
    if search_results:
        return {**state, "next_action": "end"}

    return {
        **state,
        "error": "검색 결과가 없습니다. 필터 조건을 완화해야 합니다.",
        "next_action": "suggest_revision",
    }


def route_after_validation(state: BlogNLQState) -> str:
    next_action = state.get("next_action")
    if next_action == "suggest_revision":
        return "suggest_revision"
    elif next_action == "execute_search":
        return "execute_search"
    return "end"


def route_after_revision(state: BlogNLQState) -> str:
    if state.get("next_action") == "validate_result":
        return "validate_result"
    return "end"  # next_action == "end"


def route_after_search(state: BlogNLQState) -> str:
    if state.get("next_action") == "suggest_revision":
        return "suggest_revision"
    return "end"  # next_action == "end"


@lru_cache
def get_blog_nlq_graph() -> CompiledStateGraph:
    workflow = StateGraph(BlogNLQState, context_schema=BlogNLQContext)
    workflow.add_node("prepare_input", prepare_prompt_input)
    workflow.add_node("extract_params", extract_search_params)
    workflow.add_node("validate_result", validate_parsed_result)
    workflow.add_node("execute_search", execute_search)
    workflow.add_node("suggest_revision", suggest_revision)
    workflow.add_node("analyze_result", analyze_search_result)

    workflow.add_edge(START, "prepare_input")
    workflow.add_edge("prepare_input", "extract_params")
    workflow.add_edge("extract_params", "validate_result")
    workflow.add_edge("execute_search", "analyze_result")

    workflow.add_conditional_edges(
        "validate_result",
        route_after_validation,
        {
            "suggest_revision": "suggest_revision",
            "execute_search": "execute_search",
            "end": END,
        },
    )
    workflow.add_conditional_edges(
        "suggest_revision",
        route_after_revision,
        {"validate_result": "validate_result", "end": END},
    )
    workflow.add_conditional_edges(
        "analyze_result",
        route_after_search,
        {"suggest_revision": "suggest_revision", "end": END},
    )

    return workflow.compile()
