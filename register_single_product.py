# -*- coding: utf-8 -*-
"""
단일 상품 네이버 등록
"""
import sys
import io

if sys.platform == "win32" and not isinstance(sys.stdout, io.TextIOWrapper):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from product_register import get_domeggook_product, register_to_naver
from google_sheets import GoogleSheetsManager


def register_single(item_no: str, category_id: str = None):
    """단일 상품 등록"""

    print("=" * 60)
    print(f"도매꾹 상품 등록: {item_no}")
    print("=" * 60)

    # 상세정보 조회
    detail = get_domeggook_product(item_no)
    if not detail:
        print("상품 정보를 가져올 수 없습니다.")
        return None

    # 판매가 계산
    sale_price = int(detail.price * 1.5)
    margin = sale_price - detail.price

    print(f"\n[상품 정보]")
    print(f"  상품명: {detail.name}")
    print(f"  도매가: {detail.price:,}원")
    print(f"  판매가: {sale_price:,}원")
    print(f"  마진: {margin:,}원 (33.3%)")
    print(f"  옵션: {len(detail.options)}개")

    # 카테고리 자동 설정 (핸드폰케이스)
    if category_id is None:
        category_id = "50002325"  # 휴대폰케이스

    print(f"\n[등록 시작]")
    print(f"  카테고리 ID: {category_id}")

    # 등록
    channel_no, origin_no, final_price = register_to_naver(
        detail,
        category_id=category_id,
        price_multiplier=1.5,
        display=False  # 비전시 상태로 등록
    )

    if channel_no:
        print(f"\n" + "=" * 60)
        print("등록 완료!")
        print("=" * 60)
        print(f"  채널상품번호: {channel_no}")
        print(f"  원상품번호: {origin_no}")
        print(f"  도매꾹번호: {item_no}")
        print(f"  상품명: {detail.name}")
        print(f"  도매가: {detail.price:,}원")
        print(f"  판매가: {final_price:,}원")
        print(f"  마진: {final_price - detail.price:,}원")
        print(f"\n  네이버 상품 링크:")
        print(f"  https://smartstore.naver.com/dohsohmall/products/{channel_no}")

        # 구글 시트에 저장
        try:
            sheets = GoogleSheetsManager()
            sheets.save_registered_product(
                domeggook_no=item_no,
                naver_channel_no=channel_no,
                naver_origin_no=origin_no,
                name=detail.name,
                domeggook_price=detail.price,
                naver_price=final_price,
                options=f"{len(detail.options)}개 옵션" if detail.options else "옵션없음",
                min_quantity=detail.min_quantity,
                status="비전시"
            )
        except Exception as e:
            print(f"  [WARN] 구글 시트 저장 실패: {e}")

        return {
            'channel_no': channel_no,
            'origin_no': origin_no,
            'name': detail.name,
            'price': final_price
        }
    else:
        print("등록 실패")
        return None


if __name__ == "__main__":
    # 3번 양말: 남녀 겨울 기모양말 10켤레 (5color 2set)
    # 50000852: 남성양말
    register_single("51350633", "50000852")
