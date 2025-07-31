from fastapi import FastAPI, HTTPException, Query
import time
from opensearchpy import OpenSearch, RequestsHttpConnection
from opensearchpy import AWSV4SignerAuth
from dotenv import load_dotenv
import os
import boto3
from openai import OpenAI
from typing import List, Optional
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import logging
import json
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
import asyncio  # 비동기 작업을 위한 asyncio
from openai import AsyncOpenAI
import datetime
# properties.py에서 region 및 host 값 가져오기
from common.properties import region, host1, host2  # properties.py 파일의 내용을 import
import redis.asyncio as aioredis


# 환경 변수 로드
load_dotenv()

# 로그 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# # 환경 변수에서 API 키 가져오기
# api_key = os.environ.get("OPENAI_API_KEY")

# if not api_key:
#     raise ValueError("OPENAI_API_KEY 환경 변수가 설정되지 않았습니다!")

# 환경 변수에서 API 키 및 인증 정보 가져오기
openai_api_key = os.getenv("OPENAI_API_KEY")
master_username = os.getenv("MASTER_USERNAME")
master_password = os.getenv("MASTER_PASSWORD")

# OpenAI 클라이언트 초기화
client = OpenAI(api_key=openai_api_key)
client = AsyncOpenAI(api_key=openai_api_key)


# OpenAI 및 OpenSearch 클라이언트 설정
# region = 'us-east-1'
# host = 'search-store-manual-oooooooooooo.aos.us-east-1.on.aws'
auth = AWSV4SignerAuth(boto3.Session().get_credentials(), region)


opensearch_client = OpenSearch(
    hosts=[{'host': host1, 'port': 443}],
    http_auth=(master_username, master_password),
    use_ssl=True,
    verify_certs=True,
    connection_class=RequestsHttpConnection
)


# FastAPI 앱 생성
app = FastAPI()

# CORS 설정 추가
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 모든 출처 허용. 보안상 필요한 도메인으로 제한하는 것이 좋음
    allow_credentials=True,
    allow_methods=["*"],  # 모든 HTTP 메서드 허용
    allow_headers=["*"],  # 모든 HTTP 헤더 허용
)

# # Redis 연결 설정
# REDIS_HOST = "127.0.0.1"  # Stunnel을 통해 연결하는 로컬 포트
# REDIS_PORT = 6380  # Stunnel이 수신하는 포트

# redis = None  # Redis 인스턴스를 글로벌 변수로 선언

# async def init_redis():
#     global redis
#     redis = aioredis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
#     logger.info("Redis 연결 성공!")

# # FastAPI 앱 시작 시 Redis 초기화
# @app.on_event("startup")
# async def startup():
#     await init_redis()

# # FastAPI 앱 종료 시 Redis 연결 종료
# @app.on_event("shutdown")
# async def shutdown():
#     await redis.close()    


# Pydantic 모델 정의
class QuestionRequest(BaseModel):
    question: str

class RecipeResponse(BaseModel):
    menuName: Optional[str] = None
    ingredients: Optional[List[dict]] = None
    cookingInstructions: Optional[List[str]] = None


# OpenSearch 검색 함수
async def search_opensearch(indices, query, top_k=5):
    start_time = time.time()

    filtered_query = " ".join([word for word in query.split() if word != "방법"])


    # # Redis 키 생성 (인덱스와 쿼리를 기반으로 캐싱)
    # redis_key = f"search:{','.join(indices)}:{query}"
    # logger.info(f"Redis Key 확인: {redis_key}")


    # # Redis 캐시에서 검색
    # cached_data = await redis.get(redis_key)
    # if cached_data:
    #     logger.info(f"Redis 캐시 사용: {query}")
    #     return cached_data  # Redis 캐시 데이터 반환

    try:
        # OpenSearch에서 여러 인덱스를 검색
        response = opensearch_client.search(
            index=",".join(indices),  # 여러 인덱스를 쉼표로 연결
            body={
                "query": {
                    "multi_match": {
                        "query": filtered_query,
                        "fields": [
                            "구분",
                            "C_소제목",
                            "C_소제목_요약",
                            "주제_1",
                            "내용1",
                            "주제_2",
                            "내용2",
                            "주제_3",
                            "내용3",
                            "주제_4",
                            "내용4",
                            "주제_5",
                            "내용5",
                            "주제_6",
                            "내용6",
                            "비디오링크",
                            "메뉴명^2",  # 추가 필드 예시
                            "조리순서",
                            "준비사항",
                            "이미지링크"
                        ]
                    }
                },
                "size": top_k,
            },
        )

        elapsed_time = time.time() - start_time
        logger.info(f"OpenSearch 작업 시간: {elapsed_time:.2f}초")

        contexts = []
        for hit in response["hits"]["hits"]:
            source = hit["_source"]
            # JSON 전체를 문자열로 변환하여 저장
            source_json = json.dumps(source, ensure_ascii=False, indent=2)
            contexts.append(source_json)

        # 결과를 합쳐서 반환
        full_context = "\n\n".join(contexts)
        # print(f"컨텍스트 확인:{full_context}")

        # logger.info(f"Redis 저장 테스트: key={redis_key}, value={full_context}")

        # # Redis에 결과 캐싱 (TTL: 10분)
        # await redis.setex(redis_key, 600, full_context)
        # logger.info(f"Redis 캐시에 저장 완료: {query}")

        return full_context

    except Exception as e:
        logger.error(f"OpenSearch 검색 오류: {e}")
        return f"Error: {e}", 0

