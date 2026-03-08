# -*- coding: utf-8 -*-
"""
도매꾹 상품 복수 링크 일괄 등록
==============================
터미널에서 여러 링크를 입력받아 순차적으로 등록

사용법: python bulk_register_by_links.py
  - 실행 후 링크를 한 줄씩 입력 (빈 줄 입력 시 등록 시작)
  - 또는: python bulk_register_by_links.py < links.txt
"""

import sys
import io
import time
from typing import List, Tuple, Optional
from datetime import datetime

# Windows 콘솔 인코딩 설정
if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, 'buffer') and not isinstance(sys.stdout, io.TextIOWrapper):
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    except:
        pass

try:
    from naver_commerce import NaverCommerceAPI
    from google_sheets import GoogleSheetsManager
    from run_register_by_link import (
        get_domeggook_product,
        register_to_naver,
        find_category,
        extract_item_id,
        DomeggookProduct
    )
except ImportError as e:
    print(f"[ERROR] 필수 모듈을 찾을 수 없습니다: {e}")
    sys.exit(1)


def collect_links() -> List[str]:
    """터미널에서 링크 수집"""
    print("=" * 60)
    print("도매꾹 상품 복수 링크 일괄 등록")
    print("=" * 60)
    print()
    print("상품 링크 또는 번호를 한 줄씩 입력하세요.")
    print("입력 완료 후 빈 줄을 입력하면 등록을 시작합니다.")
    print("-" * 60)

    links = []
    line_num = 1

    while True:
        try:
            line = input(f"[{line_num}] ").strip()

            if not line:
                if links:
                    break
                else:
                    print("  최소 1개 이상의 링크를 입력해주세요.")
                    continue

            # 상품번호 추출
            item_no = extract_item_id(line)
            if item_no:
                if item_no not in [extract_item_id(l) for l in links]:
                    links.append(line)
                    print(f"  → 상품번호 {item_no} 추가됨")
                    line_num += 1
                else:
                    print(f"  → 이미 추가된 상품입니다 (중복)")
            else:
                print(f"  → 유효하지 않은 링크입니다")

        except EOFError:
            # 파일에서 읽을 때 EOF 처리
            break

    return links


