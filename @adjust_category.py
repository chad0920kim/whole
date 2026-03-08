# -*- coding: utf-8 -*-
"""
카테고리 조정 스크립트
=====================
네이버에 등록된 상품의 카테고리를 AI로 분석하여 조정합니다.

기능:
- 등록된 상품의 제목과 상세설명 조회
- AI(GPT)로 적합한 카테고리 분류
- 네이버 카테고리와 매칭하여 업데이트

사용법: python @adjust_category.py
"""

import sys
import io
import os
import re
import time
from typing import Optional, List, Dict, Tuple
from dotenv import load_dotenv

load_dotenv(override=True)

# Windows 콘솔 인코딩 설정
if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, 'buffer') and not isinstance(sys.stdout, io.TextIOWrapper):
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    except:
        pass

try:
    from openai import OpenAI
    from google_sheets import GoogleSheetsManager
    from naver_commerce import NaverCommerceAPI
except ImportError as e:
    print(f"[ERROR] 필수 모듈을 찾을 수 없습니다: {e}")
    sys.exit(1)

# 구글 시트 설정
SHEET_NAME = "registered_products"
RESULT_SHEET_ID = "15LR78H5Q9RzA-A30mVxc6kswcZwDcr7gWPputtq_3zU"

# 컬럼 인덱스 (0-based)
COL_NAVER_CHANNEL_NO = 2   # C열: 네이버채널번호
COL_PRODUCT_NAME = 4       # E열: 상품명
COL_CATEGORY_RESULT = 14   # O열: 카테고리 조정 결과

# 제외 카테고리 (권한 필요 또는 특수 인증 필요)
EXCLUDED_CATEGORY_KEYWORDS = [
    '출산', '육아', '유아', '아동',  # KC인증 필수
    '도서', '책', 'e북', '음반',      # ISBN 필수
    '주류', '와인', '맥주', '소주', '위스키', '전통주', '과일주',  # 주류 판매 권한 필요
    '의약품', '의약외품', '건강기능식품',  # 의약품 판매 권한 필요
    '담배', '전자담배',  # 담배 판매 권한 필요
    # KC인증 필요 카테고리 추가
    '헬스', '운동기구', '복근운동', '웨이트', '트레이닝기구',
    '전동킥보드', '전기자전거', '전동휠',  # 전기용품 KC인증
    '어린이', '키즈',  # 어린이용품 KC인증
    # 결제수단 제한 카테고리 (카테고리 변경 불가)
    '주얼리', '귀금속', '금', '은', '백금', '다이아몬드',  # 결제수단 제한
    '귀걸이', '목걸이', '반지', '팔찌',  # 주얼리 세부 (결제수단 제한)
]

# KC 인증 필요 카테고리 ID 목록 (정확한 카테고리 ID로 제외)
KC_REQUIRED_CATEGORY_IDS = [
    # 스포츠/레저 > 헬스 관련
    "50001828",  # 헬스
    "50001829",  # 복근운동기구
    "50001830",  # AB슬라이드
]

# 결제수단 제한 카테고리 ID 목록 (주얼리/귀금속 - 일반 카테고리 변경 불가)
RESTRICTED_PAYMENT_CATEGORY_IDS = [
    # 패션잡화 > 주얼리 관련
    "50000804",  # 주얼리
    "50000805",  # 귀걸이
    "50000806",  # 목걸이/펜던트
    "50000807",  # 반지
    "50000808",  # 팔찌/발찌
]


