# -*- coding: utf-8 -*-
"""
네이버 쇼핑 API 모듈
====================
네이버 쇼핑에서 카테고리별 인기 상품 정보를 수집합니다.
"""

import os
import re
import time
import requests
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import List, Dict, Optional
from dotenv import load_dotenv

load_dotenv(override=True)


@dataclass
class ProductInfo:
    """상품 정보"""
    rank: int
    name: str
    price: int
    image_url: str
    link: str
    mall_name: str
    brand: str = ""
    category: str = ""
    features: List[str] = field(default_factory=list)
    blog_summary: str = ""
    review_count: int = 0
    rating: float = 0.0

    def to_dict(self) -> dict:
        return {
            "rank": self.rank,
            "name": self.name,
            "price": self.price,
            "image_url": self.image_url,
            "link": self.link,
            "mall_name": self.mall_name,
            "brand": self.brand,
            "category": self.category,
            "features": self.features,
            "blog_summary": self.blog_summary,
        }


class NaverShoppingAPI:
    """네이버 쇼핑 API 클래스"""

    # API 엔드포인트
    SHOPPING_API_URL = "https://openapi.naver.com/v1/search/shop.json"
    BLOG_API_URL = "https://openapi.naver.com/v1/search/blog.json"
    DATALAB_CATEGORIES_URL = "https://openapi.naver.com/v1/datalab/shopping/categories"

    # 카테고리 코드
    CATEGORIES = {
        "50000000": "패션의류",
        "50000001": "패션잡화",
        "50000002": "화장품/미용",
        "50000003": "디지털/가전",
        "50000004": "가구/인테리어",
        "50000005": "출산/육아",
        "50000006": "식품",
        "50000007": "스포츠/레저",
        "50000008": "생활/건강",
        "50000009": "여가/생활편의",
    }

    # 카테고리별 대표 키워드
    CATEGORY_KEYWORDS = {
        "50000000": ["패딩", "니트", "코트", "맨투맨", "후드티"],
        "50000001": ["가방", "지갑", "벨트", "모자", "시계"],
        "50000002": ["스킨케어", "선크림", "마스크팩", "립스틱", "파운데이션"],
        "50000003": ["무선이어폰", "공기청정기", "로봇청소기", "노트북", "스마트워치"],
        "50000004": ["소파", "침대", "책상", "조명", "수납장"],
        "50000005": ["기저귀", "분유", "유모차", "아기옷", "젖병"],
        "50000006": ["와인", "커피", "과일", "건강식품", "간식"],
        "50000007": ["골프", "등산화", "운동화", "요가매트", "자전거"],
        "50000008": ["가습기", "전기요", "안마기", "비타민", "영양제"],
        "50000009": ["캠핑", "여행가방", "텀블러", "우산", "핸드폰케이스"],
    }

    def __init__(self):
        self.client_id = os.getenv('NAVER_CLIENT_ID')
        self.client_secret = os.getenv('NAVER_CLIENT_SECRET')

        if not self.client_id or not self.client_secret:
            raise ValueError("NAVER_CLIENT_ID와 NAVER_CLIENT_SECRET 환경변수가 필요합니다.")

    def _get_headers(self) -> dict:
        """API 요청 헤더"""
        return {
            "X-Naver-Client-Id": self.client_id,
            "X-Naver-Client-Secret": self.client_secret,
            "Content-Type": "application/json"
        }

    def search_products(self, keyword: str, display: int = 10, sort: str = "sim") -> List[dict]:
        """
        네이버 쇼핑 API로 상품 검색

        Args:
            keyword: 검색 키워드
            display: 검색 결과 개수 (최대 100)
            sort: 정렬 방식 (sim: 정확도순, date: 날짜순, asc: 가격낮은순, dsc: 가격높은순)

        Returns:
            상품 리스트
        """
        params = {
            "query": keyword,
            "display": display,
            "sort": sort
        }

        try:
            response = requests.get(
                self.SHOPPING_API_URL,
                headers=self._get_headers(),
                params=params
            )

            if response.status_code == 200:
                data = response.json()
                return data.get('items', [])
            else:
                print(f"[ERROR] 쇼핑 API: {response.status_code} - {response.text}")
                return []
        except Exception as e:
            print(f"[ERROR] 상품 검색 실패: {e}")
            return []

    def get_top_products(self, keyword: str, top_n: int = 10) -> List[ProductInfo]:
        """
        키워드별 TOP N 상품 수집

        Args:
            keyword: 검색 키워드
            top_n: 수집할 상품 개수

        Returns:
            ProductInfo 리스트
        """
        print(f"\n[상품 수집] '{keyword}' TOP {top_n} 상품 수집 중...")

        items = self.search_products(keyword, display=top_n * 2)
        products = []

        for i, item in enumerate(items[:top_n], 1):
            # HTML 태그 제거
            name = re.sub(r'<[^>]+>', '', item.get('title', ''))

            product = ProductInfo(
                rank=i,
                name=name,
                price=int(item.get('lprice', 0)),
                image_url=item.get('image', ''),
                link=item.get('link', ''),
                mall_name=item.get('mallName', ''),
                brand=item.get('brand', ''),
                category=f"{item.get('category1', '')} > {item.get('category2', '')}"
            )
            products.append(product)
            print(f"  {i}위: {name[:40]}... ({product.price:,}원) - {product.mall_name}")

        return products

    def search_blog_reviews(self, product_name: str, display: int = 5) -> List[dict]:
        """
        네이버 블로그에서 상품 리뷰 검색

        Args:
            product_name: 상품명
            display: 검색 결과 개수

        Returns:
            블로그 리뷰 리스트
        """
        search_query = f"{product_name} 리뷰"

        params = {
            "query": search_query,
            "display": display,
            "sort": "sim"
        }

        try:
            response = requests.get(
                self.BLOG_API_URL,
                headers=self._get_headers(),
                params=params
            )

            if response.status_code == 200:
                data = response.json()
                blogs = []
                for item in data.get('items', []):
                    title = re.sub(r'<[^>]+>', '', item.get('title', ''))
                    description = re.sub(r'<[^>]+>', '', item.get('description', ''))
                    blogs.append({
                        'title': title,
                        'description': description,
                        'link': item.get('link', ''),
                        'blogger': item.get('bloggername', '')
                    })
                return blogs
            else:
                return []
        except Exception as e:
            print(f"[WARN] 블로그 검색 실패: {e}")
            return []

    def get_trending_categories(self, top_n: int = 5) -> List[dict]:
        """
        인기 카테고리 트렌드 분석

        Args:
            top_n: 반환할 카테고리 수

        Returns:
            카테고리별 트렌드 점수
        """
        print("\n[트렌드 분석] 카테고리별 인기도 분석 중...")

        end_date = datetime.now()
        start_date = end_date - timedelta(days=7)

        category_items = list(self.CATEGORIES.items())
        category_scores = []

        # 카테고리를 3개씩 나눠서 요청 (API 제한)
        for i in range(0, len(category_items), 3):
            chunk = category_items[i:i+3]
            body = {
                "startDate": start_date.strftime("%Y-%m-%d"),
                "endDate": end_date.strftime("%Y-%m-%d"),
                "timeUnit": "date",
                "category": [
                    {"name": name, "param": [code]}
                    for code, name in chunk
                ]
            }

            try:
                response = requests.post(
                    self.DATALAB_CATEGORIES_URL,
                    headers=self._get_headers(),
                    json=body
                )

                if response.status_code == 200:
                    data = response.json()
                    results = data.get('results', [])

                    for result in results:
                        cat_name = result.get('title', '')
                        cat_code = result.get('category', [''])[0]
                        data_points = result.get('data', [])

                        if data_points:
                            recent_avg = sum(d['ratio'] for d in data_points[-3:]) / min(3, len(data_points))
                            category_scores.append({
                                'name': cat_name,
                                'code': cat_code,
                                'score': recent_avg
                            })
                            print(f"  - {cat_name}: {recent_avg:.1f}")

                time.sleep(0.2)
            except Exception as e:
                print(f"[WARN] 카테고리 트렌드 분석 오류: {e}")

        # 점수순 정렬
        category_scores.sort(key=lambda x: x['score'], reverse=True)

        return category_scores[:top_n]

    def get_trending_keywords(self, top_n: int = 10) -> List[dict]:
        """
        인기 카테고리에서 트렌딩 키워드 수집

        Args:
            top_n: 반환할 키워드 수

        Returns:
            키워드 리스트
        """
        trending_categories = self.get_trending_categories(top_n=5)

        all_keywords = []
        for cat in trending_categories:
            cat_code = cat['code']
            cat_name = cat['name']
            cat_score = cat['score']

            keywords_for_cat = self.CATEGORY_KEYWORDS.get(cat_code, [])
            for kw in keywords_for_cat[:2]:
                all_keywords.append({
                    "keyword": kw,
                    "category": cat_name,
                    "category_code": cat_code,
                    "score": cat_score,
                })

        print(f"\n총 {len(all_keywords)}개 트렌딩 키워드 수집 완료")
        return all_keywords[:top_n]

    def get_seasonal_keywords(self) -> List[str]:
        """현재 시즌에 맞는 키워드 반환"""
        month = datetime.now().month

        seasonal = {
            1: ["신년", "새해", "겨울", "패딩", "난방"],
            2: ["발렌타인", "설날", "겨울", "보온"],
            3: ["봄", "신학기", "입학", "졸업"],
            4: ["봄", "아웃도어", "등산", "캠핑"],
            5: ["어버이날", "가정의달", "야외활동"],
            6: ["여름", "에어컨", "선풍기", "제습기"],
            7: ["여름", "휴가", "수영", "캠핑", "선크림"],
            8: ["여름", "휴가", "물놀이", "냉방"],
            9: ["가을", "추석", "단풍", "등산"],
            10: ["가을", "할로윈", "운동", "다이어트"],
            11: ["블랙프라이데이", "김장", "겨울준비"],
            12: ["크리스마스", "연말", "겨울", "선물"]
        }

        return seasonal.get(month, [])


# 테스트
if __name__ == "__main__":
    api = NaverShoppingAPI()

    # 트렌딩 키워드 수집
    keywords = api.get_trending_keywords(top_n=5)
    print("\n[트렌딩 키워드]")
    for kw in keywords:
        print(f"  - {kw['keyword']} ({kw['category']})")

    # 상품 검색 테스트
    if keywords:
        products = api.get_top_products(keywords[0]['keyword'], top_n=5)
