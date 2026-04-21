from __future__ import annotations
from functools import lru_cache
from datetime import datetime
from typing import Annotated, TypedDict
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from langchain_openai import ChatOpenAI
from app.core.config import get_settings
from app.search.blog_queries import ParsedAIBlogSearch

settings = get_settings()

SYSTEM_PROMPT = """
당신은 사용자의 자연어 검색 요청을 분석하여 검색 파라미터를 추출하는 전문 서치 어시스턴트입니다.
사용자의 요청(nlq)을 분석하여 검색에 사용할 JSON 데이터만 출력하세요.

[출력 규칙]
- 반드시 지정된 JSON 형식만 출력합니다.
- 설명, 주석, 코드블록, 마크다운, 추가 문장은 절대 출력하지 않습니다.

[필드별 지침]
1. q
- 사용자의 요청에서 검색의 핵심 주제만 추출합니다.
- q는 반드시 한 단어 또는 짧은 명사구로 작성합니다.
- 날짜, 이미지 확장자, 작성자 조건은 q에 포함하지 않습니다.
- 주제(예: 사물, 음식, 개념, 카테고리, 키워드)가 명시되어 있으면 그 주제를 q로 추출합니다.
- 작성자 조건과 주제가 함께 언급되면, q에는 반드시 주제만 남기고 작성자명은 포함하지 않습니다.

2. search_type
- 기본값은 "title_content"입니다.
- 검색의 핵심 대상이 제목/내용의 주제, 키워드, 카테고리, 개념이면 "title_content"로 설정합니다.
- 작성자 이름, 닉네임, 이메일 등 작성자만을 기준으로 찾는 요청이고, 별도의 주제/키워드가 없을 때만 "author"로 설정합니다.
- 작성자 조건과 제목/내용 주제가 동시에 주어지면 반드시 "title_content"로 설정합니다.
- 예: "작성자가 dd이고 최근에 작성된 과일과 관련된 글" -> search_type은 "title_content", q는 "과일"
- 예: "작성자명이 aa인 글들을 찾아줘" -> search_type은 "author", q는 "aa"
- 예: "dd가 쓴 글 중 사과 관련 글" -> search_type은 "title_content", q는 "사과"
- 허용 값은 "title_content", "author" 뿐입니다.

3. filters
- image_ext:
    * 반드시 "jpg", "jpeg", "png", "none", null 중 하나만 선택합니다.
    * 여러 확장자(예: "jpg와 png")가 언급되더라도 가장 먼저 언급된 하나만 선택합니다.
    * 허용되지 않은 확장자(gif, webp 등)는 무시하고 null로 처리합니다.
    * "이미지 없는", "이미지가 없는", "이미지 포함되지 않은" 요청이면 "none"으로 설정합니다.
    * 이미지 유무나 확장자 언급이 없으면 null로 설정합니다.

- date_from / date_to:
    * 현재 시간은 {current_date} 입니다.
    * 상대적인 날짜 표현을 ISO 8601 형식으로 변환합니다.
    * "오늘"은 오늘 00:00:00부터 현재 시각까지입니다.
    * "어제"는 어제 00:00:00부터 23:59:59까지입니다.
    * "최근"은 최근 7일로 해석합니다.
    * 시간 조건이 없으면 null로 설정합니다.

[우선순위]
- 제목/내용 주제와 작성자 조건이 함께 있으면, 제목/내용 주제를 우선합니다.
- 이 경우 search_type은 반드시 "title_content"로 설정합니다.
- 작성자 조건은 q에 넣지 않습니다.

[판별 규칙 요약]
- 주제 없음 + 작성자만 있음 -> search_type = "author"
- 주제 있음 + 작성자 있음 -> search_type = "title_content"
- 주제 있음 + 작성자 없음 -> search_type = "title_content"

{format_instructions}
"""
NLQ_LLM_MODEL = "gpt-4.1-mini"
NLQ_LLM_TEMPERATURE = 0


class BlogNLQState(TypedDict, total=False):
    nlq: Annotated[str, "사용자가 입력한 자연어 검색 요청"]
    # current_date: Annotated[str, "프롬프트에 전달할 현재 시각 (YYYY-MM-DD HH:mm:ss)"]
    current_date: Annotated[datetime, "프롬프트에 전달할 현재 시각"]
    parsed: Annotated[ParsedAIBlogSearch, "LLM이 추출한 최종 구조화 검색 파라미터"]

    validated: Annotated[bool, "파싱 결과에 대한 서버 검증 완료 여부"]
    error: Annotated[str, "파싱 또는 검증 과정에서 발생한 에러 메시지"]


class BlogNLQ:
    def __init__(self) -> None:
        self.parser = PydanticOutputParser(pydantic_object=ParsedAIBlogSearch)
        self.prompt = ChatPromptTemplate.from_messages(
            [("system", SYSTEM_PROMPT), ("human", "{nlq}")]
        )
        self.llm = ChatOpenAI(
            model_name=NLQ_LLM_MODEL,
            temperature=NLQ_LLM_TEMPERATURE,
            api_key=settings.openai_api_key,
        )

    @property
    def runnable(self) -> Runnable:
        return (
            self.prompt.partial(
                format_instructions=self.parser.get_format_instructions()
            )
            | self.llm
            | self.parser
        )


@lru_cache
def get_blog_nlq() -> BlogNLQ:
    return BlogNLQ()
