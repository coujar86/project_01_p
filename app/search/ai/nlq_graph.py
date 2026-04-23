from datetime import datetime
from functools import lru_cache
from langgraph.graph import StateGraph, START, END
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import interrupt
from langgraph.checkpoint.memory import MemorySaver
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
# ALLOWED_MSGPACK_MODULES = [("app.search.blog_queries", "ParsedAIBlogSearch")]
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
    # logger.debug("========================")
    nlq = state.get("nlq", "").strip()
    if not nlq:
        return {**state, "error": "검색어가 비어 있습니다."}

    current_date = state.get("current_date") or datetime.now()
    return {
        **state,
        "nlq": nlq,
        "current_date": current_date,
        "review_required": False,
        "is_corrected": False,
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
        # logger.debug(f"[HITL] parsed generated: {parsed}")
        return {**state, "parsed": parsed}
    except Exception as e:
        return {**state, "error": f"LLM 파싱 실패: {str(e)}"}


async def validate_parsed_result(state: BlogNLQState) -> BlogNLQState:
    # logger.debug(
    #    f"[HITL] validate_parsed_result start | is_corrected={state.get('is_corrected')}"
    # )
    if state.get("error"):
        return {**state, "review_required": False, "next_action": "end"}

    parsed = state.get("parsed")
    if parsed is None:
        return {
            **state,
            "review_required": False,
            "error": "파싱 결과가 없습니다.",
            "next_action": "end",
        }
    if not parsed.q or not parsed.q.strip():
        return {
            **state,
            "review_required": False,
            "error": "검색어(q) 추출이 실패하였습니다.",
            "next_action": "end",
        }

    if parsed.q.strip().lower() in INVALID_Q_SET:
        return {
            **state,
            "review_required": False,
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
            # logger.debug("[HITL] validation failed -> suggest_revision")
            return {
                **state,
                "review_required": False,
                "error": "시작 날짜가 종료 날짜보다 늦습니다.",
                "next_action": "suggest_revision",
            }

        if filters.date_from and filters.date_from > now:
            logger.error("[HITL] validation failed -> suggest_revision")
            return {
                **state,
                "review_required": False,
                "error": "미래 날짜는 검색할 수 없습니다.",
                "next_action": "suggest_revision",
            }

    if state["is_corrected"]:  # corrected 가 검사된 경우
        # logger.debug(
        #     "[HITL] corrected validated -> back to suggest_revision (for human_review)"
        # )
        return {**state, "next_action": "suggest_revision"}

    # logger.debug("[HITL] validation passed -> execute_search")
    # extract_params 에서 생성된 응답이 바로 검사를 통과한 경우 (revision 불필요)
    return {**state, "next_action": "execute_search"}


async def execute_search(state: BlogNLQState, runtime) -> BlogNLQState:
    # logger.debug("[HITL] execute_search start")
    es = runtime.context.es
    parsed = state.get("parsed")
    page = state.get("page", 1)

    try:
        search_results, total_pages, current_page = await ai_search_blogs_es(
            es=es, parsed=parsed, page=page
        )
        # logger.debug(f"[HITL] search result count: {len(search_results)}")

        return {
            **state,
            "search_results": search_results,
            "total_pages": total_pages,
            "current_page": current_page,
            "review_required": False,
            "error": None,
        }
    except Exception as e:
        return {
            **state,
            "review_required": False,
            "error": f"ES 검색 중 오류 발생: {str(e)}",
        }


async def suggest_revision(state: BlogNLQState) -> BlogNLQState:
    # logger.debug(
    #     f"[HITL] suggest_revision start | is_corrected={state.get('is_corrected')} | revision_count={state.get('revision_count',0)}"
    # )
    parsed = state.get("parsed")
    if parsed is None:
        return {
            **state,
            "review_required": False,
            "error": "교정할 수 있는 parsed가 없습니다.",
            "next_action": "end",
        }

    if state.get("is_corrected"):
        logger.error("[HITL] moving to human_review")
        return {
            **state,
            "review_required": True,
            "next_action": "human_review",
        }

    count = state.get("revision_count", 0)
    # logger.debug(f"[HITL] revision_count: {count}")
    if count >= MAX_REVISION_COUNT:
        return {
            **state,
            "review_required": False,
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
        # logger.debug(f"[HITL] corrected generated: {corrected}")
        # logger.debug("[HITL] corrected -> validate_result")
        return {
            **state,
            "parsed": corrected,
            "review_required": False,
            "is_corrected": True,
            "revision_count": count + 1,
            "error": None,
            "next_action": "validate_result",
        }
    except Exception as e:
        return {
            **state,
            "review_required": False,
            "error": f"조건 교정 실패: {str(e)}",
            "next_action": "end",
        }


async def analyze_search_result(state: BlogNLQState) -> BlogNLQState:
    # logger.debug("[HITL] analyze_search_result start")
    if state.get("error"):
        return {**state, "next_action": "end"}

    search_results = state.get("search_results", [])
    if search_results:
        return {**state, "next_action": "end"}

    # logger.debug("[HITL] search empty -> suggest_revision")
    return {
        **state,
        "error": "검색 결과가 없습니다. 필터 조건을 완화해야 합니다.",
        "next_action": "suggest_revision",
    }


async def human_review(state: BlogNLQState) -> BlogNLQState:
    parsed = state.get("parsed")

    user_decision = interrupt(parsed.model_dump())
    # logger.debug(f"[HITL] human decision: {user_decision}")
    if user_decision == "approve":
        logger.error("[HITL] human approved -> execute_search")
        return {
            **state,
            "review_required": False,
            "is_corrected": False,
            "next_action": "execute_search",
        }
    logger.error("[HITL] human rejected -> end")
    return {  # user_decision == "reject"
        **state,
        "review_required": False,
        "error": "사용자가 수정된 검색 조건을 거절했습니다.",
        "next_action": "end",
    }


def route_after_validation(state: BlogNLQState) -> str:
    next_action = state.get("next_action")
    if next_action == "suggest_revision":
        return "suggest_revision"
    elif next_action == "execute_search":
        return "execute_search"
    return "end"


def route_after_revision(state: BlogNLQState) -> str:
    next_action = state.get("next_action")
    if next_action == "validate_result":
        return "validate_result"
    elif next_action == "human_review":
        return "human_review"
    return "end"  # next_action == "end"


def route_after_review(state: BlogNLQState) -> str:
    if state.get("next_action") == "execute_search":
        return "execute_search"
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
    workflow.add_node("human_review", human_review)

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
        {
            "validate_result": "validate_result",
            "human_review": "human_review",
            "end": END,
        },
    )
    workflow.add_conditional_edges(
        "human_review",
        route_after_review,
        {"execute_search": "execute_search", "end": END},
    )
    workflow.add_conditional_edges(
        "analyze_result",
        route_after_search,
        {"suggest_revision": "suggest_revision", "end": END},
    )

    memory = MemorySaver()

    return workflow.compile(checkpointer=memory)
