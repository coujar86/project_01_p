from datetime import datetime
from functools import lru_cache
from langgraph.graph import StateGraph, START, END
from langgraph.graph.state import CompiledStateGraph
from app.search.ai.nlq_core import BlogNLQState, get_blog_nlq
from app.core.logging import get_logger

logger = get_logger(__name__)
blog_nlq = get_blog_nlq()

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
        return {"error": "검색어가 비어 있습니다."}

    current_date = state.get("current_date") or datetime.now()
    return {
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
        logger.error(f"[AI PARSED] {parsed}")
        return {**state, "parsed": parsed}
    except Exception as e:
        return {**state, "error": f"LLM 파싱 실패: {str(e)}"}


async def validate_parsed_result(state: BlogNLQState) -> BlogNLQState:
    if state.get("error"):
        return {**state, "validated": False}

    parsed = state.get("parsed")
    if parsed is None:
        return {
            **state,
            "error": "파싱 결과가 없습니다.",
            "validated": False,
        }
    if not parsed.q or not parsed.q.strip():
        return {
            **state,
            "error": "검색어(q) 추출이 실패하였습니다.",
            "validated": False,
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
                "validated": False,
            }

        if filters.date_from and filters.date_from > now:
            return {
                **state,
                "error": "미래 날짜는 검색할 수 없습니다.",
                "validated": False,
            }

    if parsed.q.strip().lower() in INVALID_Q_SET:
        return {
            **state,
            "error": "검색어가 너무 모호합니다. 주제를 조금 더 구체적으로 입력해 주세요.",
            "validated": False,
        }

    return {**state, "validated": True}


@lru_cache
def get_blog_nlq_graph() -> CompiledStateGraph:
    workflow = StateGraph(BlogNLQState)

    workflow.add_node("prepare_input", prepare_prompt_input)
    workflow.add_node("extract_params", extract_search_params)
    workflow.add_node("validate_result", validate_parsed_result)

    workflow.add_edge(START, "prepare_input")
    workflow.add_edge("prepare_input", "extract_params")
    workflow.add_edge("extract_params", "validate_result")
    workflow.add_edge("validate_result", END)
    return workflow.compile()
