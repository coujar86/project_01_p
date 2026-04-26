from datetime import datetime
from functools import lru_cache
from langgraph.graph import StateGraph, START, END
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import interrupt
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
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


MAX_REVISION_COUNT = 4
ALLOWED_MSGPACK_MODULES = [("app.search.blog_queries", "ParsedAIBlogSearch")]
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

# python -m app.worker.outbox_processor
# uvicorn main:app --port=8080 --reload

# 4월 30일을 시작 시점(date_from)으로 하고 4월 25일을 종료 시점(date_to)로 하고, 과일 주제의 글을 찾아줘


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
    # 정상적인 API 호출의 경우 라우터에서 방어됨
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
    #     f"[HITL] validate_parsed_result start | is_corrected={state.get('is_corrected')}"
    # )

    # 초기 오류(nlq 없음), LLM API 오류, LLM 출력 파싱 오류(image_ext, search_type)
    # suggest_revision에서 validate_result으로 올 때 반드시 error를 None으로 설정해야함
    if state.get("error"):
        return {**state, "review_required": False, "next_action": "end"}

    # extract_params에서 생성된 parsed(최초 생성)가 검증 실패 시 suggest_revison으로 보냄
    # is_corrected를 확인하여 suggest_revision에서 생성된 교정 쿼리의 경우
    # 검증 성공 시: suggest_revision 으로 가지만 is_corrected=True에 의해 재교정 없이 human_review로 넘어감
    # 검증 실패 시: suggest_revision 에서 재교정 (이렇게 하려면 suggest_revision으로 가는 실패 루트는 is_corrected=False 처리)

    # 검증 1: 검색어(q)를 추출했는지
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

    # 검증 2: 검색어(q)가 모호한 경우, 현재 로직에서는 이를 파라미터 추출 실패로 간주 (적절한 q 추출을 할 수 없기 때문)
    if parsed.q.strip().lower() in INVALID_Q_SET:
        return {
            **state,
            "review_required": False,
            "error": "검색어가 너무 모호합니다. 주제를 조금 더 구체적으로 입력해 주세요.",
            "next_action": "end",
        }

    # 검증 3: date_from과 date_to가 유효한 범위인지 (순서가 적절한지, date_from이 현재 시점보다 과거인지)
    now = state["current_date"]
    filters = parsed.filters

    # TEST CODE, 자율적 수정 테스트
    # count = state.get("revision_count", 0)
    # if count < 3 and filters:
    #     logger.error(f"[VALIDATE] force failed filter on first revision: count={count}")
    #     logger.error(f"[BEFORE]: {filters.date_from} ~ {filters.date_to}")
    #     failed_filter = {
    #         "date_from": datetime(2026, 4, 30, 0, 0, 0),
    #         "date_to": datetime(2026, 4, 27, 23, 59, 59),
    #     }
    #     filters.date_from = failed_filter["date_from"]
    #     filters.date_to = failed_filter["date_to"]
    #     logger.error(f"[AFTER]: {filters.date_from} ~ {filters.date_to}")

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
                "is_corrected": False,
                "error": "시작 날짜가 종료 날짜보다 늦습니다.",
                "next_action": "suggest_revision",
            }

        if filters.date_from and filters.date_from > now:
            # logger.debug("[HITL] validation failed -> suggest_revision")
            return {
                **state,
                "review_required": False,
                "is_corrected": False,
                "error": "미래 날짜는 검색할 수 없습니다.",
                "next_action": "suggest_revision",
            }

    # 재교정된 쿼리가 검증을 통과함, is_corrected=True를 유지
    if state["is_corrected"]:
        # logger.debug(
        #     "[HITL] corrected validated -> back to suggest_revision (for human_review)"
        # )
        return {**state, "next_action": "suggest_revision"}

    # extract_params에서 생성된 parsed가 바로 검증을 통과한 경우 (revision 불필요)
    # logger.debug("[HITL] validation passed -> execute_search")
    return {**state, "next_action": "execute_search"}


async def execute_search(state: BlogNLQState, runtime) -> BlogNLQState:
    # logger.debug("[HITL] execute_search start")
    es = runtime.context.es
    parsed = state.get("parsed")
    page = state.get("page", 1)

    # 검증을 통과한 parsed 및 page를 사용하여, ES 쿼리 생성 및 실제 검색 수행
    try:
        search_results, total_pages, current_page = await ai_search_blogs_es(
            es=es, parsed=parsed, page=page
        )
        # logger.debug(f"[HITL] search result count: {len(search_results)}")
        # 검색 성공 시 결과를 저장 (search_results, total_pages, current_page)
        return {
            **state,
            "search_results": search_results,
            "total_pages": total_pages,
            "current_page": current_page,
            "review_required": False,
            "error": None,
        }
    # 검색 과정에서 오류 발생 (ES 에러)
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
    # 방어적인 코드
    parsed = state.get("parsed")
    if parsed is None:
        return {
            **state,
            "review_required": False,
            "error": "교정할 수 있는 parsed가 없습니다.",
            "next_action": "end",
        }

    # 재교정된 쿼리가 검증을 통과한 경우, human_review로 이동. 검증이 실패한 경우 is_corrected=False일 것이므로 재교정 시도
    if state.get("is_corrected"):
        logger.error("[HITL] moving to human_review")
        return {
            **state,
            "review_required": True,
            "next_action": "human_review",
        }

    # MAX_REVISION_COUNT만큼 suggest_revision 아래 코드를 실행하는 것을 허용함
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
    # logger.error("[HITL] analyze_search_result start")
    # ES 에러의 경우 재교정하지 않음. 즉시 END
    if state.get("error"):
        return {**state, "next_action": "end"}

    search_results = state.get("search_results", [])
    if search_results:  # 검색 결과가 있을 경우 END (서비스 로직에서 나머지 처리)
        return {**state, "next_action": "end"}
    # TEST CODE
    # else:
    #     logger.error("[검색 결과 없음]")
    #     return {**state, "next_action": "end"}

    # 검색 결과가 없을 경우: 교정 시도. 현재 로직에서는 필터 조건 완화만 시도함
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
    # logger.debug("[HITL] human rejected -> end")
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

    memory = MemorySaver(
        serde=JsonPlusSerializer(allowed_msgpack_modules=ALLOWED_MSGPACK_MODULES)
    )

    return workflow.compile(checkpointer=memory)
