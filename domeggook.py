# -*- coding: utf-8 -*-
"""
도매꾹 상품 검색 모듈
======================
네이버 쇼핑 인기 상품과 도매꾹 상품을 매칭하여 사입 가능 여부를 확인합니다.

도매꾹 OpenAPI 사용:
- API 키 발급: http://openapi.domeggook.com/main/apikey
- API 문서: http://openapi.domeggook.com/main/reference/detail?api_no=68&version_no=2
"""

import os
import re
import time
import requests
from dataclasses import dataclass
from typing import List, Optional, Dict
from dotenv import load_dotenv

load_dotenv(override=True)


@dataclass
class DomeggookProduct:
    """도매꾹 상품 정보"""
    name: str
    price: int
    original_price: int = 0
    min_quantity: int = 1
    link: str = ""
    image_url: str = ""
    seller: str = ""
    brand: str = ""
    category: str = ""
    item_no: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "price": self.price,
            "original_price": self.original_price,
            "min_quantity": self.min_quantity,
            "link": self.link,
            "image_url": self.image_url,
            "seller": self.seller,
            "brand": self.brand,
            "item_no": self.item_no,
        }


class DomeggookSearcher:
    """도매꾹 상품 검색 클래스 (OpenAPI v4.1 사용)"""

    API_URL = "https://domeggook.com/ssl/api/"
    API_VERSION = "4.1"

    def __init__(self):
        self.api_key = os.getenv('DOMEGGOOK_API_KEY')
        if not self.api_key:
            print("[WARN] DOMEGGOOK_API_KEY가 설정되지 않았습니다.")
            print("       도매꾹 API 키 발급: http://openapi.domeggook.com/main/apikey")

    def search_products(
        self,
        keyword: str,
        max_results: int = 20,
        market: str = "dome"
    ) -> List[DomeggookProduct]:
        """
        도매꾹 OpenAPI로 상품 검색 (v4.1)

        Args:
            keyword: 검색 키워드
            max_results: 최대 결과 수 (1-200)
            market: dome(도매꾹) 또는 supply(도매매)

        Returns:
            DomeggookProduct 리스트
        """
        if not self.api_key:
            print(f"  [도매꾹] API 키 없음 - 검색 건너뜀")
            return []

        print(f"  [도매꾹] '{keyword}' 검색 중...")

        products = []

        try:
            params = {
                "ver": self.API_VERSION,
                "mode": "getItemList",
                "aid": self.api_key,
                "market": market,  # dome 또는 supply
                "om": "json",
                "kw": keyword,  # 검색어 (v4.1 파라미터)
                "sz": str(min(max_results, 200)),  # 페이지당 상품 수 (최대 200)
                "so": "ha",  # 인기순 (ha: 인기순, rd: 최신순)
            }

            response = requests.get(
                self.API_URL,
                params=params,
                timeout=15
            )

            if response.status_code != 200:
                print(f"    [WARN] API 요청 실패: HTTP {response.status_code}")
                return products

            data = response.json()

            # 에러 체크
            if 'errors' in data:
                error_msg = data['errors'].get('message', 'Unknown error')
                print(f"    [WARN] API 에러: {error_msg}")
                return products

            # 상품 파싱 (v4.1 응답 구조)
            items = data.get('domeggook', {}).get('list', {}).get('item', [])
            if not isinstance(items, list):
                items = [items] if items else []

            for item in items[:max_results]:
                try:
                    product = self._parse_api_item(item)
                    if product:
                        products.append(product)
                except Exception as e:
                    continue

            print(f"    [도매꾹] {len(products)}개 상품 발견")

        except requests.exceptions.Timeout:
            print(f"    [WARN] API 타임아웃")
        except requests.exceptions.RequestException as e:
            print(f"    [ERROR] API 요청 실패: {e}")
        except Exception as e:
            print(f"    [ERROR] 도매꾹 검색 실패: {e}")

        return products

    def _parse_api_item(self, item: dict) -> Optional[DomeggookProduct]:
        """API 응답에서 상품 정보 파싱 (v4.1 응답 구조)"""
        try:
            # v4.1 응답 필드명
            name = item.get('title', '')
            if not name:
                return None

            # 가격 파싱
            price = self._parse_price(item.get('price', 0))
            original_price = self._parse_price(item.get('orgPrice', 0))

            # 최소 주문 수량 (unitQty 필드 사용)
            min_qty = self._parse_price(item.get('unitQty', 1)) or self._parse_price(item.get('minQty', 1)) or 1

            # 상품 번호 (no 필드 사용)
            item_no = str(item.get('no', '') or item.get('itemNo', ''))

            # 링크 (url 필드 직접 사용, 없으면 생성)
            link = item.get('url', '')
            if not link and item_no:
                link = f"https://domeggook.com/{item_no}"

            # 이미지 (thumb 필드 사용)
            image_url = item.get('thumb', '') or item.get('thumbnail', '') or item.get('img', '')

            # 판매자 (id 필드 사용)
            seller = item.get('id', '') or item.get('sellerId', '') or item.get('seller', '')

            # 브랜드 (API 응답에서 추출, 없으면 상품명에서 추출)
            brand = item.get('brand', '') or item.get('brandName', '')
            if not brand:
                # 상품명 첫 단어를 브랜드로 추정
                words = name.split()
                if words:
                    brand = words[0]

            return DomeggookProduct(
                name=name,
                price=price,
                original_price=original_price,
                min_quantity=min_qty,
                link=link,
                image_url=image_url,
                seller=seller,
                brand=brand,
                item_no=item_no
            )

        except Exception as e:
            return None

    def _parse_price(self, price_value) -> int:
        """가격 값을 정수로 변환"""
        if isinstance(price_value, int):
            return price_value
        if isinstance(price_value, float):
            return int(price_value)
        if isinstance(price_value, str):
            numbers = re.findall(r'\d+', price_value.replace(',', ''))
            if numbers:
                return int(numbers[0])
        return 0

    def find_matching_product(
        self,
        product_name: str,
        target_price: int,
        min_margin: int = 10000
    ) -> Optional[DomeggookProduct]:
        """
        네이버 상품과 매칭되는 도매꾹 상품 찾기

        Args:
            product_name: 네이버 상품명
            target_price: 네이버 상품 가격
            min_margin: 최소 마진 금액 (기본 10,000원)

        Returns:
            매칭된 도매꾹 상품 또는 None
        """
        # 상품명에서 핵심 키워드 추출
        keywords = self._extract_keywords(product_name)

        if not keywords:
            return None

        # 여러 검색 전략 시도
        all_products = []

        # 전략 1: 상위 2개 키워드로 검색
        if len(keywords) >= 2:
            search_query = " ".join(keywords[:2])
            products = self.search_products(search_query, max_results=20)
            all_products.extend(products)

        # 전략 2: 첫번째 키워드만으로 검색 (더 넓은 검색)
        if keywords:
            products = self.search_products(keywords[0], max_results=20)
            for p in products:
                if p.item_no not in [ap.item_no for ap in all_products]:
                    all_products.append(p)

        if not all_products:
            return None

        # 가격 조건: 최소 1만원 이상 마진이 남아야 함
        max_price = target_price - min_margin

        matching_products = []
        for product in all_products:
            if product.price > 0 and product.price <= max_price:
                # 상품명 유사도 계산
                similarity = self._calculate_similarity(product_name, product.name)
                # 마진 금액 계산
                margin = target_price - product.price
                margin_rate = margin / target_price if target_price > 0 else 0

                # 유사도가 20% 이상이면 후보에 추가 (같은 상품인지 확인)
                if similarity >= 0.2:
                    # 종합 점수: 유사도 우선 + 마진 보너스
                    score = (similarity * 100000) + margin  # 유사도가 더 중요
                    matching_products.append((product, score, similarity, margin))

        if not matching_products:
            return None

        # 종합 점수 높은 순으로 정렬
        matching_products.sort(key=lambda x: x[1], reverse=True)

        return matching_products[0][0]

    def _extract_keywords(self, product_name: str) -> List[str]:
        """상품명에서 핵심 키워드 추출"""
        # 불필요한 문자 제거
        clean_name = re.sub(r'[\[\](){}]', ' ', product_name)
        clean_name = re.sub(r'[^\w\s가-힣]', ' ', clean_name)

        # 불용어
        stopwords = {
            '무료배송', '당일발송', '특가', '할인', '세일', '이벤트',
            '한정', '품절임박', '인기', '추천', '베스트', '신상',
            '개', '세트', '박스', '팩', '묶음', '단품', 'NEW', 'new',
            '정품', '국내', '해외', '배송', '빠른', '무료'
        }

        # 단어 분리
        words = clean_name.split()
        keywords = []

        for word in words:
            word = word.strip()
            if len(word) >= 2 and word not in stopwords:
                keywords.append(word)

        return keywords

    def _calculate_similarity(self, name1: str, name2: str) -> float:
        """두 상품명의 유사도 계산"""
        keywords1 = set(self._extract_keywords(name1))
        keywords2 = set(self._extract_keywords(name2))

        if not keywords1 or not keywords2:
            return 0.0

        # Jaccard 유사도
        intersection = len(keywords1 & keywords2)
        union = len(keywords1 | keywords2)

        return intersection / union if union > 0 else 0.0

    def _check_brand_match(self, naver_brand: str, naver_name: str, domeggook_name: str, domeggook_brand: str = "") -> str:
        """
        브랜드 일치 여부 확인

        Args:
            naver_brand: 네이버 상품 브랜드
            naver_name: 네이버 상품명
            domeggook_name: 도매꾹 상품명
            domeggook_brand: 도매꾹 상품 브랜드

        Returns:
            "일치", "불일치", "미확인" 중 하나
        """
        # 네이버 브랜드가 없으면 상품명에서 추출 시도
        naver_brand_clean = naver_brand.strip() if naver_brand else ""

        if not naver_brand_clean:
            # 상품명 첫 단어를 브랜드로 추정
            words = naver_name.split()
            if words:
                naver_brand_clean = words[0]

        if not naver_brand_clean:
            return "미확인"

        # 브랜드 정규화 (소문자, 공백 제거)
        naver_brand_lower = naver_brand_clean.lower().replace(" ", "")
        domeggook_name_lower = domeggook_name.lower().replace(" ", "")
        domeggook_brand_lower = (domeggook_brand or "").lower().replace(" ", "")

        # 1. 도매꾹 브랜드와 네이버 브랜드 직접 비교
        if domeggook_brand_lower and naver_brand_lower:
            if naver_brand_lower == domeggook_brand_lower:
                return "일치"
            if naver_brand_lower in domeggook_brand_lower or domeggook_brand_lower in naver_brand_lower:
                return "일치"

        # 2. 네이버 브랜드가 도매꾹 상품명에 포함되어 있는지 확인
        if len(naver_brand_lower) >= 2 and naver_brand_lower in domeggook_name_lower:
            return "일치"

        # 3. 도매꾹 브랜드가 네이버 상품명에 포함되어 있는지 확인
        if domeggook_brand_lower and len(domeggook_brand_lower) >= 2:
            naver_name_lower = naver_name.lower().replace(" ", "")
            if domeggook_brand_lower in naver_name_lower:
                return "일치"

        return "불일치"

    def match_products(
        self,
        naver_products: list,
        min_margin: int = 10000
    ) -> Dict[int, dict]:
        """
        네이버 상품 목록과 도매꾹 상품 매칭

        Args:
            naver_products: ProductInfo 리스트
            min_margin: 최소 마진 금액 (기본 10,000원)

        Returns:
            {rank: {name, price, link, margin}} 형태의 딕셔너리
        """
        print(f"\n[도매꾹 매칭] {len(naver_products)}개 상품 매칭 중... (최소 마진: {min_margin:,}원)")

        if not self.api_key:
            print("  [SKIP] API 키가 없어 매칭을 건너뜁니다.")
            return {}

        matches = {}

        for product in naver_products:
            time.sleep(0.3)  # API 요청 간격

            match = self.find_matching_product(
                product.name,
                product.price,
                min_margin
            )

            if match:
                margin = product.price - match.price
                margin_rate = (margin / product.price) * 100 if product.price > 0 else 0

                # 브랜드 일치 여부 확인 (네이버 브랜드와 도매꾹 브랜드 비교)
                brand_match = self._check_brand_match(product.brand, product.name, match.name, match.brand)

                matches[product.rank] = {
                    'name': match.name,
                    'price': match.price,
                    'link': match.link,
                    'brand': match.brand,
                    'margin': margin,
                    'margin_rate': margin_rate,
                    'min_quantity': match.min_quantity,
                    'item_no': match.item_no,
                    'brand_match': brand_match
                }

                print(f"  #{product.rank} 매칭! {match.name[:30]}... - {match.price:,}원 (마진: {margin:,}원, {margin_rate:.1f}%)")
            else:
                print(f"  #{product.rank} 매칭 없음")

        print(f"\n[도매꾹] 총 {len(matches)}개 상품 매칭 완료")

        return matches


# 테스트
if __name__ == "__main__":
    import sys
    import io
    if sys.platform == "win32":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

    searcher = DomeggookSearcher()

    if searcher.api_key:
        # API 키가 있으면 검색 테스트
        products = searcher.search_products("무선이어폰", max_results=5)

        print("\n[검색 결과]")
        for i, p in enumerate(products, 1):
            print(f"  {i}. {p.name[:40]}... - {p.price:,}원")
    else:
        print("\n도매꾹 API 키를 .env 파일에 설정해주세요:")
        print("DOMEGGOOK_API_KEY=your_api_key_here")
        print("\nAPI 키 발급: http://openapi.domeggook.com/main/apikey")
