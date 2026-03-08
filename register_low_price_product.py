# -*- coding: utf-8 -*-
"""
도매꾹 저가 상품 검색 및 네이버 등록
- 10,000원 미만 상품 검색
- 조건에 맞는 상품 1개 선정
- 네이버 스마트스토어에 등록
"""
import sys
import io
import asyncio

if sys.platform == "win32" and not isinstance(sys.stdout, io.TextIOWrapper):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from domeggook import DomeggookSearcher
from domeggook_image import DomeggookImageAPI
from product_register import get_domeggook_product, register_to_naver
from google_sheets import GoogleSheetsManager


def search_low_price_products(max_price: int = 10000, keywords: list = None) -> list:
    """
    도매꾹에서 저가 상품 검색

    Args:
        max_price: 최대 가격 (기본 10,000원)
        keywords: 검색 키워드 리스트

    Returns:
        조건에 맞는 상품 리스트
    """
    if keywords is None:
        keywords = ["헤어악세사리", "핸드폰케이스", "양말", "귀걸이", "팔찌"]

    searcher = DomeggookSearcher()
    all_products = []

    print("=" * 60)
    print(f"도매꾹 저가 상품 검색 (최대 {max_price:,}원)")
    print("=" * 60)

    for keyword in keywords:
        products = searcher.search_products(keyword, max_results=30)

        # 가격 필터링
        for p in products:
            if 1000 <= p.price < max_price:  # 1,000원 ~ 10,000원 미만
                # 최소주문수량 1개인 상품만
                if p.min_quantity <= 1:
                    # 중복 제거
                    if p.item_no not in [x.item_no for x in all_products]:
                        all_products.append(p)

    # 가격순 정렬
    all_products.sort(key=lambda x: x.price)

    print(f"\n[검색 결과] {len(all_products)}개 상품 발견")
    return all_products


def check_image_license(item_no: str) -> bool:
    """
    도매꾹 상품의 이미지 사용 가능 여부 확인

    Args:
        item_no: 도매꾹 상품번호

    Returns:
        이미지 사용 가능하면 True
    """
    try:
        api = DomeggookImageAPI()
        detail = api.get_product_detail(item_no)

        if not detail:
            return False

        license_info = detail.get('desc', {}).get('license', {})
        usable = license_info.get('usable', False)

        return usable == True or usable == 'true' or str(usable).lower() == 'true'

    except Exception as e:
        print(f"    [WARN] 라이선스 확인 오류: {e}")
        return False


def select_best_product(products: list) -> dict:
    """
    등록하기 좋은 상품 1개 선정

    조건:
    - 가격: 3,000원 ~ 8,000원
    - 마진율 50% 이상 가능
    - 옵션이 있으면 좋음
    - 이미지 사용 가능 (license.usable = true)
    """
    print("\n" + "=" * 60)
    print("상품 선정 중...")
    print("=" * 60)

    candidates = []

    for p in products:
        # 가격 범위 체크 (3,000원 ~ 8,000원)
        if p.price < 3000 or p.price > 8000:
            continue

        print(f"\n검토 중: {p.name[:30]}... ({p.item_no})")

        # 이미지 사용 가능 여부 확인 (필수!)
        if not check_image_license(p.item_no):
            print(f"  -> 이미지 사용 불가 - 제외")
            continue
        print(f"  -> 이미지 사용 가능 [OK]")

        # 상세 정보 조회
        detail = get_domeggook_product(p.item_no)
        if not detail:
            continue

        # 대표 이미지 필수
        if not detail.image_url:
            continue

        # 상세 이미지 있으면 가점
        detail_img_score = min(len(detail.detail_images), 5)  # 최대 5점

        # 옵션 있으면 가점
        option_score = min(len(detail.options), 3)  # 최대 3점

        # 품절 옵션이 너무 많으면 감점
        soldout_count = sum(1 for opt in detail.options if opt.is_soldout)
        if len(detail.options) > 0:
            soldout_ratio = soldout_count / len(detail.options)
            if soldout_ratio > 0.5:  # 50% 이상 품절이면 제외
                continue

        # 판매가격 계산 (1.5배)
        sale_price = int(detail.price * 1.5)
        margin = sale_price - detail.price
        margin_rate = (margin / sale_price) * 100

        # 종합 점수
        score = detail_img_score + option_score + (margin_rate / 10)

        candidates.append({
            'product': p,
            'detail': detail,
            'sale_price': sale_price,
            'margin': margin,
            'margin_rate': margin_rate,
            'score': score,
            'option_count': len(detail.options),
            'soldout_count': soldout_count
        })

        print(f"\n후보: {detail.name[:30]}...")
        print(f"  도매가: {detail.price:,}원 → 판매가: {sale_price:,}원")
        print(f"  마진: {margin:,}원 ({margin_rate:.1f}%)")
        print(f"  옵션: {len(detail.options)}개 (품절 {soldout_count}개)")
        print(f"  상세이미지: {len(detail.detail_images)}개")
        print(f"  점수: {score:.1f}")

        # 후보가 5개면 충분
        if len(candidates) >= 5:
            break

    if not candidates:
        print("  조건에 맞는 상품이 없습니다.")
        return None

    # 점수순 정렬
    candidates.sort(key=lambda x: x['score'], reverse=True)

    best = candidates[0]
    print(f"\n" + "=" * 60)
    print(f"선정된 상품: {best['detail'].name}")
    print(f"=" * 60)

    return best


