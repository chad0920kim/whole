# -*- coding: utf-8 -*-
"""가습기 상품 검색"""
import sys
import io

if sys.platform == "win32" and not isinstance(sys.stdout, io.TextIOWrapper):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from domeggook import DomeggookSearcher
from domeggook_image import DomeggookImageAPI
from product_register import get_domeggook_product


def check_image_license(item_no: str) -> bool:
    """이미지 사용 가능 여부 확인"""
    try:
        api = DomeggookImageAPI()
        detail = api.get_product_detail(item_no)
        if not detail:
            return False
        license_info = detail.get('desc', {}).get('license', {})
        usable = license_info.get('usable', False)
        return usable == True or usable == 'true' or str(usable).lower() == 'true'
    except:
        return False


def search_humidifiers():
    """2~3만원대 가습기 검색"""
    print("=" * 70)
    print("도매꾹 가습기 검색 (20,000원 ~ 35,000원)")
    print("=" * 70)

    searcher = DomeggookSearcher()
    keywords = ["가습기", "미니가습기", "무선가습기", "대용량가습기"]

    all_products = []

    for keyword in keywords:
        print(f"\n>> '{keyword}' 검색 중...")
        products = searcher.search_products(keyword, max_results=30)

        for p in products:
            # 가격 필터: 20,000원 ~ 35,000원
            if p.price < 20000 or p.price > 35000:
                continue
            # 최소주문수량 1개
            if p.min_quantity > 1:
                continue
            # 중복 제거
            if p.item_no in [x.item_no for x in all_products]:
                continue
            all_products.append(p)

    print(f"\n[검색 결과] {len(all_products)}개 상품 발견")

    # 가격순 정렬
    all_products.sort(key=lambda x: x.price)

    print("\n" + "=" * 70)
    print("이미지 라이선스 확인 중...")
    print("=" * 70)

    recommendations = []

    for i, p in enumerate(all_products[:20], 1):  # 상위 20개만 검토
        print(f"\n[{i}/20] {p.name[:40]}... ({p.price:,}원)")

        # 이미지 라이선스 확인
        if not check_image_license(p.item_no):
            print(f"       -> 이미지 사용 불가")
            continue
        print(f"       -> 이미지 사용 가능!")

        # 상세정보 조회
        detail = get_domeggook_product(p.item_no)
        if not detail:
            print(f"       -> 상세정보 조회 실패")
            continue

        if not detail.image_url:
            print(f"       -> 대표 이미지 없음")
            continue

        # 품절 체크
        if detail.options:
            soldout_count = sum(1 for opt in detail.options if opt.is_soldout)
            if len(detail.options) > 0:
                soldout_ratio = soldout_count / len(detail.options)
                if soldout_ratio > 0.5:
                    print(f"       -> 품절 비율 높음 ({soldout_ratio*100:.0f}%)")
                    continue

        # 판매가 및 마진 계산 (1.5배)
        sale_price = int(detail.price * 1.5)
        margin = sale_price - detail.price
        margin_rate = (margin / sale_price) * 100

        recommendations.append({
            'item_no': p.item_no,
            'name': detail.name,
            'domeggook_price': detail.price,
            'sale_price': sale_price,
            'margin': margin,
            'margin_rate': margin_rate,
            'option_count': len(detail.options),
            'detail_images': len(detail.detail_images),
            'link': f"https://domeggook.com/{p.item_no}"
        })

        print(f"       -> 추천! 도매가 {detail.price:,}원 -> 판매가 {sale_price:,}원")

        # 10개 추천 완료
        if len(recommendations) >= 10:
            break

    # 결과 출력
    print("\n")
    print("=" * 70)
    print("                    [가습기 추천 상품]")
    print("=" * 70)

    if not recommendations:
        print("\n조건에 맞는 상품을 찾지 못했습니다.")
        return []

    for i, item in enumerate(recommendations, 1):
        print(f"\n{i}. {item['name'][:50]}...")
        print(f"   도매꾹 번호: {item['item_no']}")
        print(f"   도매가: {item['domeggook_price']:,}원 -> 판매가: {item['sale_price']:,}원")
        print(f"   예상 마진: {item['margin']:,}원 ({item['margin_rate']:.1f}%)")
        print(f"   옵션: {item['option_count']}개, 상세이미지: {item['detail_images']}개")
        print(f"   링크: {item['link']}")

    print("\n" + "=" * 70)
    print(f"총 {len(recommendations)}개 상품 추천")
    print("=" * 70)

    return recommendations


if __name__ == "__main__":
    search_humidifiers()
