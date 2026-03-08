# -*- coding: utf-8 -*-
"""
도매꾹 상위 상품 500개 일괄 등록
================================
- 도매꾹 인기순(판매량순) 상위 500개 상품 조회
- 최소구매수량 1개 필터링
- 기등록 상품 제외
- 이미지 사용 허용 상품만
- 마진 10% 적용
- 배송비 정책: 무료배송 아니면 3,000원 / 단 마진 3,000원 이상이면 무료배송

사용법: python @bulk_register_top500.py
"""

import sys
import io
import time
from typing import List, Dict, Set, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime

# Windows 콘솔 인코딩 설정
if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, 'buffer') and not isinstance(sys.stdout, io.TextIOWrapper):
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    except:
        pass

try:
    from domeggook_image import DomeggookImageAPI
    from naver_commerce import NaverCommerceAPI
    from google_sheets import GoogleSheetsManager
    from run_register_by_link import (
        get_domeggook_product,
        register_to_naver,
        find_category,
        DomeggookProduct
    )
except ImportError as e:
    print(f"[ERROR] 필수 모듈을 찾을 수 없습니다: {e}")
    sys.exit(1)

# ============================================================================
# 설정값
# ============================================================================
MARGIN_RATE = 1.1  # 10% 마진
TARGET_COUNT = 500  # 등록 목표 개수
BATCH_SIZE = 50  # API 한번에 조회할 개수
FREE_SHIPPING_MARGIN = 3000  # 이 금액 이상 마진이면 무료배송
DEFAULT_DELIVERY_FEE = 3000  # 기본 배송비

# 카테고리별 검색 키워드 (각 카테고리에서 균등하게 수집)
CATEGORY_KEYWORDS = {
    "패션의류": ["패딩", "니트", "코트", "맨투맨", "후드티", "청바지", "원피스", "자켓", "티셔츠", "레깅스"],
    "패션잡화": ["가방", "지갑", "벨트", "모자", "시계", "목걸이", "귀걸이", "스카프", "장갑"],
    "생활용품": ["텀블러", "우산", "핸드폰케이스", "무드등", "수건", "슬리퍼", "양말", "담요"],
    "주방용품": ["밀폐용기", "프라이팬", "냄비", "식기", "수저", "컵", "도마", "주방수납"],
    "디지털": ["무선이어폰", "충전기", "보조배터리", "블루투스스피커", "마우스패드", "케이블"],
    "뷰티": ["스킨케어", "선크림", "마스크팩", "립스틱", "클렌징", "화장솜"],
    "반려동물": ["강아지옷", "고양이장난감", "펫간식", "펫용품", "펫패드"],
    "사무문구": ["필기구", "노트", "파일", "데스크정리", "스탠드", "메모지"],
}


# NOTE: AI 카테고리 분류는 run_register_by_link.py의 find_category 함수에 통합됨
# AICategoryClassifier 클래스는 더 이상 필요하지 않음 (find_category가 AI 분류 자동 수행)