class CategoryAdjuster:
    """카테고리 조정 클래스"""

    def __init__(self):
        self.openai_client = self._init_openai()
        self.naver_api = NaverCommerceAPI()
        self.sheets = GoogleSheetsManager()
        self.sheet_id = os.getenv("GOOGLE_SHEET_ID")

        # 카테고리 캐시
        self._category_cache = None
        self._leaf_categories = None

        # 에러 로그 기록
        self.error_logs = []  # [{product, error_type, details, ai_category, matched_category}, ...]
        self.success_logs = []  # 성공 기록

    def _init_openai(self) -> Optional[OpenAI]:
        """OpenAI 클라이언트 초기화"""
        api_key = os.getenv('OPENAI_API_KEY')
        if not api_key:
            # 상위 폴더에서 찾기
            parent_env = os.path.join(os.path.dirname(__file__), '..', 'smm2', '.env')
            if os.path.exists(parent_env):
                from dotenv import dotenv_values
                config = dotenv_values(parent_env)
                api_key = config.get('OPENAI_API_KEY')

        if api_key:
            return OpenAI(api_key=api_key)
        else:
            print("[WARN] OPENAI_API_KEY가 설정되지 않았습니다")
            return None

    def load_categories(self):
        """네이버 카테고리 목록 로드"""
        if self._category_cache is not None:
            return

        print("[카테고리] 네이버 카테고리 목록 로드 중...")
        categories = self.naver_api.get_categories()

        if categories:
            self._category_cache = categories
            # 리프 카테고리만 필터링 (last=True)
            self._leaf_categories = [c for c in categories if c.get('last') is True]
            print(f"  총 {len(categories)}개 카테고리, 리프 {len(self._leaf_categories)}개")
        else:
            self._category_cache = []
            self._leaf_categories = []
            print("  [ERROR] 카테고리 로드 실패")

    def get_registered_products(self, only_unprocessed: bool = False) -> List[Dict]:
        """구글 시트에서 등록된 상품 목록 조회

        Args:
            only_unprocessed: True면 O열이 빈 상품만 반환
        """
        if not self.sheet_id:
            print("[ERROR] GOOGLE_SHEET_ID 환경변수가 설정되지 않았습니다")
            return []

        try:
            # O열까지 조회 (A~O = 15열)
            data = self.sheets.get_sheet_data(self.sheet_id, f"{SHEET_NAME}!A2:O")
            products = []

            for idx, row in enumerate(data, start=2):
                if len(row) < 5:
                    continue

                naver_channel_no = row[COL_NAVER_CHANNEL_NO] if len(row) > COL_NAVER_CHANNEL_NO else ""
                name = row[COL_PRODUCT_NAME] if len(row) > COL_PRODUCT_NAME else ""

                # O열 (인덱스 14) 결과값 확인
                result_value = row[COL_CATEGORY_RESULT] if len(row) > COL_CATEGORY_RESULT else ""

                if naver_channel_no and name:
                    # 미처리 상품만 필터링
                    if only_unprocessed and result_value:
                        continue  # O열에 값이 있으면 스킵

                    products.append({
                        "row_num": idx,
                        "naver_channel_no": str(naver_channel_no),
                        "name": name,
                        "result": result_value  # 기존 결과값도 포함
                    })

            return products

        except Exception as e:
            print(f"[ERROR] 상품 목록 조회 실패: {e}")
            return []

    def get_product_detail(self, channel_product_no: str) -> Optional[Dict]:
        """네이버 상품 상세 정보 조회"""
        try:
            product = self.naver_api.get_product(channel_product_no)
            if not product:
                print(f"  [ERROR] 상품 조회 결과 없음: {channel_product_no}")
                return None

            # API 응답 구조 확인
            # channel-products API 응답에는 originProductNo가 최상위에 있을 수 있음
            origin_product_no = product.get("originProductNo", "")

            # originProduct 하위에서도 찾기
            origin = product.get("originProduct", {})
            smart = product.get("smartstoreChannelProduct", {})

            if not origin_product_no:
                origin_product_no = origin.get("originProductNo", "")

            # 그래도 없으면 channelProductNo를 이용해 originProduct 정보 조회 시도
            if not origin_product_no:
                # 최상위 레벨에서 확인
                print(f"  [DEBUG] API 응답 키: {list(product.keys())}")
                # origin이 dict가 아닌 경우 처리
                if isinstance(origin, dict) and origin:
                    print(f"  [DEBUG] originProduct 키: {list(origin.keys())[:10]}")

            return {
                "name": origin.get("name", "") if isinstance(origin, dict) else product.get("name", ""),
                "detail_content": origin.get("detailContent", "") if isinstance(origin, dict) else "",
                "current_category_id": origin.get("leafCategoryId", "") if isinstance(origin, dict) else product.get("leafCategoryId", ""),
                "origin_product_no": origin_product_no,
                "channel_product_no": channel_product_no,  # 채널상품번호도 저장
                "display_status": smart.get("channelProductDisplayStatusType", "") if isinstance(smart, dict) else ""
            }

        except Exception as e:
            print(f"  [ERROR] 상품 상세 조회 실패: {e}")
            import traceback
            traceback.print_exc()
            return None

    def extract_text_from_html(self, html: str, max_length: int = 2000) -> str:
        """HTML에서 텍스트 추출"""
        if not html:
            return ""

        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, 'html.parser')

            # 스크립트, 스타일 제거
            for tag in soup(['script', 'style']):
                tag.decompose()

            text = soup.get_text(separator=' ', strip=True)
            # 공백 정리
            text = re.sub(r'\s+', ' ', text)
            return text[:max_length]

        except Exception:
            # BeautifulSoup 없으면 간단한 태그 제거
            text = re.sub(r'<[^>]+>', ' ', html)
            text = re.sub(r'\s+', ' ', text)
            return text[:max_length]

    def classify_category_with_ai(self, product_name: str, detail_text: str) -> Optional[str]:
        """AI로 상품 카테고리 분류"""
        if not self.openai_client:
            return None

        try:
            # 카테고리 목록 요약 (주요 대분류)
            main_categories = """
주요 카테고리:
- 패션의류: 여성의류, 남성의류, 언더웨어, 잠옷
- 패션잡화: 가방, 지갑, 벨트, 모자, 양말
- 화장품/미용: 스킨케어, 메이크업, 헤어케어, 바디케어
- 디지털/가전: 휴대폰, 컴퓨터, TV, 생활가전, 계절가전
- 가구/인테리어: 가구, 침구, 수납, 인테리어소품
- 생활/건강: 욕실용품, 주방용품, 세탁용품, 건강용품
- 식품: 가공식품, 음료, 과일, 간식
- 스포츠/레저: 운동기구, 캠핑, 자전거, 등산
- 자동차용품: 인테리어용품, 익스테리어용품, 세차용품
- 완구/취미: 장난감, 피규어, 보드게임
- 반려동물: 강아지용품, 고양이용품, 사료, 간식
- 문구/오피스: 필기구, 사무용품, 학용품
"""

            prompt = f"""다음 상품 정보를 분석하여 가장 적합한 카테고리를 추천해주세요.

[상품 정보]
상품명: {product_name}
상세설명: {detail_text[:1500] if detail_text else '없음'}

{main_categories}

반드시 아래 형식으로 답변하세요:
대분류 > 중분류 > 소분류

예시:
- 전기장판 → 가구/인테리어 > 침구 > 전기요/매트
- 블루투스 이어폰 → 디지털/가전 > 음향가전 > 이어폰
- 강아지 사료 → 반려동물 > 강아지용품 > 사료

한 줄로만 답변하세요."""

            response = self.openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "상품 카테고리 분류 전문가입니다. 상품명과 상세설명을 분석하여 가장 적합한 카테고리를 '대분류 > 중분류 > 소분류' 형식으로 정확히 분류합니다."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=100,
                temperature=0.1
            )

            result = response.choices[0].message.content.strip()
            print(f"  [AI] 추천 카테고리: {result}")
            return result

        except Exception as e:
            print(f"  [AI] 분류 실패: {e}")
            return None

    def find_matching_category(self, ai_category: str) -> Optional[str]:
        """AI 추천 카테고리에 맞는 네이버 카테고리 ID 찾기

        개선된 로직:
        1. AI 추천 카테고리의 상위 카테고리도 고려
        2. "패션의류 > 남성의류 > 바지"면 "패션의류" 하위 카테고리 우선
        3. 상위 카테고리 일치 점수 + 키워드 매칭 점수로 최적 매칭
        """
        if not self._leaf_categories or not ai_category:
            return None

        # AI 결과에서 키워드 추출 (상위부터 하위 순서)
        parts = [p.strip() for p in ai_category.split('>')]
        keywords = []
        for part in parts:
            # 괄호 안 내용도 포함
            sub_parts = re.split(r'[/,()]', part)
            for sp in sub_parts:
                sp = sp.strip()
                if sp and len(sp) >= 2:
                    keywords.append(sp.lower())

        if not keywords:
            return None

        print(f"  [매칭] AI 추천: {ai_category}")
        print(f"  [매칭] 키워드: {keywords}")

        # 카테고리 매칭 (상위 카테고리 일치도 점수 반영)
        # 키워드 매핑 (동의어 처리)
        keyword_synonyms = {
            '패션의류': ['패션의류', '의류'],
            '남성의류': ['남성의류', '남자의류', '남성'],
            '여성의류': ['여성의류', '여자의류', '여성'],
            '가구': ['가구', '가구/인테리어'],
            '침구': ['침구', '침구류'],
            '디지털': ['디지털', '디지털/가전'],
            '가전': ['가전', '생활가전'],
        }

        all_matches = []

        for cat in self._leaf_categories:
            whole_name = cat.get('wholeCategoryName', '').lower()
            cat_id = str(cat.get('id', ''))

            # 제외 카테고리 필터링 (키워드 기반)
            if any(ex.lower() in whole_name for ex in EXCLUDED_CATEGORY_KEYWORDS):
                continue

            # KC 인증 필요 카테고리 ID로 필터링
            if cat_id in KC_REQUIRED_CATEGORY_IDS:
                continue

            # 결제수단 제한 카테고리 ID로 필터링
            if cat_id in RESTRICTED_PAYMENT_CATEGORY_IDS:
                continue

            cat_parts = [p.strip().lower() for p in whole_name.split('>')]

            # 점수 계산
            score = 0
            matched_keywords = []

            # 1. 상위 카테고리부터 순서대로 매칭 점수 부여
            # 첫 번째 키워드(대분류) 일치 시 높은 점수
            for i, keyword in enumerate(keywords):
                # 동의어 확인
                synonyms = keyword_synonyms.get(keyword, [keyword])

                for cat_part in cat_parts:
                    # 정확한 매칭 또는 동의어 매칭
                    is_match = False

                    if cat_part == keyword:
                        is_match = True
                    elif any(syn in cat_part or cat_part in syn for syn in synonyms):
                        is_match = True
                    # 복합 카테고리 (예: "트레이닝바지")에서 키워드가 끝에 있는지
                    elif cat_part.endswith(keyword) and len(cat_part) > len(keyword):
                        prefix = cat_part[:-len(keyword)]
                        # 음식/해산물 관련 제외 (바지락 등)
                        if prefix not in ['바지', '조개', '해산', '고등어', '멸치']:
                            is_match = True

                    if is_match:
                        # 상위 카테고리일수록 높은 점수 (10, 8, 6, 4...)
                        position_score = max(10 - i * 2, 2)
                        score += position_score
                        matched_keywords.append(keyword)
                        break

            # 2. 매칭된 키워드가 있으면 후보에 추가
            if score > 0:
                # 깊이도 고려 (더 구체적인 카테고리 선호)
                depth = len(cat_parts)
                total_score = score * 10 + depth
                all_matches.append((cat, total_score, matched_keywords))

        if all_matches:
            # 점수 순으로 정렬
            all_matches.sort(key=lambda x: x[1], reverse=True)

            # 상위 3개 후보 출력
            print(f"  [매칭] 후보:")
            for cat, score, matched in all_matches[:3]:
                print(f"    - {cat.get('wholeCategoryName')} (점수: {score}, 매칭: {matched})")

            best_cat = all_matches[0][0]
            print(f"  [매칭] 선택: {best_cat.get('wholeCategoryName')} ({best_cat.get('id')})")
            return best_cat.get('id')

        print(f"  [매칭] 일치하는 카테고리 없음")
        return None

    def update_product_category(self, origin_product_no: str, new_category_id: str,
                                  channel_product_no: str = "") -> bool:
        """상품 카테고리 업데이트

        네이버 커머스 API v2 사용
        - channel-products API로 카테고리 변경
        - 필수 필드: statusType, saleType, leafCategoryId, name, salePrice, stockQuantity, deliveryInfo
        """
        try:
            import requests

            if not new_category_id:
                print(f"  [ERROR] new_category_id가 없습니다")
                return False

            if not channel_product_no:
                print(f"  [ERROR] channel_product_no가 없습니다")
                return False

            headers = self.naver_api._get_headers()

            # 먼저 기존 상품 전체 정보를 가져옴
            product = self.naver_api.get_product(channel_product_no)
            if not product:
                print(f"  [ERROR] 상품 정보 조회 실패")
                return False

            origin = product.get("originProduct", {})

            # statusType 값 확인 및 정규화
            status_type = origin.get("statusType", "SALE")
            # 유효한 statusType 값: SALE, SUSPENSION, OUTOFSTOCK, UNADMISSION, REJECTION, WAIT, DELETE
            valid_status_types = ["SALE", "SUSPENSION", "OUTOFSTOCK", "UNADMISSION", "REJECTION", "WAIT", "DELETE"]
            if status_type not in valid_status_types:
                print(f"  [WARN] statusType '{status_type}' -> 'SALE'로 변경")
                status_type = "SALE"

            # saleType 값 확인
            sale_type = origin.get("saleType", "NEW")
            valid_sale_types = ["NEW", "OLD"]
            if sale_type not in valid_sale_types:
                sale_type = "NEW"

            # deliveryInfo 필수 필드 확보
            delivery_info = origin.get("deliveryInfo", {})
            if not delivery_info:
                # 기본 배송 정보 설정
                delivery_info = {
                    "deliveryType": "DELIVERY",
                    "deliveryAttributeType": "NORMAL",
                    "deliveryFee": {
                        "deliveryFeeType": "FREE"
                    }
                }

            # smartstoreChannelProduct 정보 가져오기
            smartstore = product.get("smartstoreChannelProduct", {})
            channel_product_display_status = smartstore.get("channelProductDisplayStatusType", "ON")

            # images 필수 필드 확보
            images = origin.get("images", {})
            if not images:
                print(f"  [ERROR] 상품 이미지 정보가 없습니다")
                return False

            # 기존 정보를 유지하면서 카테고리만 변경
            update_data = {
                "originProduct": {
                    "statusType": status_type,
                    "saleType": sale_type,
                    "leafCategoryId": str(new_category_id),
                    "name": origin.get("name", ""),
                    "images": images,  # 필수 필드
                    "salePrice": origin.get("salePrice", 0),
                    "stockQuantity": origin.get("stockQuantity", 100),
                    "deliveryInfo": delivery_info,
                },
                "smartstoreChannelProduct": {
                    "channelProductDisplayStatusType": channel_product_display_status,
                    "naverShoppingRegistration": True  # Boolean 값
                }
            }

            # detailAttribute가 있으면 추가 (None이 아닌 경우)
            detail_attr = origin.get("detailAttribute")
            if detail_attr and isinstance(detail_attr, dict):
                update_data["originProduct"]["detailAttribute"] = detail_attr

            # smartstore 추가 정보가 있으면 포함
            if smartstore.get("storeKeepExclusiveProduct") is not None:
                update_data["smartstoreChannelProduct"]["storeKeepExclusiveProduct"] = smartstore.get("storeKeepExclusiveProduct")

            # channel-products API 사용
            url = f"{self.naver_api.BASE_URL}/external/v2/products/channel-products/{channel_product_no}"

            response = requests.put(
                url,
                headers=headers,
                json=update_data,
                timeout=30
            )

            if response.status_code in [200, 204]:
                return True, None
            else:
                print(f"  [ERROR] 카테고리 업데이트 실패: {response.status_code}")
                error_text = response.text[:500]
                print(f"    {error_text}")

                # 에러 상세 분석
                error_reason = None
                try:
                    error_json = response.json()
                    if "invalidInputs" in error_json:
                        for inv in error_json["invalidInputs"]:
                            msg = inv.get('message', '')
                            name = inv.get('name', '')
                            inv_type = inv.get('type', '')
                            print(f"    - {name}: {msg}")
                            if "대분류" in msg:
                                error_reason = "대분류변경불가"
                            elif "KC" in msg or "인증" in msg or "certificationInfos" in name:
                                error_reason = "KC인증필요"
                            elif "결제수단" in msg or "RestrictPayMean" in inv_type:
                                error_reason = "결제수단제한"
                            elif "NotChangable" in inv_type:
                                error_reason = "카테고리변경불가"
                except:
                    pass

                return False, error_reason

        except Exception as e:
            print(f"  [ERROR] 카테고리 업데이트 오류: {e}")
            import traceback
            traceback.print_exc()
            return False, None

    def get_category_name(self, category_id: str) -> str:
        """카테고리 ID로 이름 조회"""
        if not self._category_cache:
            return category_id

        for cat in self._category_cache:
            if str(cat.get('id')) == str(category_id):
                return cat.get('wholeCategoryName', category_id)
        return category_id

    def log_error(self, product: Dict, error_type: str, details: str,
                   ai_category: str = "", matched_category: str = "", matched_id: str = ""):
        """에러 로그 기록"""
        log_entry = {
            "product_name": product.get("name", ""),
            "channel_no": product.get("naver_channel_no", ""),
            "row_num": product.get("row_num", 0),
            "error_type": error_type,
            "details": details,
            "ai_category": ai_category,
            "matched_category": matched_category,
            "matched_id": matched_id,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        self.error_logs.append(log_entry)

        # 구글 시트 O열에 결과 저장
        row_num = product.get("row_num", 0)
        if row_num > 0:
            if error_type == "대분류변경불가":
                result_text = f"[대분류불가] 재등록필요"
            elif error_type == "KC인증필요":
                result_text = f"[KC인증필요] 카테고리변경불가"
            elif error_type == "결제수단제한":
                result_text = f"[결제수단제한] 재등록필요"
            elif error_type == "카테고리변경불가":
                result_text = f"[변경불가] 재등록필요"
            else:
                result_text = f"[실패] {error_type}"
            self._save_result_to_sheet(row_num, result_text)

    def log_success(self, product: Dict, from_cat: str, to_cat: str):
        """성공 로그 기록"""
        log_entry = {
            "product_name": product.get("name", ""),
            "channel_no": product.get("naver_channel_no", ""),
            "row_num": product.get("row_num", 0),
            "from_category": from_cat,
            "to_category": to_cat,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        self.success_logs.append(log_entry)

        # 구글 시트 O열에 결과 저장
        row_num = product.get("row_num", 0)
        if row_num > 0:
            # 카테고리 마지막 부분만 표시
            to_short = to_cat.split('>')[-1].strip() if '>' in to_cat else to_cat
            result_text = f"[완료] → {to_short}"
            self._save_result_to_sheet(row_num, result_text)

    def _save_result_to_sheet(self, row_num: int, result_text: str):
        """결과를 구글 시트 O열에 저장"""
        try:
            # O열 = 15번째 열 (1-indexed)
            cell_range = f"{SHEET_NAME}!O{row_num}"
            self.sheets.update_sheet_data(
                RESULT_SHEET_ID,
                cell_range,
                [[result_text]]
            )
        except Exception as e:
            print(f"  [WARN] 시트 저장 실패: {e}")

    def process_product(self, product: Dict) -> Tuple[bool, str]:
        """단일 상품 카테고리 조정 처리"""
        channel_no = product["naver_channel_no"]
        name = product["name"]

        print(f"\n[상품] {name[:40]}")
        print(f"  채널번호: {channel_no}")

        # 1. 상품 상세 정보 조회
        detail = self.get_product_detail(channel_no)
        if not detail:
            self.log_error(product, "상세조회실패", "네이버 API에서 상품 정보를 가져올 수 없음")
            return False, "상세 조회 실패"

        current_cat_id = detail["current_category_id"]
        current_cat_name = self.get_category_name(current_cat_id)
        print(f"  현재 카테고리: {current_cat_name}")

        # 2. 상세설명에서 텍스트 추출
        detail_text = self.extract_text_from_html(detail["detail_content"])

        # 3. AI로 카테고리 분류
        ai_category = self.classify_category_with_ai(name, detail_text)
        if not ai_category:
            self.log_error(product, "AI분류실패", "OpenAI API 호출 실패 또는 응답 없음")
            return False, "AI 분류 실패"

        # 4. 네이버 카테고리 매칭
        new_cat_id = self.find_matching_category(ai_category)
        if not new_cat_id:
            self.log_error(product, "카테고리매칭실패",
                          f"AI 추천 '{ai_category}'에 맞는 네이버 카테고리를 찾을 수 없음",
                          ai_category=ai_category)
            return False, "카테고리 매칭 실패"

        new_cat_name = self.get_category_name(new_cat_id)

        # 5. 같은 카테고리면 스킵
        if str(new_cat_id) == str(current_cat_id):
            print(f"  [SKIP] 이미 적합한 카테고리입니다")
            # 스킵도 구글 시트에 기록
            row_num = product.get("row_num", 0)
            if row_num > 0:
                cat_short = current_cat_name.split('>')[-1].strip() if '>' in current_cat_name else current_cat_name
                self._save_result_to_sheet(row_num, f"[적합] {cat_short}")
            return True, "변경 불필요"

        print(f"  변경: {current_cat_name}")
        print(f"    → {new_cat_name}")

        # 6. 카테고리 업데이트 (origin_product_no 또는 channel_product_no 사용)
        success, error_reason = self.update_product_category(
            detail.get("origin_product_no", ""),
            new_cat_id,
            detail.get("channel_product_no", channel_no)
        )
        if success:
            print(f"  [완료] 카테고리 변경 완료!")
            self.log_success(product, current_cat_name, new_cat_name)
            return True, f"{current_cat_name} → {new_cat_name}"
        else:
            # 에러 유형별 특별 처리
            if error_reason == "대분류변경불가":
                error_type = "대분류변경불가"
                error_msg = f"대분류 변경 불가 ({current_cat_name.split('>')[0].strip()} → {new_cat_name.split('>')[0].strip()})"
            elif error_reason == "KC인증필요":
                error_type = "KC인증필요"
                error_msg = f"대상 카테고리({new_cat_name})에 KC 인증 필요"
            elif error_reason == "결제수단제한":
                error_type = "결제수단제한"
                error_msg = f"결제수단 제한 카테고리 → 일반 카테고리 변경 불가"
            elif error_reason == "카테고리변경불가":
                error_type = "카테고리변경불가"
                error_msg = f"해당 카테고리에서는 변경 불가"
            else:
                error_type = "API업데이트실패"
                error_msg = f"네이버 API PUT 요청 실패"

            self.log_error(product, error_type, error_msg,
                          ai_category=ai_category,
                          matched_category=new_cat_name,
                          matched_id=str(new_cat_id))
            return False, error_type

    def analyze_errors(self):
        """에러 분석 (통계만 출력)"""
        if not self.error_logs:
            print("\n[분석] 에러가 없습니다!")
            return

        print("\n" + "=" * 60)
        print("에러 분석")
        print("=" * 60)

        # 에러 유형별 통계
        error_types = {}
        for log in self.error_logs:
            err_type = log["error_type"]
            error_types[err_type] = error_types.get(err_type, 0) + 1

        print(f"\n[에러 통계] 총 {len(self.error_logs)}건")
        for err_type, count in error_types.items():
            print(f"  - {err_type}: {count}건")

        # 상세 에러 목록
        print(f"\n[에러 상세]")
        for i, log in enumerate(self.error_logs, 1):
            print(f"\n  {i}. {log['product_name'][:30]}")
            print(f"     채널번호: {log['channel_no']}")
            print(f"     에러유형: {log['error_type']}")
            print(f"     상세: {log['details']}")
            if log.get('ai_category'):
                print(f"     AI추천: {log['ai_category']}")
            if log.get('matched_category'):
                print(f"     매칭결과: {log['matched_category']} ({log.get('matched_id', '')})")



def main():
    print("=" * 60)
    print("카테고리 조정 스크립트")
    print("=" * 60)

    adjuster = CategoryAdjuster()

    # 카테고리 목록 로드
    adjuster.load_categories()

    if not adjuster._leaf_categories:
        print("\n[ERROR] 카테고리 목록을 로드할 수 없습니다.")
        return

    # 실행 모드 선택
    print("\n실행 모드를 선택하세요:")
    print("  1. 전체 상품 확인 (구글 시트 기준)")
    print("  2. 미처리 상품만 (O열 빈칸)")
    print("  3. 특정 상품번호 직접 입력")
    print("  4. 네이버에서 상품 목록 조회 후 선택")
    print()

    choice = input("선택 (1-4): ").strip()

    if choice == "1":
        # 구글 시트에서 상품 목록 조회
        products = adjuster.get_registered_products()
        if not products:
            print("\n등록된 상품이 없습니다.")
            return

        print(f"\n등록된 상품 {len(products)}개 발견")
        print("-" * 60)

        # 상품 목록 표시
        for i, p in enumerate(products[:20], 1):
            print(f"  {i}. [{p['naver_channel_no']}] {p['name'][:40]}")

        if len(products) > 20:
            print(f"  ... 외 {len(products) - 20}개")

        print()
        selection = input("처리할 상품 선택 (번호, 범위 1-5, all, 또는 Enter로 취소): ").strip().lower()

        if not selection:
            print("취소됨")
            return

        # 선택 파싱
        if selection in ['all', 'a']:
            selected_products = products
        elif '-' in selection:
            parts = selection.split('-')
            start = int(parts[0].strip()) - 1
            end = int(parts[1].strip())
            selected_products = products[start:end]
        elif ',' in selection:
            indices = [int(n.strip()) - 1 for n in selection.split(',')]
            selected_products = [products[i] for i in indices if 0 <= i < len(products)]
        else:
            try:
                idx = int(selection) - 1
                selected_products = [products[idx]] if 0 <= idx < len(products) else []
            except:
                selected_products = []

        if not selected_products:
            print("선택된 상품이 없습니다.")
            return

        print(f"\n{len(selected_products)}개 상품 카테고리 조정 시작...")
        print("-" * 60)

        success_count = 0
        fail_count = 0

        for product in selected_products:
            success, msg = adjuster.process_product(product)
            if success and msg != "변경 불필요":
                success_count += 1
            elif not success:
                fail_count += 1

            time.sleep(2)  # API 호출 간격

        print("\n" + "=" * 60)
        print(f"[완료] 변경: {success_count}건 | 실패: {fail_count}건")
        print("=" * 60)

        # 에러 분석
        if fail_count > 0:
            adjuster.analyze_errors()

    elif choice == "2":
        # 미처리 상품만 (O열 빈칸)
        products = adjuster.get_registered_products(only_unprocessed=True)
        if not products:
            print("\n미처리 상품이 없습니다. (모든 상품이 이미 처리됨)")
            return

        print(f"\n미처리 상품 {len(products)}개 발견")
        print("-" * 60)

        # 상품 목록 표시
        for i, p in enumerate(products[:20], 1):
            print(f"  {i}. [{p['naver_channel_no']}] {p['name'][:40]}")

        if len(products) > 20:
            print(f"  ... 외 {len(products) - 20}개")

        print()
        selection = input("처리할 상품 선택 (번호, 범위 1-5, all, 또는 Enter로 취소): ").strip().lower()

        if not selection:
            print("취소됨")
            return

        # 선택 파싱
        if selection in ['all', 'a']:
            selected_products = products
        elif '-' in selection:
            parts = selection.split('-')
            start = int(parts[0].strip()) - 1
            end = int(parts[1].strip())
            selected_products = products[start:end]
        elif ',' in selection:
            indices = [int(n.strip()) - 1 for n in selection.split(',')]
            selected_products = [products[i] for i in indices if 0 <= i < len(products)]
        else:
            try:
                idx = int(selection) - 1
                selected_products = [products[idx]] if 0 <= idx < len(products) else []
            except:
                selected_products = []

        if not selected_products:
            print("선택된 상품이 없습니다.")
            return

        print(f"\n{len(selected_products)}개 미처리 상품 카테고리 조정 시작...")
        print("-" * 60)

        success_count = 0
        fail_count = 0

        for product in selected_products:
            success, msg = adjuster.process_product(product)
            if success and msg != "변경 불필요":
                success_count += 1
            elif not success:
                fail_count += 1

            time.sleep(2)  # API 호출 간격

        print("\n" + "=" * 60)
        print(f"[완료] 변경: {success_count}건 | 실패: {fail_count}건")
        print("=" * 60)

        # 에러 분석
        if fail_count > 0:
            adjuster.analyze_errors()

    elif choice == "3":
        # 특정 상품번호 입력
        channel_no = input("네이버 채널상품번호 입력: ").strip()
        if not channel_no:
            print("취소됨")
            return

        product = {"naver_channel_no": channel_no, "name": "직접 입력"}
        success, msg = adjuster.process_product(product)
        print(f"\n결과: {msg}")

        # 에러 분석 및 개선 제안
        if not success:
            adjuster.analyze_errors()

    elif choice == "4":
        # 네이버에서 상품 목록 조회
        print("\n네이버 상품 목록 조회 중...")
        products = adjuster.naver_api.get_products(page=1, size=50)

        if not products:
            print("상품이 없습니다.")
            return

        print(f"\n{len(products)}개 상품 발견")
        print("-" * 60)

        for i, p in enumerate(products[:30], 1):
            origin = p.get("originProduct", {})
            smart = p.get("smartstoreChannelProduct", {})
            channel_no = p.get("channelProductNo", "")
            name = origin.get("name", "")[:40]
            cat_id = origin.get("leafCategoryId", "")
            cat_name = adjuster.get_category_name(cat_id)

            # 현재 카테고리에서 마지막 부분만 표시
            cat_short = cat_name.split('>')[-1].strip() if '>' in cat_name else cat_name
            print(f"  {i}. {name}")
            print(f"      [{channel_no}] 카테고리: {cat_short}")

        print()
        selection = input("처리할 상품 선택 (번호, 범위 1-5, all): ").strip().lower()

        if not selection:
            print("취소됨")
            return

        # 선택 파싱
        if selection in ['all', 'a']:
            selected = products[:30]
        elif '-' in selection:
            parts = selection.split('-')
            start = int(parts[0].strip()) - 1
            end = int(parts[1].strip())
            selected = products[start:end]
        elif ',' in selection:
            indices = [int(n.strip()) - 1 for n in selection.split(',')]
            selected = [products[i] for i in indices if 0 <= i < len(products)]
        else:
            try:
                idx = int(selection) - 1
                selected = [products[idx]] if 0 <= idx < len(products) else []
            except:
                selected = []

        if not selected:
            print("선택된 상품이 없습니다.")
            return

        print(f"\n{len(selected)}개 상품 카테고리 조정 시작...")

        success_count = 0
        fail_count = 0

        for p in selected:
            origin = p.get("originProduct", {})
            channel_no = p.get("channelProductNo", "")
            name = origin.get("name", "")

            product = {"naver_channel_no": channel_no, "name": name}
            success, msg = adjuster.process_product(product)
            if success and msg != "변경 불필요":
                success_count += 1
            elif not success:
                fail_count += 1

            time.sleep(2)

        print("\n" + "=" * 60)
        print(f"[완료] 변경: {success_count}건 | 실패: {fail_count}건")
        print("=" * 60)

        # 에러 분석
        if fail_count > 0:
            adjuster.analyze_errors()

    else:
        print("잘못된 선택입니다.")


if __name__ == "__main__":
    main()