def register_product(product_info: dict, category_id: str = None) -> dict:
    """
    네이버에 상품 등록

    Args:
        product_info: 선정된 상품 정보
        category_id: 네이버 카테고리 ID (없으면 기본값)

    Returns:
        등록 결과
    """
    detail = product_info['detail']

    # 카테고리 매핑 (간단한 키워드 기반)
    if category_id is None:
        name_lower = detail.name.lower()
        if any(kw in name_lower for kw in ['헤어', '머리', '핀', '집게']):
            category_id = "50000803"  # 헤어악세서리
        elif any(kw in name_lower for kw in ['귀걸이', '이어링']):
            category_id = "50000804"  # 귀걸이
        elif any(kw in name_lower for kw in ['목걸이', '펜던트']):
            category_id = "50000805"  # 목걸이
        elif any(kw in name_lower for kw in ['팔찌', '뱅글']):
            category_id = "50000806"  # 팔찌
        elif any(kw in name_lower for kw in ['반지', '링']):
            category_id = "50000807"  # 반지
        elif any(kw in name_lower for kw in ['양말', '삭스']):
            category_id = "50000436"  # 양말
        elif any(kw in name_lower for kw in ['케이스', '폰케이스']):
            category_id = "50002325"  # 휴대폰케이스
        else:
            category_id = "50000561"  # 기타 패션잡화

    print(f"\n[등록 시작]")
    print(f"  카테고리 ID: {category_id}")

    # 등록
    channel_no, origin_no, sale_price = register_to_naver(
        detail,
        category_id=category_id,
        price_multiplier=1.5,
        display=False  # 비전시 상태로 등록
    )

    if channel_no:
        result = {
            'success': True,
            'channel_product_no': channel_no,
            'origin_product_no': origin_no,
            'domeggook_item_no': detail.item_no,
            'name': detail.name,
            'domeggook_price': detail.price,
            'sale_price': sale_price,
            'margin': sale_price - detail.price,
            'option_count': len(detail.options)
        }

        # 구글 시트에 저장
        try:
            sheets = GoogleSheetsManager()
            sheets.save_registered_product(
                domeggook_no=detail.item_no,
                naver_channel_no=channel_no,
                naver_origin_no=origin_no,
                name=detail.name,
                domeggook_price=detail.price,
                naver_price=sale_price,
                options=f"{len(detail.options)}개 옵션" if detail.options else "옵션없음",
                min_quantity=detail.min_quantity,
                status="비전시"
            )
        except Exception as e:
            print(f"  [WARN] 구글 시트 저장 실패: {e}")

        return result
    else:
        return {'success': False, 'error': '등록 실패'}


async def main():
    """메인 실행"""
    print("=" * 60)
    print("도매꾹 저가 상품 → 네이버 등록")
    print("=" * 60)

    # 1. 저가 상품 검색 (헤어악세사리 제외 - 이미 등록함)
    products = search_low_price_products(
        max_price=10000,
        keywords=["양말", "키링", "반지", "파우치", "손거울"]
    )

    if not products:
        print("상품을 찾지 못했습니다.")
        return

    # 2. 최적 상품 선정
    best = select_best_product(products)

    if not best:
        print("등록할 상품을 선정하지 못했습니다.")
        return

    # 3. 사용자 확인
    print(f"\n" + "=" * 60)
    print("선정된 상품 정보:")
    print("=" * 60)
    print(f"  상품명: {best['detail'].name}")
    print(f"  도매꾹 번호: {best['detail'].item_no}")
    print(f"  도매가: {best['detail'].price:,}원")
    print(f"  판매가: {best['sale_price']:,}원")
    print(f"  마진: {best['margin']:,}원 ({best['margin_rate']:.1f}%)")
    print(f"  옵션: {best['option_count']}개")
    print(f"  도매꾹 링크: https://domeggook.com/{best['detail'].item_no}")
    print()

    # 자동 등록 (사용자 확인 없이 진행)
    print("\n자동 등록을 진행합니다...")

    # 4. 등록
    result = register_product(best)

    if result['success']:
        print(f"\n" + "=" * 60)
        print("등록 완료!")
        print("=" * 60)
        print(f"  채널상품번호: {result['channel_product_no']}")
        print(f"  원상품번호: {result['origin_product_no']}")
        print(f"  도매꾹번호: {result['domeggook_item_no']}")
        print(f"  상품명: {result['name']}")
        print(f"  도매가: {result['domeggook_price']:,}원")
        print(f"  판매가: {result['sale_price']:,}원")
        print(f"  마진: {result['margin']:,}원")
        print(f"\n  네이버 상품 링크:")
        print(f"  https://smartstore.naver.com/dohsohmall/products/{result['channel_product_no']}")
    else:
        print(f"\n등록 실패: {result.get('error', 'Unknown error')}")


if __name__ == "__main__":
    asyncio.run(main())