class _DeprecatedAICategoryClassifier:
    """AI 기반 카테고리 분류기"""

    def __init__(self, naver_api):
        self.naver_api = naver_api
        self.openai_client = self._init_openai()
        self._category_cache = None
        self._leaf_categories = None

    def _init_openai(self):
        """OpenAI 클라이언트 초기화"""
        if not OPENAI_AVAILABLE:
            return None

        api_key = os.getenv('OPENAI_API_KEY')
        if api_key:
            return OpenAI(api_key=api_key)
        return None

    def load_categories(self):
        """네이버 카테고리 목록 로드"""
        if self._category_cache is not None:
            return

        categories = self.naver_api.get_categories()
        if categories:
            self._category_cache = categories
            self._leaf_categories = [c for c in categories if c.get('last') is True]
        else:
            self._category_cache = []
            self._leaf_categories = []

    def classify_with_ai(self, product_name: str, domeggook_category: str = "") -> str:
        """AI로 상품 카테고리 분류"""
        if not self.openai_client:
            return None

        try:
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
            category_hint = f"\n도매꾹 카테고리: {domeggook_category}" if domeggook_category else ""

            prompt = f"""다음 상품 정보를 분석하여 가장 적합한 카테고리를 추천해주세요.

[상품 정보]
상품명: {product_name}{category_hint}

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
                    {"role": "system", "content": "상품 카테고리 분류 전문가입니다. 상품명을 분석하여 가장 적합한 카테고리를 '대분류 > 중분류 > 소분류' 형식으로 정확히 분류합니다."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=100,
                temperature=0.1
            )

            result = response.choices[0].message.content.strip()
            return result

        except Exception as e:
            print(f"    [AI] 분류 실패: {e}")
            return None

    def find_matching_category(self, ai_category: str) -> str:
        """AI 추천 카테고리에 맞는 네이버 카테고리 ID 찾기"""
        import re

        if not self._leaf_categories or not ai_category:
            return None

        # AI 결과에서 키워드 추출
        parts = [p.strip() for p in ai_category.split('>')]
        keywords = []
        for part in parts:
            sub_parts = re.split(r'[/,()]', part)
            for sp in sub_parts:
                sp = sp.strip()
                if sp and len(sp) >= 2:
                    keywords.append(sp.lower())

        if not keywords:
            return None

        # 키워드 동의어 매핑
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

            # 제외 카테고리 필터링
            if any(ex.lower() in whole_name for ex in EXCLUDED_CATEGORY_KEYWORDS):
                continue

            cat_parts = [p.strip().lower() for p in whole_name.split('>')]

            # 점수 계산
            score = 0
            matched_keywords = []

            for i, keyword in enumerate(keywords):
                synonyms = keyword_synonyms.get(keyword, [keyword])

                for cat_part in cat_parts:
                    is_match = False

                    if cat_part == keyword:
                        is_match = True
                    elif any(syn in cat_part or cat_part in syn for syn in synonyms):
                        is_match = True
                    elif cat_part.endswith(keyword) and len(cat_part) > len(keyword):
                        prefix = cat_part[:-len(keyword)]
                        if prefix not in ['바지', '조개', '해산', '고등어', '멸치']:
                            is_match = True

                    if is_match:
                        position_score = max(10 - i * 2, 2)
                        score += position_score
                        matched_keywords.append(keyword)
                        break

            if score > 0:
                depth = len(cat_parts)
                total_score = score * 10 + depth
                all_matches.append((cat, total_score, matched_keywords))

        if all_matches:
            all_matches.sort(key=lambda x: x[1], reverse=True)
            best_cat = all_matches[0][0]
            return best_cat.get('id')

        return None

    def get_category_id(self, product_name: str, domeggook_category: str = "") -> str:
        """상품명과 도매꾹 카테고리로 네이버 카테고리 ID 찾기"""
        self.load_categories()

        # AI로 카테고리 분류
        ai_category = self.classify_with_ai(product_name, domeggook_category)
        if not ai_category:
            return None

        print(f"    [AI] 추천: {ai_category}")

        # 네이버 카테고리 매칭
        category_id = self.find_matching_category(ai_category)
        if category_id:
            # 매칭된 카테고리명 출력
            for cat in self._leaf_categories:
                if str(cat.get('id')) == str(category_id):
                    cat_short = cat.get('wholeCategoryName', '').split('>')[-1].strip()
                    print(f"    [AI] 매칭: {cat_short} ({category_id})")
                    break

        return category_id


@dataclass
class RegistrationResult:
    """등록 결과"""
    success: int = 0
    failed: int = 0
    skipped: int = 0
    registered_items: List[Dict] = None
    failed_items: List[Dict] = None

    def __post_init__(self):
        if self.registered_items is None:
            self.registered_items = []
        if self.failed_items is None:
            self.failed_items = []


class BulkProductRegistrar:
    """상위 상품 일괄 등록 클래스"""

    def __init__(self):
        self.domeggook = DomeggookImageAPI()
        self.naver_commerce = None
        self.sheets = None
        self.registered_items: Set[str] = set()

    def _init_naver_api(self):
        """네이버 API 초기화"""
        if not self.naver_commerce:
            print("[INFO] 네이버 커머스 API 초기화...")
            self.naver_commerce = NaverCommerceAPI()

    def _init_sheets(self):
        """구글시트 초기화"""
        if not self.sheets:
            self.sheets = GoogleSheetsManager()

    def _load_registered_items(self):
        """구글시트에서 기등록 상품번호 로드"""
        if self.registered_items:
            return

        try:
            self._init_sheets()
            data = self.sheets.sheets_service.spreadsheets().values().get(
                spreadsheetId=self.sheets.sheet_id,
                range="registered_products!B:B"  # B열: 도매꾹번호
            ).execute()

            values = data.get('values', [])
            for row in values[1:]:  # 헤더 제외
                if row and row[0]:
                    self.registered_items.add(str(row[0]))

            print(f"[INFO] 기등록 상품 {len(self.registered_items)}개 로드됨")
        except Exception as e:
            print(f"[WARN] 기등록 상품 로드 실패: {e}")

    def get_category_products(self, category_name: str, keywords: List[str], target_count: int) -> List[Dict]:
        """
        단일 카테고리에서 상품 수집

        Args:
            category_name: 카테고리명
            keywords: 검색 키워드 리스트
            target_count: 목표 상품 수

        Returns:
            상품 정보 리스트
        """
        import requests

        collected = []
        collected_item_nos = set()

        print(f"\n{'='*70}")
        print(f"[수집] {category_name} (목표: {target_count}개)")
        print("="*70)

        for keyword in keywords:
            if len(collected) >= target_count:
                break

            keyword_target = min(10, target_count - len(collected))
            print(f"\n  [키워드] '{keyword}' 검색 중...")

            try:
                params = {
                    'ver': '4.1',
                    'mode': 'getItemList',
                    'aid': self.domeggook.api_key,
                    'om': 'json',
                    'market': 'dome',
                    'sz': 20,
                    'so': 'ha',
                    'kw': keyword
                }

                # API 호출 (재시도 로직 포함)
                data = None
                for retry in range(3):
                    try:
                        response = requests.get(self.domeggook.API_URL, params=params, timeout=30)
                        response.encoding = 'utf-8'
                        data = response.json()
                        break
                    except Exception as api_err:
                        if retry < 2:
                            wait_time = 30 * (retry + 1)
                            print(f"    [API 제한] {wait_time}초 대기 후 재시도... ({retry+1}/3)")
                            time.sleep(wait_time)
                        else:
                            raise api_err

                if not data:
                    continue

                domeggook = data.get('domeggook', {})
                items = domeggook.get('list', {}).get('item', [])

                if not items:
                    print(f"    검색 결과 없음")
                    continue

                if isinstance(items, dict):
                    items = [items]

                keyword_collected = 0

                for item in items:
                    if keyword_collected >= keyword_target:
                        break
                    if len(collected) >= target_count:
                        break

                    item_no = str(item.get('no', ''))
                    if not item_no:
                        continue

                    # 중복 체크
                    if item_no in collected_item_nos:
                        continue

                    # 기등록 상품 제외
                    if item_no in self.registered_items:
                        continue

                    # 상세 조회
                    detail = self.domeggook.get_product_detail(item_no)
                    if not detail:
                        continue

                    # MOQ 확인
                    qty_info = detail.get('qty', {})
                    min_qty = 1
                    if isinstance(qty_info, dict):
                        try:
                            min_qty = int(qty_info.get('domeMoq', 1) or 1)
                        except:
                            min_qty = 1

                    if min_qty > 1:
                        continue

                    # 이미지 사용 허용 확인
                    license_info = detail.get('desc', {}).get('license', {})
                    usable = license_info.get('usable', False)
                    if usable != True and usable != 'true':
                        continue

                    # 가격 정보
                    basis = detail.get('basis', {})
                    price_info = detail.get('price', {})

                    price = 0
                    dome_price = price_info.get('dome', 0)
                    if isinstance(dome_price, str) and '|' in dome_price:
                        first_price = dome_price.split('|')[0]
                        if '+' in first_price:
                            price = int(first_price.split('+')[1])
                    else:
                        try:
                            price = int(dome_price or 0)
                        except:
                            price = 0

                    if price <= 0:
                        continue

                    # 마진 10% 적용 (100원 단위 올림)
                    margin_price = int(price * MARGIN_RATE)
                    margin_price = ((margin_price + 99) // 100) * 100
                    margin = margin_price - price

                    # 배송비 정보
                    deli = detail.get('deli', {})
                    original_delivery_fee = 0
                    if isinstance(deli, dict):
                        dome_deli = deli.get('dome', {})
                        if isinstance(dome_deli, dict):
                            original_delivery_fee = int(dome_deli.get('fee', 0) or 0)

                    # 도매꾹 카테고리 정보 추출
                    domeggook_cat = detail.get('category', {})
                    domeggook_category_name = ''
                    if isinstance(domeggook_cat, dict):
                        domeggook_category_name = domeggook_cat.get('name', '')

                    # 수집
                    collected.append({
                        'item_no': item_no,
                        'name': basis.get('title', item.get('title', '')),
                        'price': price,
                        'margin_price': margin_price,
                        'margin': margin,
                        'min_qty': min_qty,
                        'original_delivery_fee': original_delivery_fee,
                        'category_name': category_name,
                        'keyword': keyword,
                        'license_msg': license_info.get('msg', ''),
                        'domeggook_category': domeggook_category_name  # 도매꾹 카테고리명
                    })
                    collected_item_nos.add(item_no)
                    keyword_collected += 1

                    cat_display = f" [{domeggook_category_name[:15]}]" if domeggook_category_name else ""
                    print(f"    [{len(collected):3d}] {item_no}: {basis.get('title', '')[:30]}... "
                          f"({price:,}→{margin_price:,}원){cat_display}")

                    # API 호출 제한 대응
                    time.sleep(0.5)

            except Exception as e:
                print(f"    [ERROR] 검색 실패: {e}")
                continue

        print(f"\n  → {category_name}: {len(collected)}개 수집 완료")
        return collected

    def register_product(self, product_info: Dict) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        단일 상품 등록

        Args:
            product_info: 상품 정보 딕셔너리

        Returns:
            (성공여부, 채널상품번호, 에러메시지)
        """
        item_no = product_info['item_no']

        try:
            # 상품 정보 조회 (10% 마진) - API 제한 대응 재시도 로직
            product = None
            for retry in range(3):
                product = get_domeggook_product(item_no, margin_rate=MARGIN_RATE)
                if product:
                    break
                print(f"  [RETRY] {retry+1}/3 - API 호출 제한, 10초 대기 후 재시도...")
                time.sleep(10)

            if not product:
                return False, None, "상품 정보 조회 실패"

            self._init_naver_api()

            # 카테고리 자동 매칭 (find_category가 AI 분류를 자동으로 수행)
            domeggook_category = product_info.get('domeggook_category', '')
            category_id = find_category(self.naver_commerce, product.name, domeggook_category)

            if not category_id:
                return False, None, "카테고리 매칭 실패"

            # 등록 (비전시)
            channel_no, origin_no, final_price = register_to_naver(
                product=product,
                naver_api=self.naver_commerce,
                category_id=category_id,
                display=False,
                check_min_quantity=False
            )

            if channel_no:
                # 구글시트 저장
                try:
                    self._init_sheets()

                    option_summary = f"{len(product.options)}개 옵션" if product.options else "옵션없음"

                    self.sheets.save_registered_product(
                        domeggook_no=item_no,
                        naver_channel_no=channel_no,
                        naver_origin_no=origin_no,
                        name=product.name,
                        domeggook_price=product.price,
                        naver_price=final_price,
                        options=option_summary,
                        min_quantity=product.min_quantity,
                        status="비전시",
                        margin_rate=10.0  # 10% 마진
                    )

                    # 기등록 목록에 추가
                    self.registered_items.add(item_no)

                except Exception as e:
                    print(f"  [WARN] 구글시트 저장 실패: {e}")

                return True, channel_no, None
            else:
                return False, None, "네이버 등록 API 실패"

        except Exception as e:
            return False, None, str(e)

    def bulk_register(self, products: List[Dict]) -> RegistrationResult:
        """
        상품 일괄 등록

        Args:
            products: 등록할 상품 리스트

        Returns:
            RegistrationResult
        """
        result = RegistrationResult()
        total = len(products)

        print("\n" + "=" * 70)
        print("[2단계] 상품 일괄 등록")
        print("=" * 70)
        print(f"  등록 대상: {total}개")
        print(f"  마진율: {(MARGIN_RATE - 1) * 100:.0f}%")
        print(f"  배송비: 마진 {FREE_SHIPPING_MARGIN:,}원 이상 → 무료배송, 아니면 {DEFAULT_DELIVERY_FEE:,}원")
        print()

        start_time = datetime.now()

        for i, product_info in enumerate(products, 1):
            item_no = product_info['item_no']
            name = product_info['name'][:35]

            print(f"\n[{i}/{total}] 등록 중: {item_no} - {name}...")

            # 이미 등록된 상품 다시 체크 (동시 실행 대비)
            if item_no in self.registered_items:
                print(f"  → 이미 등록됨 (SKIP)")
                result.skipped += 1
                continue

            success, channel_no, error = self.register_product(product_info)

            if success:
                result.success += 1
                result.registered_items.append({
                    'item_no': item_no,
                    'name': product_info['name'],
                    'channel_no': channel_no,
                    'price': product_info['price'],
                    'margin_price': product_info['margin_price']
                })
                print(f"  → 성공! (채널상품번호: {channel_no})")
            else:
                result.failed += 1
                result.failed_items.append({
                    'item_no': item_no,
                    'name': product_info['name'],
                    'error': error
                })
                print(f"  → 실패: {error}")

            # 진행 상황 출력 (10개마다)
            if i % 10 == 0:
                elapsed = (datetime.now() - start_time).total_seconds()
                avg_time = elapsed / i
                remaining = avg_time * (total - i)
                print(f"\n  === 진행: {i}/{total} | 성공: {result.success} | 실패: {result.failed} | "
                      f"예상 남은 시간: {remaining/60:.1f}분 ===\n")

            # API 호출 간격 (도매꾹 분당 180회 제한 대응)
            time.sleep(2)

        end_time = datetime.now()
        elapsed_time = (end_time - start_time).total_seconds()

        return result

    def print_summary(self, result: RegistrationResult, elapsed_time: float):
        """결과 요약 출력"""
        print("\n" + "=" * 70)
        print("[등록 완료]")
        print("=" * 70)
        print(f"  총 처리: {result.success + result.failed + result.skipped}개")
        print(f"  성공: {result.success}개")
        print(f"  실패: {result.failed}개")
        print(f"  스킵: {result.skipped}개")
        print(f"  소요 시간: {elapsed_time/60:.1f}분 ({elapsed_time:.0f}초)")
        print()

        if result.registered_items:
            print("[성공 상품 목록]")
            print("-" * 70)
            for item in result.registered_items[:20]:  # 상위 20개만 출력
                print(f"  {item['item_no']}: {item['name'][:40]}... "
                      f"→ {item['channel_no']}")
            if len(result.registered_items) > 20:
                print(f"  ... 외 {len(result.registered_items) - 20}개")
            print()

        if result.failed_items:
            print("[실패 상품 목록]")
            print("-" * 70)
            for item in result.failed_items[:10]:  # 상위 10개만 출력
                print(f"  {item['item_no']}: {item['error']}")
            if len(result.failed_items) > 10:
                print(f"  ... 외 {len(result.failed_items) - 10}개")
            print()