def register_products(links: List[str], margin_rate: float = 1.3, display: bool = False) -> dict:
    """
    상품 일괄 등록

    Args:
        links: 상품 링크 리스트
        margin_rate: 마진율 (기본 1.3 = 30%)
        display: True면 전시, False면 비전시

    Returns:
        결과 통계
    """
    results = {
        'total': len(links),
        'success': 0,
        'failed': 0,
        'skipped': 0,
        'registered': [],
        'errors': []
    }

    print()
    print("=" * 60)
    print(f"[등록 시작] 총 {len(links)}개 상품")
    print(f"  마진율: {(margin_rate - 1) * 100:.0f}%")
    print(f"  전시상태: {'전시' if display else '비전시'}")
    print("=" * 60)

    naver_api = NaverCommerceAPI()
    sheets = None

    try:
        sheets = GoogleSheetsManager()
    except Exception as e:
        print(f"[WARN] 구글시트 연결 실패: {e}")

    start_time = datetime.now()

    for i, link in enumerate(links, 1):
        item_no = extract_item_id(link)
        print(f"\n{'='*60}")
        print(f"[{i}/{len(links)}] 상품번호: {item_no}")
        print("=" * 60)

        try:
            # 1. 도매꾹 상품 정보 조회
            print("[1/3] 도매꾹 상품 정보 조회 중...")
            product = get_domeggook_product(item_no, margin_rate=margin_rate)

            if not product:
                print(f"  [ERROR] 상품 정보를 가져올 수 없습니다")
                results['failed'] += 1
                results['errors'].append({
                    'item_no': item_no,
                    'error': '상품 정보 조회 실패'
                })
                continue

            print(f"  상품명: {product.name}")
            print(f"  도매가: {product.price:,}원 → 판매가: {product.margin_price:,}원")
            if product.category_name:
                print(f"  도매꾹 카테고리: {product.category_name}")

            # 2. 카테고리 매칭
            print("\n[2/3] 카테고리 매칭 중...")
            category_id = find_category(naver_api, product.name, product.category_name)

            if not category_id:
                print(f"  [ERROR] 카테고리 매칭 실패")
                results['failed'] += 1
                results['errors'].append({
                    'item_no': item_no,
                    'name': product.name,
                    'error': '카테고리 매칭 실패'
                })
                continue

            # 3. 네이버 등록
            print("\n[3/3] 네이버 스마트스토어 등록 중...")
            channel_no, origin_no, final_price = register_to_naver(
                product=product,
                naver_api=naver_api,
                category_id=category_id,
                display=display,
                check_min_quantity=False
            )

            if channel_no:
                results['success'] += 1
                results['registered'].append({
                    'item_no': item_no,
                    'name': product.name,
                    'channel_no': channel_no,
                    'price': product.price,
                    'sale_price': final_price
                })

                # 구글시트 저장
                if sheets:
                    try:
                        option_summary = f"{len(product.options)}개 옵션" if product.options else "옵션없음"
                        sheets.save_registered_product(
                            domeggook_no=item_no,
                            naver_channel_no=channel_no,
                            naver_origin_no=origin_no,
                            name=product.name,
                            domeggook_price=product.price,
                            naver_price=final_price,
                            options=option_summary,
                            min_quantity=product.min_quantity,
                            status="전시" if display else "비전시",
                            margin_rate=(margin_rate - 1) * 100
                        )
                    except Exception as e:
                        print(f"  [WARN] 구글시트 저장 실패: {e}")

                print(f"\n  [SUCCESS] 등록 완료! (채널상품번호: {channel_no})")
            else:
                results['failed'] += 1
                results['errors'].append({
                    'item_no': item_no,
                    'name': product.name,
                    'error': '네이버 API 등록 실패'
                })

            # API 호출 제한 대응 (1초 대기)
            if i < len(links):
                time.sleep(1)

        except Exception as e:
            results['failed'] += 1
            results['errors'].append({
                'item_no': item_no,
                'error': str(e)
            })
            print(f"  [ERROR] 처리 중 오류: {e}")

    elapsed = (datetime.now() - start_time).total_seconds()
    results['elapsed'] = elapsed

    return results


def print_summary(results: dict):
    """결과 요약 출력"""
    print()
    print("=" * 60)
    print("등록 결과 요약")
    print("=" * 60)
    print(f"  총 시도: {results['total']}개")
    print(f"  성공: {results['success']}개")
    print(f"  실패: {results['failed']}개")
    print(f"  소요시간: {results.get('elapsed', 0):.1f}초")

    if results['registered']:
        print()
        print("-" * 60)
        print("등록 성공 목록:")
        for item in results['registered']:
            print(f"  - [{item['item_no']}] {item['name'][:30]}...")
            print(f"    도매가: {item['price']:,}원 → 판매가: {item['sale_price']:,}원")
            print(f"    채널상품번호: {item['channel_no']}")

    if results['errors']:
        print()
        print("-" * 60)
        print("실패 목록:")
        for item in results['errors']:
            name = item.get('name', '')[:30] if item.get('name') else ''
            print(f"  - [{item['item_no']}] {name}")
            print(f"    사유: {item['error']}")

    print()
    print("=" * 60)


def main():
    # 설정 입력
    print()
    margin_input = input("마진율 입력 (기본 30%, Enter로 스킵): ").strip()
    if margin_input:
        try:
            margin_percent = float(margin_input.replace('%', ''))
            margin_rate = 1 + (margin_percent / 100)
        except:
            margin_rate = 1.3
    else:
        margin_rate = 1.3

    display_input = input("전시 상태 (y=전시, Enter=비전시): ").strip().lower()
    display = display_input in ['y', 'yes', '전시']

    print()

    # 링크 수집
    links = collect_links()

    if not links:
        print("등록할 상품이 없습니다.")
        return

    print()
    print("-" * 60)
    print(f"총 {len(links)}개 상품을 등록합니다.")
    confirm = input("계속하시겠습니까? (y/Enter=예, n=아니오): ").strip().lower()

    if confirm == 'n':
        print("취소되었습니다.")
        return

    # 등록 실행
    results = register_products(links, margin_rate=margin_rate, display=display)

    # 결과 출력
    print_summary(results)


if __name__ == "__main__":
    main()
