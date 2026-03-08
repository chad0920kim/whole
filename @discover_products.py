# -*- coding: utf-8 -*-
"""
네이버 쇼핑 인기 키워드 기반 도매꾹 상품 발굴 및 등록
=====================================================
- 네이버 쇼핑 인기 키워드 조회
- 도매꾹에서 판매량 높은 상품 10개 추천
- 최소구매수량 1개 필터링
- 기등록 상품 제외
- 사용자 선택 후 등록

사용법: python run_discover_products.py
"""

import sys
import io
import time
from typing import List, Dict

# Windows 콘솔 인코딩 설정
if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, 'buffer') and not isinstance(sys.stdout, io.TextIOWrapper):
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    except:
        pass

try:
    from naver_shopping import NaverShoppingAPI
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


class ProductDiscovery:
    """상품 발굴 클래스"""

    def __init__(self):
        self.naver_shopping = NaverShoppingAPI()
        self.domeggook = DomeggookImageAPI()
        self.naver_commerce = None  # 필요시 초기화
        self.sheets = None  # 필요시 초기화
        self.registered_items = set()  # 기등록 상품번호

    def _load_registered_items(self):
        """구글시트에서 기등록 상품번호 로드"""
        if self.registered_items:
            return

        try:
            self.sheets = GoogleSheetsManager()
            # registered_products 시트에서 도매꾹번호 컬럼 조회
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

    def get_trending_keywords(self) -> List[str]:
        """인기 키워드 목록 반환"""
        print("\n[1단계] 네이버 쇼핑 인기 키워드 조회 중...")

        # 시즌 키워드
        seasonal = self.naver_shopping.get_seasonal_keywords()

        # 카테고리별 인기 키워드
        category_keywords = []
        for cat_code, keywords in self.naver_shopping.CATEGORY_KEYWORDS.items():
            category_keywords.extend(keywords[:2])

        # 합치기 (중복 제거)
        all_keywords = list(dict.fromkeys(seasonal + category_keywords))

        return all_keywords

    def search_domeggook_products(
        self,
        keyword: str,
        max_count: int = 10
    ) -> List[Dict]:
        """
        도매꾹에서 키워드로 상품 검색 (판매량순, MOQ 1개)

        Args:
            keyword: 검색 키워드
            max_count: 최대 추천 개수

        Returns:
            추천 상품 리스트
        """
        print(f"\n[검색] '{keyword}' 도매꾹 상품 검색 중...")

        # 기등록 상품 로드
        self._load_registered_items()

        try:
            # 도매꾹 API 호출 (판매량순 = 'ha')
            params = {
                'ver': '4.1',
                'mode': 'getItemList',
                'aid': self.domeggook.api_key,
                'om': 'json',
                'market': 'dome',
                'sz': 50,  # 넉넉하게 조회
                'so': 'ha',  # 판매량순
                'kw': keyword
            }

            import requests
            response = requests.get(self.domeggook.API_URL, params=params, timeout=30)
            response.encoding = 'utf-8'
            data = response.json()

            domeggook = data.get('domeggook', {})
            items = domeggook.get('list', {}).get('item', [])

            if not items:
                print(f"  검색 결과 없음")
                return []

            if isinstance(items, dict):
                items = [items]

            # 필터링 및 상세 조회
            recommended = []
            checked = 0

            for item in items:
                if len(recommended) >= max_count:
                    break

                item_no = str(item.get('no', ''))
                if not item_no:
                    continue

                # 기등록 상품 제외
                if item_no in self.registered_items:
                    print(f"  [SKIP] {item_no} - 기등록 상품")
                    continue

                # 상세 조회로 MOQ 확인
                checked += 1
                detail = self.domeggook.get_product_detail(item_no)

                if not detail:
                    continue

                # 최소구매수량 확인
                qty_info = detail.get('qty', {})
                min_qty = 1
                if isinstance(qty_info, dict):
                    try:
                        min_qty = int(qty_info.get('domeMoq', 1) or 1)
                    except:
                        min_qty = 1

                if min_qty > 1:
                    print(f"  [SKIP] {item_no} - MOQ {min_qty}개")
                    continue

                # 이미지 사용 허용 확인
                license_info = detail.get('desc', {}).get('license', {})
                usable = license_info.get('usable', False)
                if usable != True and usable != 'true':
                    print(f"  [SKIP] {item_no} - 이미지 사용 불가")
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

                margin_price = int(price * 1.3)
                margin = margin_price - price

                # 추천 상품에 추가
                recommended.append({
                    'item_no': item_no,
                    'name': basis.get('title', item.get('title', '')),
                    'price': price,
                    'margin_price': margin_price,
                    'margin': margin,
                    'min_qty': min_qty,
                    'image_url': detail.get('thumb', {}).get('large', '') or item.get('thumb', ''),
                    'category': detail.get('category', {}).get('name', ''),
                    'license_msg': license_info.get('msg', '')
                })

                print(f"  [{len(recommended)}] {item_no}: {basis.get('title', '')[:35]}... "
                      f"({price:,}원 → {margin_price:,}원, 마진 {margin:,}원)")

                # API 호출 제한 대응
                time.sleep(0.35)

            print(f"\n  총 {checked}개 확인 → {len(recommended)}개 추천")
            return recommended

        except Exception as e:
            print(f"  [ERROR] 검색 실패: {e}")
            import traceback
            traceback.print_exc()
            return []

    def display_recommendations(self, products: List[Dict], keyword: str):
        """추천 상품 목록 출력"""
        if not products:
            print("\n추천 상품이 없습니다.")
            return

        print("\n" + "=" * 70)
        print(f"[추천 상품] '{keyword}' - {len(products)}개")
        print("=" * 70)
        print(f"{'번호':<4} {'상품명':<40} {'도매가':>10} {'판매가':>10} {'마진':>8}")
        print("-" * 70)

        for i, p in enumerate(products, 1):
            name = p['name'][:38] + '..' if len(p['name']) > 38 else p['name']
            print(f"{i:<4} {name:<40} {p['price']:>10,} {p['margin_price']:>10,} {p['margin']:>8,}")

        print("-" * 70)
        print("  * 모든 상품: MOQ 1개, 이미지 사용 허용, 기등록 제외")
        print()

    def register_selected_product(self, product: Dict) -> bool:
        """선택된 상품 등록"""
        item_no = product['item_no']

        print(f"\n[등록 시작] {item_no}: {product['name'][:40]}...")

        # 상품 정보 조회
        domeggook_product = get_domeggook_product(item_no, margin_rate=1.3)

        if not domeggook_product:
            print("  [ERROR] 상품 정보를 가져올 수 없습니다.")
            return False

        # 네이버 API 초기화
        if not self.naver_commerce:
            self.naver_commerce = NaverCommerceAPI()

        # 카테고리 자동 매칭
        category_id = find_category(self.naver_commerce, domeggook_product.name, domeggook_product.category_name)

        if not category_id:
            # 기본 카테고리 사용 (생활/건강 > 생활잡화 > 기타생활잡화)
            DEFAULT_CATEGORY_ID = "50000803"
            print(f"  [WARN] 카테고리 매칭 실패 - 기본 카테고리 사용 ({DEFAULT_CATEGORY_ID})")
            category_id = DEFAULT_CATEGORY_ID

        # 등록
        channel_no, origin_no, final_price = register_to_naver(
            product=domeggook_product,
            naver_api=self.naver_commerce,
            category_id=category_id,
            display=False,  # 비전시
            check_min_quantity=False
        )

        if channel_no:
            print("\n" + "=" * 60)
            print("등록 성공!")
            print("=" * 60)
            print(f"  네이버 상품번호: {channel_no}")
            print(f"  도매꾹 상품번호: {item_no}")
            print(f"  상품명: {domeggook_product.name[:50]}")
            print(f"  도매가: {domeggook_product.price:,}원")
            print(f"  판매가: {final_price:,}원")
            print(f"  마진: {final_price - domeggook_product.price:,}원")
            print(f"\n  상품 링크: https://smartstore.naver.com/dohsohmall/products/{channel_no}")

            # 구글시트 저장
            try:
                if not self.sheets:
                    self.sheets = GoogleSheetsManager()

                option_summary = f"{len(domeggook_product.options)}개 옵션" if domeggook_product.options else "옵션없음"

                self.sheets.save_registered_product(
                    domeggook_no=item_no,
                    naver_channel_no=channel_no,
                    naver_origin_no=origin_no,
                    name=domeggook_product.name,
                    domeggook_price=domeggook_product.price,
                    naver_price=final_price,
                    options=option_summary,
                    min_quantity=domeggook_product.min_quantity,
                    status="비전시"
                )
                print("  구글시트 저장 완료")

                # 기등록 목록에 추가
                self.registered_items.add(item_no)

            except Exception as e:
                print(f"  [WARN] 구글시트 저장 실패: {e}")

            return True
        else:
            print("  [ERROR] 등록 실패")
            return False