def main():
    print("=" * 70)
    print("도매꾹 상위 상품 카테고리별 일괄 등록")
    print("=" * 70)
    print()
    print(f"  - 마진율: {(MARGIN_RATE - 1) * 100:.0f}%")
    print(f"  - MOQ 1개 상품만")
    print(f"  - 이미지 사용 허용 상품만")
    print(f"  - 기등록 상품 제외")
    print(f"  - 배송비: 마진 ≥ {FREE_SHIPPING_MARGIN:,}원이면 무료, 아니면 {DEFAULT_DELIVERY_FEE:,}원")
    print()

    # 카테고리별 목표 수량
    num_categories = len(CATEGORY_KEYWORDS)
    per_category = TARGET_COUNT // num_categories
    print(f"  총 목표: {TARGET_COUNT}개")
    print(f"  카테고리: {num_categories}개")
    print(f"  카테고리당: ~{per_category}개")
    print()

    # 카테고리 목록 출력
    print("[카테고리 목록]")
    for i, cat in enumerate(CATEGORY_KEYWORDS.keys(), 1):
        print(f"  {i}. {cat}")
    print()

    # 확인
    confirm = input("카테고리별로 수집→등록을 진행합니다. 시작할까요? (y/Enter=시작, n=취소): ").strip().lower()
    if confirm == 'n':
        print("취소되었습니다.")
        return

    registrar = BulkProductRegistrar()

    # 기등록 상품 로드
    registrar._load_registered_items()

    # 전체 결과 집계
    total_result = RegistrationResult()
    total_start_time = datetime.now()

    # 카테고리별 처리
    for cat_idx, (category_name, keywords) in enumerate(CATEGORY_KEYWORDS.items(), 1):
        print("\n" + "#" * 70)
        print(f"# [{cat_idx}/{num_categories}] {category_name}")
        print("#" * 70)

        # 1단계: 해당 카테고리 상품 수집
        products = registrar.get_category_products(category_name, keywords, per_category)

        if not products:
            print(f"\n  → {category_name}: 등록할 상품 없음, 다음 카테고리로...")
            continue

        # 2단계: 수집된 상품 등록
        print(f"\n[등록] {category_name} - {len(products)}개 상품 등록 시작")
        print("-" * 70)

        cat_result = registrar.bulk_register(products)

        # 결과 집계
        total_result.success += cat_result.success
        total_result.failed += cat_result.failed
        total_result.skipped += cat_result.skipped
        total_result.registered_items.extend(cat_result.registered_items)
        total_result.failed_items.extend(cat_result.failed_items)

        print(f"\n  → {category_name} 완료: 성공 {cat_result.success}개, 실패 {cat_result.failed}개")

        # 다음 카테고리 전 대기 (API 제한 완화)
        if cat_idx < num_categories:
            print(f"\n  [대기] 다음 카테고리 진행 전 30초 대기...")
            time.sleep(30)

    # 최종 결과 출력
    total_elapsed = (datetime.now() - total_start_time).total_seconds()
    registrar.print_summary(total_result, total_elapsed)

    print("\n완료!")


if __name__ == "__main__":
    main()
