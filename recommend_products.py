# -*- coding: utf-8 -*-
"""
네이버 인기 키워드 기반 도매꾹 상품 추천
- 네이버 쇼핑 인기 상품 분석
- 도매꾹에서 10,000원 미만 상품 매칭
- 이미지 라이선스 확인
"""
import sys
import io

if sys.platform == "win32" and not isinstance(sys.stdout, io.TextIOWrapper):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from naver_shopping import NaverShoppingAPI
from domeggook import DomeggookSearcher
from domeggook_image import DomeggookImageAPI
from product_register import get_domeggook_product


def check_image_license(item_no: str) -> bool:
    """도매꾹 상품의 이미지 사용 가능 여부 확인"""
    try:
        api = DomeggookImageAPI()
        detail = api.get_product_detail(item_no)

        if not detail:
            return False

        license_info = detail.get('desc', {}).get('license', {})
        usable = license_info.get('usable', False)

        return usable == True or usable == 'true' or str(usable).lower() == 'true'

    except Exception as e:
        return False


def recommend_products():
    """네이버 인기 키워드 기반 도매꾹 상품 추천"""

    print("=" * 70)
    print("네이버 인기 키워드 기반 도매꾹 상품 추천")
    print("=" * 70)

    # 저가 상품이 많은 카테고리 키워드
    keywords = [
        # 패션잡화 (저가 상품 많음)
        "헤어악세사리", "헤어핀", "머리끈",
        "귀걸이", "팔찌", "반지", "목걸이",
        "양말", "스카프",
        # 생활용품
        "핸드폰케이스", "키링", "파우치",
        "손거울", "텀블러", "에코백",
        # 문구/잡화
        "스티커", "메모지", "필통",
    ]

    domeggook = DomeggookSearcher()
    recommendations = []

    print("\n[1단계] 도매꾹 저가 상품 검색")
    print("-" * 70)

    for keyword in keywords:
        print(f"\n>> '{keyword}' 검색 중...")

        # 도매꾹 검색
        products = domeggook.search_products(keyword, max_results=20)

        for p in products:
            # 가격 필터: 1,000원 ~ 10,000원
            if p.price < 1000 or p.price >= 10000:
                continue

            # 최소주문수량 1개
            if p.min_quantity > 1:
                continue

            # 중복 제거
            if p.item_no in [r['item_no'] for r in recommendations]:
                continue

            recommendations.append({
                'keyword': keyword,
                'item_no': p.item_no,
                'name': p.name,
                'price': p.price,
                'min_quantity': p.min_quantity,
                'link': p.link,
            })

    print(f"\n[검색 결과] 총 {len(recommendations)}개 상품 발견 (10,000원 미만)")

    # 가격순 정렬
    recommendations.sort(key=lambda x: x['price'])

    print("\n" + "=" * 70)
    print("[2단계] 이미지 라이선스 및 상세정보 확인")
    print("=" * 70)

    final_recommendations = []

    for i, item in enumerate(recommendations[:30], 1):  # 상위 30개만 검토
        print(f"\n[{i}/30] {item['name'][:35]}... ({item['price']:,}원)")

        # 이미지 라이선스 확인
        if not check_image_license(item['item_no']):
            print(f"       -> 이미지 사용 불가 - 제외")
            continue

        print(f"       -> 이미지 사용 가능!")

        # 상세정보 조회
        detail = get_domeggook_product(item['item_no'])
        if not detail:
            print(f"       -> 상세정보 조회 실패")
            continue

        if not detail.image_url:
            print(f"       -> 대표 이미지 없음")
            continue

        # 품절 체크
        if detail.options:
            soldout_count = sum(1 for opt in detail.options if opt.is_soldout)
            soldout_ratio = soldout_count / len(detail.options)
            if soldout_ratio > 0.5:
                print(f"       -> 품절 비율 높음 ({soldout_ratio*100:.0f}%)")
                continue

        # 판매가 및 마진 계산
        sale_price = int(detail.price * 1.5)
        margin = sale_price - detail.price
        margin_rate = (margin / sale_price) * 100

        final_recommendations.append({
            'keyword': item['keyword'],
            'item_no': item['item_no'],
            'name': detail.name,
            'domeggook_price': detail.price,
            'sale_price': sale_price,
            'margin': margin,
            'margin_rate': margin_rate,
            'option_count': len(detail.options),
            'detail_images': len(detail.detail_images),
            'link': f"https://domeggook.com/{item['item_no']}"
        })

        print(f"       -> 추천! 도매가 {detail.price:,}원 -> 판매가 {sale_price:,}원 (마진 {margin:,}원)")

        # 10개 추천 완료
        if len(final_recommendations) >= 10:
            break

    # 결과 출력
    print("\n")
    print("=" * 70)
    print("                      [추천 상품 TOP 10]")
    print("=" * 70)

    if not final_recommendations:
        print("\n조건에 맞는 상품을 찾지 못했습니다.")
        return []

    for i, item in enumerate(final_recommendations, 1):
        print(f"\n{i}. [{item['keyword']}] {item['name'][:40]}...")
        print(f"   도매꾹 번호: {item['item_no']}")
        print(f"   도매가: {item['domeggook_price']:,}원 -> 판매가: {item['sale_price']:,}원")
        print(f"   예상 마진: {item['margin']:,}원 ({item['margin_rate']:.1f}%)")
        print(f"   옵션: {item['option_count']}개, 상세이미지: {item['detail_images']}개")
        print(f"   링크: {item['link']}")

    print("\n" + "=" * 70)
    print(f"총 {len(final_recommendations)}개 상품 추천 완료")
    print("=" * 70)

    return final_recommendations


if __name__ == "__main__":
    recommendations = recommend_products()