def main():
    print("=" * 70)
    print("네이버 쇼핑 인기 키워드 기반 상품 발굴")
    print("=" * 70)
    print("  - MOQ 1개 상품만 추천")
    print("  - 이미지 사용 허용 상품만 추천")
    print("  - 기등록 상품 제외")
    print("  - 30% 마진 적용")
    print()

    discovery = ProductDiscovery()

    # 키워드 선택
    print("[키워드 입력]")
    print("  직접 입력하거나, Enter를 누르면 인기 키워드 목록을 보여줍니다.")
    keyword_input = input("\n검색 키워드: ").strip()

    if not keyword_input:
        # 인기 키워드 목록 표시
        keywords = discovery.get_trending_keywords()
        print("\n[인기 키워드 목록]")
        for i, kw in enumerate(keywords[:15], 1):
            print(f"  {i:2}. {kw}")

        print()
        kw_choice = input("키워드 번호 또는 직접 입력: ").strip()

        if kw_choice.isdigit():
            idx = int(kw_choice) - 1
            if 0 <= idx < len(keywords):
                keyword_input = keywords[idx]
            else:
                print("잘못된 번호입니다.")
                return
        elif kw_choice:
            keyword_input = kw_choice
        else:
            print("키워드를 입력해주세요.")
            return

    print(f"\n선택된 키워드: {keyword_input}")

    # 도매꾹 상품 검색
    products = discovery.search_domeggook_products(keyword_input, max_count=10)

    if not products:
        print("\n추천할 상품이 없습니다.")
        print("  - 다른 키워드로 시도해보세요.")
        return

    # 추천 상품 표시
    discovery.display_recommendations(products, keyword_input)

    # 상품 선택
    while True:
        print("\n[상품 선택]")
        print("  - 번호 입력: 단일 선택 (예: 3)")
        print("  - 복수 선택: 쉼표로 구분 (예: 1,3,5)")
        print("  - 범위 선택: 하이픈 사용 (예: 1-5)")
        print("  - 전체 선택: all 또는 a")
        print("  - q=종료, r=재검색")

        choice = input("\n등록할 상품: ").strip().lower()

        if choice == 'q':
            print("종료합니다.")
            break
        elif choice == 'r':
            new_keyword = input("새 키워드: ").strip()
            if new_keyword:
                products = discovery.search_domeggook_products(new_keyword, max_count=10)
                if products:
                    discovery.display_recommendations(products, new_keyword)
                    keyword_input = new_keyword
                else:
                    print("추천 상품이 없습니다.")
            continue

        # 선택된 인덱스 파싱
        selected_indices = []

        if choice in ['all', 'a']:
            # 전체 선택
            selected_indices = list(range(len(products)))
        elif '-' in choice and choice.replace('-', '').replace(' ', '').isdigit():
            # 범위 선택 (예: 1-5)
            try:
                parts = choice.split('-')
                start = int(parts[0].strip()) - 1
                end = int(parts[1].strip())
                selected_indices = [i for i in range(start, end) if 0 <= i < len(products)]
            except:
                print("잘못된 형식입니다.")
                continue
        elif ',' in choice:
            # 복수 선택 (예: 1,3,5)
            try:
                nums = [int(n.strip()) - 1 for n in choice.split(',')]
                selected_indices = [i for i in nums if 0 <= i < len(products)]
            except:
                print("잘못된 형식입니다.")
                continue
        elif choice.isdigit():
            # 단일 선택
            idx = int(choice) - 1
            if 0 <= idx < len(products):
                selected_indices = [idx]
            else:
                print("잘못된 번호입니다.")
                continue
        else:
            print("잘못된 입력입니다.")
            continue

        if not selected_indices:
            print("선택된 상품이 없습니다.")
            continue

        # 선택된 상품 목록 표시
        selected_products = [products[i] for i in selected_indices]
        print(f"\n[선택된 상품: {len(selected_products)}개]")
        for i, p in enumerate(selected_products, 1):
            print(f"  {i}. [{p['item_no']}] {p['name'][:40]}... ({p['price']:,}원 → {p['margin_price']:,}원)")

        # 확인
        confirm = input(f"\n{len(selected_products)}개 상품을 등록하시겠습니까? (y/Enter=등록, n=취소): ").strip().lower()

        if confirm not in ['', 'y', 'yes']:
            print("취소되었습니다.")
            continue

        # 등록 진행
        success_count = 0
        fail_count = 0
        registered_indices = []

        for i, idx in enumerate(selected_indices):
            selected = products[idx]
            print(f"\n{'='*60}")
            print(f"[{i+1}/{len(selected_indices)}] 등록 중: {selected['name'][:40]}...")
            print('='*60)

            success = discovery.register_selected_product(selected)
            if success:
                success_count += 1
                registered_indices.append(idx)
            else:
                fail_count += 1

            # API 호출 간격
            if i < len(selected_indices) - 1:
                time.sleep(1)

        # 결과 출력
        print("\n" + "=" * 60)
        print(f"[등록 완료] 성공: {success_count}개, 실패: {fail_count}개")
        print("=" * 60)

        # 등록된 상품 제거 (역순으로)
        for idx in sorted(registered_indices, reverse=True):
            products.pop(idx)

        if products:
            print(f"\n남은 추천 상품: {len(products)}개")
            discovery.display_recommendations(products, keyword_input)
        else:
            print("\n모든 추천 상품을 등록했습니다.")
            break


if __name__ == "__main__":
    main()
