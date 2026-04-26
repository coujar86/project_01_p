### Project_01 ###

# Elasticsearch 도입
엔드포인트: "/blogs/search"
- blog_queries.py: 검색 전용 스키마 정의 및 쿼리 정의 함수
- blog_search.py: 검색 수행 로직 (일반 검색, 자연어 검색 모두 포함)
- blog_sync.py: 문서 생성 및 임베딩 함수, ES에 대한 요청 함수
- index.py: 검색 인덱스 정의

outbox에서 이벤트 처리 (ES 요청 시도)


# LangGraph 파이프라인
엔드포인트: "blogs/ai-search", "blogs/ai-search/review"
- app/search/ai/nlq_core.py: GraphState 및 chain 정의
- app/search/ai/nlq_graph.py: 전체 그래프 로직

app/services/blog.py 에서 ai_search_blogs(), resume_ai_search_blogs()


# Outbox 패턴
- app/worker/outbox_processor.py
- app/db/crud/outbox.py
- app/db/models/outbox.py

서비스 로직에서 blogs 테이블 쓰기와 단일 트랜젝션으로 묶음
app/services/blog.py 에서 create_blog(), update_blog(), delete_blog()