# GPT LLM 응답 생성 함수
async def generate_llm_response(context, question, model="gpt-4o", max_tokens=1024):
    start_time = time.time()
    try:

        # 메시지 구성
        messages = [
            {"role": "system", "content": "You are a helpful assistant. Prioritize including the '링크' field in your response if it exists"}
        ]

        # 컨텍스트가 있을 때 JSON 구조 요청
        if context:
            messages.append(
                {"role": "system", "content": "When a context is provided, respond strictly"}
            )

        if context:
            messages.append(
                {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {question}"}
            )
        else:
            messages.append(
                {"role": "user", "content": f"""
                    Question: {question}

                    제공된 정보로 답변하기 어려운 경우, 사용자에게 정중히 안내하고
                    추가적인 문의는 ooooo@gmail.kr로 연락해달라고 요청해주세요.
                """}
            )

        # OpenAI 스트림 호출
        async with client.chat.completions.stream(
            model=model,
            messages=messages,
            max_tokens=max_tokens
        ) as stream:
            async for chunk in stream:
                # delta가 None일 수 있으므로 안전하게 접근
                delta = chunk.choices[0].delta if chunk.choices and chunk.choices[0].delta else {}
                chunk_content = delta.get("content", "")

                if chunk_content:
                    yield json.dumps({"status": "processing", "data": chunk_content}, ensure_ascii=False) + "\n"

        # 스트림 종료
        yield json.dumps({"status": "complete", "data": "Stream finished"}, ensure_ascii=False) + "\n"

    except Exception as e:
        yield json.dumps({"status": "error", "data": str(e)}, ensure_ascii=False) + "\n"

# 질문과 응답 데이터를 저장하는 함수
def save_to_opensearch(index_name, question, response, timestamp):
    """
    OpenSearch에 질문과 응답 데이터를 저장하는 함수
    """
    try:
        # 저장할 문서
        document = {
            "question": question,
            "response": response,
            "timestamp": timestamp,
        }

        # OpenSearch에 문서 저장
        result = opensearch_client.index(index=index_name, body=document)
        logger.info(f"데이터 저장 완료: {result['_id']}")
        return result
    except Exception as e:
        logger.error(f"OpenSearch 저장 오류: {e}")
        return None

# FastAPI 엔드포인트 생성
@app.get("/simplesearch", response_model=None)  # response_model 제거, 스트리밍 반환
async def search_and_respond(question: str, indices: Optional[List[str]] = Query(["recipe_index", "nori_vol6_index_v3"])):
    now = datetime.datetime.now() 
    timestamp_millis = now.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    print(timestamp_millis)

    try:
        # -------------------------
        # 1) OpenSearch에서 데이터 검색
        # -------------------------
        context = await search_opensearch(indices, query=question, top_k=50)
        print("가져온 컨텍스트:", context)

        if "Error" in context:
            raise HTTPException(status_code=500, detail=context)

        # -------------------------
        # 2) SSE용 내부 함수 정의
        # -------------------------
        async def stream_openai_response(context, question):
            id_counter = 1  # SSE 메시지 id 카운터
            all_yielded_data = []  # 전체 데이터를 저장할 리스트

            # # NO_CONTEXT 메시지 처리
            # if not context:
            #     no_context_message = "##NO_CONTEXT##"
            #     yield (
            #         f"id: {id_counter}\n"
            #         f"event: message\n"
            #         f"data: {json.dumps({'status': 'processing', 'data': no_context_message}, ensure_ascii=False)}\n\n"
            #     )
            #     id_counter += 1

            

            # 메시지 구성
            if context:

                # Few-shot 예제 정의
                few_shot_examples = [
                    {
                        "role": "user",
                        "content": "시그니쳐 플래터 2-3인분 레시피 알려줘"
                    },
                    {
                        "role": "assistant",
                        "content": json.dumps({
                            "menuName":[0],
                            "imageLink":[1],
                            "ingredients":[2],
                            "prepareBowl":[3],
                            "prepareMI":[4],
                            "cookingInstructions":[5]
                        }, ensure_ascii=False, separators=(',', ':')) 
                        + 
                        json.dumps({
                            "data": [
                                "BFT 시그니쳐플래터(2~3인용)|이미지링크:https://bft-menu-images.s3.us-east-1.amazonaws.com/bft-images/webp-image/BFT+%EC%8B%9C%EA%B7%B8%EB%8B%88%EC%B3%90+%ED%94%8C%EB%9E%98%ED%84%B0.webp|1. 폭립 250g^2. 통삼겹살 100g^3. 치킨 150g^4. 절단옥수수 2개^5. 바베큐소스 40g^6. 레몬 20g^7. 양상치 80g^8. 볶은양파 50g^9. 마늘후레이크 10g^10. 소시지 2개^11. 케이준후라이 100g^12. 핫도그번 2개|홀 서비스 용기: 철판 쟁반 (31x24 cm)^배달 용기: 각 메뉴별로 햄버거 용기에 나눠 담은 포장 (폭립은 덮밥용기)^플래터 메뉴는 모두 비닐장갑, 컷팅 나이프, 포크 인원수에 맞춰 제공|가라아게 준비 - 튀김기 시간: 초벌 3분 30초 / 주문시 재벌 30초^소시지 준비 - 튀김기 시간: 30초^케이준후라이 준비 - 튀김기 시간: 3분 30초|조리순서:^1. 폭립 (250g): 자연해동 후 냉장보관, 전자렌지 2분 조리, 에어프라이어 190도에서 5분 조리^2. 통삼겹살 (100g, 1장): 100g씩 넓게 썰기, 팬에서 중불로 한 면당 30~40초씩 조리, 허브솔트 추가^3. 치킨 (150g): 가라아게 튀김기로 초벌 3분 30초, 주문시 재벌 30초^4. 절단옥수수 (2개): 튀김기로 2분 조리^5. 바베큐소스 (40g): 고기 위에 스프레드^6. 레몬 (20g): 치킨 위에 얹기^7. 양상치 (80g): 스리라차 소스 30g 드리즐^8. 볶은양파 (50g): 2스푼 사용^9. 마늘후레이크 (10g): 고기 위에 얹기^10. 소시지 (2개): 튀김기로 30초 조리 후 케첩과 머스타드 드리즐^11. 케이준후라이 (100g): 튀김기로 3분 30초 조리^12. 핫도그번 (2개): 에어프라이어 180도에서 1분 조리^13. 소스 추가: 소스용기에 케찹 & 할라피뇨"
                            ]
                        }, ensure_ascii=False)
                    },
                    {
                        "role": "user",
                        "content": "시그니쳐 플래터 3-4인분 레시피 알려줘"
                    },
                    {
                        "role": "assistant",
                        "content": json.dumps({
                            "menuName":[0],
                            "imageLink":[1],
                            "ingredients":[2],
                            "prepareBowl":[3],
                            "prepareMI":[4],
                            "cookingInstructions":[5]
                        }, ensure_ascii=False, separators=(',', ':')) 
                        + 
                        json.dumps({
                            "data": [
                                "BFT 시그니쳐 플래터 (3~4인분)|https://bft-menus-images.s3.ap-northeast-2.amazonaws.com/bft-images/webp-image/BFT+%EC%8B%9C%EA%B7%B8%EB%8B%88%EC%B3%90+%ED%94%8C%EB%9E%98%ED%84%B0.webp|1. 폭립 500g^2. 통삼겹살 200g^3. 풀드포크 100g^4. 치킨 200g^5. 절단옥수수 3개^6. 바베큐소스 40g^7. 레몬 20g^8. 양상치 80g^9. 볶은양파 50g^10. 마늘후레이크 10g^11. 소시지 3개^12. 케이준후라이 100g^13. 핫도그번 3개|홀 서비스 용기: 철판 쟁반 (31x24 cm), 프라이: 타원형 접시 (지름 27cm)^배달 용기: 각 메뉴별로 햄버거 용기에 나눠 담은 포장 (폭립은 덮밥용기)^플래터 메뉴는 모두 비닐장갑, 컷팅 나이프, 포크 인원수에 맞춰 제공|가라아게 준비 - 튀김기 시간: 초벌 3분 30초 / 주문 시 재벌 30초^소시지 준비 - 튀김기 시간: 30초^케이준후라이 준비 - 튀김기 시간: 3분 30초|조리순서:^1. 폭립 (500g): 자연해동 후 냉장보관, 전자렌지 2분 조리, 에어프라이어 190도에서 5분 조리^2. 통삼겹살 (200g, 2장): 100g씩 두 장으로 팬에서 중불로 한 면당 30~40초씩 조리, 허브솔트 추가^3. 풀드포크 (100g): 4스푼 준비하여 플래터에 담기^4. 치킨 (200g): 가라아게 튀김기로 초벌 3분 30초, 주문 시 재벌 30초^5. 절단옥수수 (3개): 튀김기로 2분 조리^6. 바베큐소스 (40g): 고기 위에 스프레드^7. 레몬 (20g): 조리된 치킨 위에 얹기^8. 양상치 (80g): 스리라차 소스 30g 드리즐^9. 볶은양파 (50g): 2스푼 사용하여 플래터 위에 흩뿌리기^10. 마늘후레이크 (10g): 고기 위에 얹기^11. 소시지 (3개): 튀김기로 30초 조리 후 케첩과 머스타드 드리즐^12. 케이준후라이 (100g): 튀김기로 3분 30초 조리^13. 핫도그번 (3개): 에어프라이어 180도에서 1분간 데우기^14. 소스용기에 케찹 및 할라피뇨를 추가로 담아 고객에 제공할 준비 마무리"
                            ]
                        }, ensure_ascii=False)

                    },
                    {
                        "role": "user",
                        "content": "폭립 프라이에 바베큐소스 얼마나 들어가?"
                    },
                    {
                        "role": "assistant",
                        "content": json.dumps({
                            "title": [0],
                            "simpleRecipe": [1]
                        }, ensure_ascii=False, separators=(',', ':'))  
                        + 
                        json.dumps({
                            "data": [
                                "폭립 프라이|바베큐소스 30g"
                            ]
                        }, ensure_ascii=False)
                    },
                    {
                        "role": "user",
                        "content": "버거 종류 뭐뭐 있어?"
                    },
                    {
                        "role": "assistant",
                        "content": json.dumps({
                            "title": [0],
                            "simpleRecipe": [1]
                        }, ensure_ascii=False, separators=(',', ':'))  
                        + 
                        json.dumps({
                            "data": [
                                "버거 종류|BFT 오리지널 수제버거, 멜팅치즈 더블패티 버거, BFT 시그니처 통베이컨 버거, 풀드포크 버스터 버거, 맥앤치즈 버거, 잭다니엘 핫 치킨 버거 가 있습니다."
                            ]
                        }, ensure_ascii=False)
                    },
                    {
                        "role": "user",
                        "content": "플레인 핫도그에 들어가는 재료 알려줘"
                    },
                    {
                        "role": "assistant",
                        "content": json.dumps({
                            "title": [0],
                            "simpleRecipe": [1]
                        }, ensure_ascii=False, separators=(',', ':'))  
                        + 
                        json.dumps({
                            "data": [
                                "플레인 핫도그|1. 핫도그번 1개^2. 소시지 1개^3. 케챱 적당량^4. 머스타드 소스 10g^5. 파슬리 2g"
                            ]
                        }, ensure_ascii=False)
                    },
                    {
                        "role": "user",
                        "content": "맥앤 치즈 버거에 뭐뭐 들어가가?"
                    },
                    {
                        "role": "assistant",
                        "content": json.dumps({
                            "title": [0],
                            "simpleRecipe": [1]
                        }, ensure_ascii=False, separators=(',', ':'))  
                        + 
                        json.dumps({
                            "data": [
                                "맥앤치즈 버거|1. 햄버거번 1개^2. 렌치소스 20g^3. 소고기 패티 1장^4. 체다치즈 1장^5. 맥앤치즈 50g"
                            ]
                        }, ensure_ascii=False)
                    },                   
                    {
                        "role": "user",
                        "content": "미트포크 프라이 만드는법 알려줘"
                    },
                    {
                        "role": "assistant",
                        "content": json.dumps({
                            "menuName":[0],
                            "imageLink":[1],
                            "ingredients":[2],
                            "prepareBowl":[3],
                            "prepareMI":[4],
                            "cookingInstructions":[5]
                        }, ensure_ascii=False, separators=(',', ':'))  
                        + 
                        json.dumps({
                            "data": [
                                "미트포크 프라이|https://bft-menu-images.s3.us-east-1.amazonaws.com/bft-images/webp-image/%EB%AF%B8%ED%8A%B8%ED%8F%AC%ED%81%AC+%ED%94%84%EB%9D%BC%EC%9D%B4.webp|1. 통삼겹살 200g (100g X 2장)^2. 바베큐소스 40g (30g 스프레드 + 10g 드리즐)^3. 풀드포크 100g (4스푼)^4. 케이준후라이 100g (2줌 가득)|홀: 플래터 - 철판 쟁반 (31x24 cm)^프라이: 타원형 접시 (지름 27cm)^배달: 햄버거 용기에 메뉴별로 각각 나눠 포장|케이준 후라이의 튀김기 시간은 3분 30초|조리 순서:^1. 통삼겹살 200g을 준비합니다. (100g씩 두 장)^2. 바베큐소스 30g을 통삼겹살에 고르게 스프레드합니다^3. 풀드포크 100g을 준비하여 4스푼 덜어 놓습니다.^4. 바베큐소스 10g을 준비하여 드리즐 형태로 요리에 첨가합니다.^5. 케이준후라이 100g을 2줌 가득 넣습니다.^이렇게 준비된 재료들을 플래터에 담아 손님께 제공해주세요!"
                            ]
                        }, ensure_ascii=False)
                    },
                    {
                        "role": "user",
                        "content": "이물질 컴플레인 어떻게 해야해?? 관련 링크 있어?"
                    },
                    {
                        "role": "assistant",
                        "content": json.dumps({
                            "title": [0],
                            "videoLink": [1],
                            "contents": [2]
                        }, ensure_ascii=False, separators=(',', ':'))  
                        + 
                        json.dumps({
                            "data": [
                                "고객이 음식에서 이물질을 발견하고 불만 제기|https://www.youtube.com/embed/SpBNart-MiA|1. 즉각적인 사과와 경청^고객에게 즉시 사과하고 그들의 불만을 경청합니다. \"불편을 드려서 정말 죄송합니다. 어떤 이물질이 발견되었는지 말씀해 주실 수 있나요?\"^2. 상황 확인 및 기록\n고객이 발견한 이물질에 대해 자세히 확인하고 필요한 경우 사진을 찍거나 기록합니다. \"이물질의 종류와 발견된 음식을 확인하겠습니다. 잠시만 기다려 주세요.\"^3. 음식 교환 또는 환불 제안^고객에게 음식 교환이나 환불을 제안합니다. \"이 문제를 해결하기 위해 새 음식을 제공해 드리거나 환불을 원하시면 처리해 드리겠습니다.\""
                            ]
                        }, ensure_ascii=False)
                    },
                    {
                        "role": "user",
                        "content": "잡상인이 왔어요. 어떻게 해요? 관련 링크 있으면 보내줘요"
                    },
                    {
                        "role": "assistant",
                        "content": json.dumps({
                            "title": [0],
                            "videoLink": [1],
                            "contents": [2]

                        }, ensure_ascii=False, separators=(',', ':')) 
                        + 
                        json.dumps({
                            "data": [
                                "잡상인이 매장을 방문했을 때의 대처 방법|https://www.youtube.com/embed/Xkwq4wd8jD8|1. 정중한 거절^잡상인에게 매장에서의 판매나 홍보 활동이 허용되지 않음을 정중하게 알립니다. \"죄송하지만 저희 매장에서는 외부 판매나 홍보를 허용하지 않습니다.\"라고 말합니다.^2. 매장 방침 안내^매장의 정책을 설명하여 매장 내에서의 모든 상업 활동이 제재된다는 점을 강조합니다. \"저희 매장은 고객의 쇼핑 경험을 보호하기 위해 외부 홍보 활동을 금지하고 있습니다.\"라고 안내합니다.^3. 필요한 경우 보안 인력 동원^잡상인이 계속해서 방해하거나 문제를 일으킬 경우, 보안 인력을 호출하여 상황을 해결합니다. \"계속 문제를 일으키신다면, 보안 인력을 부를 수밖에 없습니다.\""
                            ]
                        }, ensure_ascii=False)
                    },
                    {
                        "role": "user",
                        "content": "식자재가 금방 상했어" 
                    },
                    {
                        "role": "assistant",
                        "content": json.dumps({
                            "title": [0],
                            "videoLink": [1],
                            "contents": [2]
                        }, ensure_ascii=False, separators=(',', ':'))  
                        + 
                        json.dumps({
                            "data": [
                                "식자재 관리하는 방법|https://www.youtube.com/embed/5NxRMl1EiHw|1. 즉각적인 재료 폐기^변질된 재료는 즉시 폐기합니다. 안전을 최우선으로 고려하여, 변질된 재료가 고객에게 제공되지 않도록 철저히 관리합니다. 폐기 시에는 변질된 재료를 명확히 표시하고, 다른 재료와 혼합되지 않도록 주의합니다.^2. 상황 보고 및 기록^변질된 재료에 대한 상황을 매장 관리자에게 즉시 보고합니다. 변질된 재료의 종류, 양, 변질 원인 등을 기록하여 향후 유사한 상황을 예방할 수 있는 자료로 활용합니다.^3. 온도 점검 및 조치^보관 온도를 점검하고, 문제가 발생한 냉장고나 저장 공간의 온도를 조절합니다. 필요한 경우, 온도계나 냉장고의 작동 상태를 점검하여 문제가 지속되지 않도록 조치를 취합니다.^4. 대체 재료 준비^변질된 재료를 대체할 수 있는 신선한 재료를 즉시 준비합니다. 재고를 확인하고, 필요한 경우 공급업체에 연락하여 신속하게 재료를 보충합니다. 고객에게 제공할 수 있는 메뉴를 조정하여 서비스에 차질이 없도록 합니다.^5. 직원 교육 및 예방 조치^변질된 재료의 원인과 예방 방법에 대해 직원 교육을 실시합니다. 보관 온도 관리의 중요성을 강조하고, 정기적인 점검 및 유지보수 계획을 수립하여 향후 유사한 상황이 발생하지 않도록 합니다." 
                            ]
                        }, ensure_ascii=False)
                    },

                ]
                messages = few_shot_examples + [
                    {"role": "system", "content": (
                        "You are a helpful assistant. Respond in two parts:\n"
                        "1. Provide the structure map of the data in this format when you get a question about a recipe or ingredients:\n"
                        "{"
                        "\"menuName\":[index],"
                        "\"imageLink\":[index],"
                        "\"ingredients\":[index],"
                        "\"prepareBowl\":[index],"
                        "\"prepareMI\":[index],"
                        "\"cookingInstructions\":[index]"
                        "}"
                        "2. Then provide the full data array corresponding to the structure map as a **single compressed line**:\n"
                        "{"
                        "\"data\":[\"value1|value2|value3|...\"]"
                        "}"

                        "3. Provide the structure map of the data in this format for general recipe-related questions (e.g., ingredient quantities):\n"
                        "{"
                        "\"title\":[index],"
                        "\"simpleRecipe\":[index]"
                        "}"
                        "4. Then provide the full data array corresponding to the structure map as a **single compressed line**:\n"
                        "{"
                        "\"data\":[\"value1|value2|value3|...\"]"
                        "}"

                        "5. Provide the structure map of the data in this format for general questions:\n"
                        "{"
                        "\"title\":[index],"
                        "\"videoLink\":[index],"
                        "\"contents\":[index]"
                        "}"
                        "6. Then provide the full data array corresponding to the structure map as a **single compressed line**:\n"
                        "{"
                        "\"data\":[\"value1|value2|value3|...\"]"
                        "}"

                        "Make sure:\n"
                        "1. Use the pipe symbol (|) instead of commas (,) to separate values **only when there are multiple distinct values in the data array**.\n"
                        "2. If the data array contains a single value, do not use the pipe symbol within that value.\n"
                        "3. Indices start from 0 and increment sequentially without skipping numbers.\n"
                        "4. Do not include any additional markers or formatting like ```json.\n"
                        "5. The 'data' array matches the structure map perfectly.\n"
                        "6. When a context is provided, respond with JSON structure.\n"
                        "7. Only provide links that are verified to exist and are publicly accessible. If no valid link is available, exclude the videoLink field entirely from the response. Do not provide fake links such as https://www.youtube.com/example-link.\n"
                        "8. cookingInstructions을 설명할 때, 'cookingInstructions'는 넘버링된 리스트 형식으로 작성하며, 각 단계는 '-니다.'로 끝나는 공손하고 친절한 문장으로 구성합니다. 모든 단계는 사용자가 쉽게 따라할 수 있도록 설명하고, 팁도 함께 포함하세요.\n"
                        "9. For questions asking about specific ingredient quantities (e.g., '얼마', '몇 g', '양'), use the simplified structure for general recipe-related questions.\n"
                        "10. if link information is included, it must appear immediately after the 'menuName' or 'title' field, ensuring proper order and structure in the output\n"
                        "11. For fields like 'contents', ensure the entire content is treated as a single block (e.g., [2]), instead of splitting it into multiple indices such as [2, 3, 4, 5, 6]."
                        "12. For any line break required in the response—whether in numbered lists, paragraphs, or anywhere else—you must **ONLY** use the caret symbol `^`. This is the **only** acceptable way to indicate a new line. (When rendering the output, replace '^' with an actual newline if needed.)\n"
                        "13. **ABSOLUTE RULE:** You must **NEVER** use newline characters in any form, including but not limited to:\n"
                        "    - `\\n` (**backslash n**)\n"
                        "    - Use only one caret symbol `^` for line breaks.\n"
                        "14. The '용기 준비' and '주요 재료 준비' fields are already implemented in the frontend. Do not include any additional text or explanations for these fields. Only provide the values directly.\n"
                        "15. Even if the provided context contains incomplete or truncated sentences, ensure that your response consists of complete, coherent sentences. Infer any missing information to generate a full and comprehensive answer. Replace any abruptly cut-off content with appropriate, contextually relevant phrases to maintain the flow and clarity of the response.\n"
                        "16. **For recipe-related contexts, do not infer or generate information about ingredients or instructions that are not explicitly mentioned in the context.** If the requested information is not found, respond with '재료정보 없음' or indicate that the item is not included in the recipe.\n"
                        "17. **When responding with 'simpleRecipe', include only the menu name or relevant keywords in the 'title' field.** Avoid adding additional descriptive text or explanations within the 'title'."

                    )},
                    {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {question}"}
                ]

            else:
                no_context_message = (
                    f"Question: {question}\n\n"
                    f"제공된 정보로 답변하기 어려운 경우, 사용자에게 정중히 안내하고 "
                    f"추가적인 문의는 ooooo@gmail.kr로 연락해달라고 요청해주세요."
                )
                non_context_shots_examples = [
                    {
                        "role": "user",
                        "content": "맛있는 저녁 추천해줘"
                    },
                    {
                        "role": "assistant",
                        "content": json.dumps({
                            "title": [0],
                            "commonContents": [1]
                        }, ensure_ascii=False, separators=(',', ':')) 
                        + 
                        json.dumps({
                            "data": [
                                "맛있는 저녁 추천|LA갈비와 상추쌈.^달달하고 짭조름한 갈비에 상추쌈 한입. 어떠신가요?"
                            ]
                        }, ensure_ascii=False)
                    },
                    {
                        "role": "user",
                        "content": "서울에 놀러갈만한 곳 추천해줘"
                    },
                    {
                        "role": "assistant",
                        "content": json.dumps({
                            "title": [0],
                            "commonContents": [1]
                        }, ensure_ascii=False, separators=(',', ':'))
                        + 
                        json.dumps({
                            "data": [
                                "서울 놀러갈만한 곳 추천|서울에는 다양한 명소가 많습니다.^몇 가지 추천드리자면 경복궁, 남산타워, 홍대 거리, 이태원 그리고 한강 공원이 있습니다.^각각의 장소는 독특한 매력을 가지고 있어 방문할 만한 가치가 있습니다.^더 궁금한 점이 있으시면 ooooo@gmail.kr로 연락해 주세요."
                            ]
                        }, ensure_ascii=False)
                    },
                    {
                        "role": "user",
                        "content": "캐나다에서 여행하기 좋은 도시가 어딘가요?"
                    },
                    {
                        "role": "assistant",
                        "content": json.dumps({
                            "title": [0],
                            "commonContents": [1]
                        }, ensure_ascii=False, separators=(',', ':'))
                        + 
                        json.dumps({
                            "data": [
                                "캐나다에서 여행하기 좋은 도시|밴쿠버^롭슨 거리는 쇼핑과 레스토랑이 다양하고, 스탠리 파크는 자연을 느끼기에 좋습니다.^토론토^CN 타워와 온타리오 호수를 즐길 수 있으며 다양한 문화 이벤트가 열립니다.^퀘벡 시티^역사적인 건축물과 유럽풍의 거리를 경험할 수 있습니다.^자세한 정보가 필요하시면 ooooo@gmail.kr로 연락해 주세요."
                            ]
                        }, ensure_ascii=False)
                    },
                    {
                        "role": "user",
                        "content": "라식과 라섹의 차이점이 뭐야?"
                    },
                    {
                        "role": "assistant",
                        "content": json.dumps({
                            "title": [0],
                            "commonContents": [1]
                        }, ensure_ascii=False, separators=(',', ':'))
                        + 
                        json.dumps({
                            "data": [
                                "라식과 라섹의 차이점|라식 (LASIK)^라식은 각막 절편을 만들어 레이저로 각막을 교정하는 수술입니다.^회복이 빠르고 통증이 적지만 각막이 얇은 사람에게는 적합하지 않을 수 있습니다.^라섹 (LASEK)^라섹은 각막 상피를 벗겨내고 레이저로 각막을 교정하는 수술입니다.^회복 기간이 길고 통증이 있을 수 있지만 각막이 얇은 사람에게도 적합합니다."
                            ]
                        }, ensure_ascii=False)
                    },
                    {
                        "role": "user",
                        "content": "하이"
                    },
                    {
                        "role": "assistant",
                        "content": json.dumps({
                            "title": [0],
                            "commonContents": [1]
                        }, ensure_ascii=False, separators=(',', ':'))
                        + 
                        json.dumps({
                            "data": [
                                "하이|안녕하세요! 저는 여러분을 돕기 위해 여기에 있는 프렌지니입니다. 궁금한 점이 있으면 언제든지 물어보세요!"
                            ]
                        }, ensure_ascii=False)
                    },
                    {
                        "role": "user",
                        "content": "나도 내가 뭘 물어봐야 할지 모르겠어.EFGSsdf"
                    },
                    {
                        "role": "assistant",
                        "content": json.dumps({
                            "impossibleToAnswer": [0]
                        }, ensure_ascii=False, separators=(',', ':')) 
                        + 
                        json.dumps({
                            "data": [
                                "답변할 수 없는 질문입니다.^조금 더 생각을 해보신 후에 다시 물어봐주세요."
                            ]
                        }, ensure_ascii=False)
                    },
                ]


                system_message = {
                    "role": "system",
                    "content": (
                        "You are a helpful assistant. When there is no context, respond in two parts:\n"
                        "1. Provide the structure map of the data in this format:\n"
                        "{"
                        "\"title\": [index],"
                        "\"commonContents\": [index]"
                        "}"
                        "2. Then provide the full data array corresponding to the structure map as a **single compressed line**:\n"
                        "{"
                        "\"data\":[\"value1|value2\"]"
                        "}"

                        "Make sure:\n"
                        "1. Use the pipe symbol (|) **only to separate 'title' and 'commonContents' within the 'data' array**.\n"
                        "   - Do **not** use the pipe symbol inside a single block of explanation or when listing multiple details in the same section.\n"
                        "2. If the data array contains a single value, do not use the pipe symbol within that value."
                        "3. Indices start from 0 and increment sequentially without skipping numbers.\n"
                        "4. Do not include any additional markers or formatting like ```json.\n"
                        "5. The 'data' array matches the structure map.\n"
                        "6. 제공된 정보로 답변하기 어려운 경우, gpt가 아는 선에서 답변하고, 사용자에게 정중히 안내하고 추가적인 문의는 ooooo@gmail.kr로 연락해달라고 요청해주세요.\n"
                        "7. Only provide links that are verified to exist and are publicly accessible. If no valid link is available, exclude the link field entirely from the response. Do not provide fake links such as https://www.youtube.com/example-link.\n"
                        "8. **If the question cannot be answered or there is insufficient information, respond strictly in the following format:**\n"
                        "{"
                        "\"impossibleToAnswer\":[0]"
                        "}"
                        "{"
                        "\"data\": [\"답변할 수 없는 질문입니다.\"]"
                        "}"
                        "Do not provide any additional explanations outside this format when you cannot answer the question."
                        "9. Any line break required in the response, whether in numbered lists or anywhere else, must be represented using the '^' symbol instead of '\\n'. (Strictly avoid using '\\n' or double carets '^^' under any circumstances.)"
                        "10. If you receive greetings such as '안녕', '하이', 'Hello', or 'Hi', respond warmly with a greeting and introduce yourself as a frien-genie here to help.\n"
                    )
                }
                

                # user_message에 실제 질문을 담습니다.
                user_message = {
                    "role": "user",
                    "content": no_context_message
                }

                # 최종 messages 배열: [few-shot ...] + [system] + [user]
                messages = non_context_shots_examples + [system_message, user_message]


            # OpenAI 스트림 호출
            stream = await client.chat.completions.create(
                model="gpt-4o",
                messages=messages,
                stream=True,
                temperature= 0.3
                
            )

            # OpenAI 스트림 데이터 처리
            async for chunk in stream:
                delta = chunk.choices[0].delta if chunk.choices and chunk.choices[0].delta else None
                chunk_content = delta.content if delta and hasattr(delta, "content") else ""

                if chunk_content:

                    # # \\n을 <br>로 변환
                    # chunk_content = chunk_content.replace("\n", "<br>")
                    
                    # print(f"### Chunk Received ###\n{chunk_content}")
                    yield (
                        f"id: {id_counter}\n"
                        f"event: message\n"
                        f"data: {json.dumps({'status': 'processing', 'data': chunk_content}, ensure_ascii=False)}\n\n"
                    )
                    all_yielded_data.append(chunk_content)  # 누적 데이터에 추가
                    id_counter += 1

            # 스트림 완료 메시지
            yield (
                f"id: {id_counter}\n"
                f"event: message\n"
                f"data: {json.dumps({'status': 'complete', 'data': ''}, ensure_ascii=False)}\n\n"
            )
                # 전체 데이터 출력
            print("### All Yielded Data ###")
            print("".join(all_yielded_data))  # 누적된 데이터 합치기
            
            # -------------------------
            # 3) 질문-응답 데이터를 OpenSearch에 저장
            # -------------------------

            full_response = "".join(all_yielded_data)  # 누적된 데이터를 하나로 결합
            save_to_opensearch(
                index_name="seoul-qa-index",  # 저장할 인덱스 이름
                question=question,
                response=full_response,
                timestamp=timestamp_millis
            )
        return StreamingResponse(stream_openai_response(context, question), media_type="text/event-stream; charset=utf-8")

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
