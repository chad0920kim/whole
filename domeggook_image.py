# -*- coding: utf-8 -*-
"""
도매꾹 이미지허용상품 조회 모듈
================================
도매꾹 OpenAPI를 사용하여 이미지 사용이 허용된 상품을 조회합니다.
getItemList로 상품 목록 조회 후 getItemView로 desc.license.usable 확인
"""

import os
import time
import requests
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from dotenv import load_dotenv

load_dotenv(override=True)


@dataclass
class ProductOption:
    """상품 옵션 데이터 클래스"""
    name: str = ""                  # 옵션명 (예: 색상, 사이즈)
    value: str = ""                 # 옵션값 (예: 블랙, L)
    price_diff: int = 0             # 추가금액
    stock: int = 0                  # 재고


@dataclass
class ImageAllowedProduct:
    """이미지허용상품 데이터 클래스"""
    item_no: str                    # 상품번호
    name: str                       # 상품명
    price: int                      # 판매가 (도매가)
    original_price: int = 0         # 정가
    min_quantity: int = 1           # 최소주문수량
    image_url: str = ""             # 대표 이미지 URL
    detail_images: List[str] = field(default_factory=list)  # 상세 이미지
    detail_html: str = ""           # 상세설명 HTML
    category: str = ""              # 카테고리
    category_name: str = ""         # 카테고리명
    brand: str = ""                 # 브랜드
    seller_id: str = ""             # 판매자 ID
    option_info: str = ""           # 옵션 정보 (원본 문자열)
    options: List[ProductOption] = field(default_factory=list)  # 파싱된 옵션 리스트
    delivery_fee: int = 0           # 배송비
    license_msg: str = ""           # 이미지 사용 라이선스 메시지
    kc_cert: List[Dict] = field(default_factory=list)  # KC 인증 정보

    def get_option_list(self) -> List[str]:
        """옵션값 리스트 반환 (예: ['블랙', '화이트', 'L', 'XL'])"""
        return [opt.value for opt in self.options if opt.value]

    def get_option_string(self) -> str:
        """옵션을 구분자로 연결한 문자열 반환"""
        return " | ".join(self.get_option_list())

    @property
    def link(self) -> str:
        """상품 링크"""
        return f"https://domeggook.com/{self.item_no}" if self.item_no else ""

    @property
    def margin_price(self) -> int:
        """30% 마진 적용 판매가"""
        return int(self.price * 1.3)


class DomeggookImageAPI:
    """도매꾹 이미지허용상품 API 클래스"""

    API_URL = "https://domeggook.com/ssl/api/"

    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("DOMEGGOOK_API_KEY")
        if not self.api_key:
            raise ValueError("DOMEGGOOK_API_KEY 환경변수가 필요합니다.")

    def get_image_allowed_products(
        self,
        keyword: str = "",
        category: str = "",
        max_products: int = 20,
        check_each: bool = True
    ) -> List[ImageAllowedProduct]:
        """
        이미지허용상품 목록 조회

        Args:
            keyword: 검색 키워드
            category: 카테고리 코드
            max_products: 최대 조회 상품 수
            check_each: True면 각 상품별로 license.usable 확인

        Returns:
            ImageAllowedProduct 리스트 (이미지 사용 허용된 상품만)
        """
        # 1단계: 상품 목록 조회
        print(f"[도매꾹] 상품 목록 조회 중... (키워드: {keyword or '전체'})")
        items = self._get_item_list(keyword, category, max_products)
        print(f"  → {len(items)}개 상품 발견")

        if not check_each:
            return items

        # 2단계: 각 상품의 이미지 사용 허용 여부 확인
        print(f"[도매꾹] 이미지 사용 허용 여부 확인 중...")
        allowed_products = []

        for i, item in enumerate(items):
            detail = self.get_product_detail(item.item_no)
            if detail:
                license_info = detail.get('desc', {}).get('license', {})
                usable = license_info.get('usable', False)

                if usable == True or usable == 'true':
                    item.license_msg = license_info.get('msg', '')

                    # 상세설명 HTML 추가 (notice 또는 content)
                    desc_info = detail.get('desc', {})
                    item.detail_html = desc_info.get('notice', '') or desc_info.get('content', '')

                    # 카테고리 정보 추가
                    cat_info = detail.get('category', {})
                    item.category = cat_info.get('code', '')
                    item.category_name = cat_info.get('name', '')

                    # 대표 이미지 업데이트 (thumb에서 가장 큰 이미지 사용)
                    thumb_info = detail.get('thumb', {})
                    if isinstance(thumb_info, dict):
                        # original > large > largePng 순으로 시도
                        item.image_url = (
                            thumb_info.get('original') or
                            thumb_info.get('large') or
                            thumb_info.get('largePng') or
                            item.image_url
                        )

                    # 추가 이미지 (addImage 필드에서)
                    add_images = detail.get('addImage', [])
                    if isinstance(add_images, list):
                        item.detail_images = [img.get('url', img) if isinstance(img, dict) else img for img in add_images[:5]]
                    elif isinstance(add_images, dict):
                        item.detail_images = [add_images.get('url', '')]

                    # 브랜드 정보 추가
                    brand_info = detail.get('brand', {})
                    if isinstance(brand_info, dict):
                        item.brand = brand_info.get('name', '')

                    # 옵션 정보 추가 (구조화)
                    options = detail.get('option', {})
                    if isinstance(options, dict):
                        option_list = options.get('list', [])
                        item.option_info = str(option_list)
                        item.options = self._parse_options(option_list)

                    # KC 인증 정보 추출
                    detail_section = detail.get('detail', {})
                    safety_cert = detail_section.get('safetyCert', []) if isinstance(detail_section, dict) else []
                    kc_cert_list = []
                    if isinstance(safety_cert, list):
                        for cert in safety_cert:
                            if isinstance(cert, dict) and cert.get('cert') == 'Y':
                                cert_type = cert.get('certType', cert.get('type', ''))
                                cert_name = cert.get('certName', cert.get('name', ''))
                                cert_no = cert.get('no', '')
                                if cert_no:
                                    kc_cert_list.append({
                                        'type': cert_type,
                                        'name': cert_name,
                                        'no': cert_no
                                    })
                    item.kc_cert = kc_cert_list

                    allowed_products.append(item)
                    print(f"  ✓ {i+1}/{len(items)} [{item.item_no}] 이미지 허용: {item.name[:30]}...")
                else:
                    print(f"  ✗ {i+1}/{len(items)} [{item.item_no}] 이미지 불허")

            # API 호출 제한 (분당 180회) 대응
            time.sleep(0.4)

        print(f"[도매꾹] 이미지허용상품 {len(allowed_products)}개 확인 완료")
        return allowed_products

    def _get_item_list(self, keyword: str, category: str, max_products: int) -> List[ImageAllowedProduct]:
        """상품 목록 조회"""
        try:
            params = {
                'ver': '4.1',
                'mode': 'getItemList',
                'aid': self.api_key,
                'om': 'json',
                'market': 'dome',
                'sz': min(max_products, 20),
                'so': 'ha'  # 인기순
            }

            if keyword:
                params['kw'] = keyword
            if category:
                params['cat'] = category

            response = requests.get(self.API_URL, params=params, timeout=30)
            response.encoding = 'utf-8'
            data = response.json()

            domeggook = data.get('domeggook', {})
            items = domeggook.get('list', {}).get('item', [])

            if not items:
                return []
            if isinstance(items, dict):
                items = [items]

            products = []
            for item in items[:max_products]:
                product = self._parse_list_item(item)
                if product:
                    products.append(product)

            return products

        except Exception as e:
            print(f"  [ERROR] 상품 목록 조회 실패: {e}")
            return []

    def _parse_list_item(self, item: dict) -> Optional[ImageAllowedProduct]:
        """상품 목록 아이템 파싱"""
        try:
            item_no = str(item.get('no', ''))
            name = item.get('title', '')

            if not item_no or not name:
                return None

            price = self._parse_int(item.get('price', 0))
            min_qty = self._parse_int(item.get('unitQty', 1)) or 1
            image_url = item.get('thumb', '')

            # 배송비
            deli = item.get('deli', {})
            delivery_fee = self._parse_int(deli.get('fee', 0)) if isinstance(deli, dict) else 0

            return ImageAllowedProduct(
                item_no=item_no,
                name=name,
                price=price,
                min_quantity=min_qty,
                image_url=image_url,
                seller_id=item.get('id', ''),
                delivery_fee=delivery_fee
            )

        except Exception as e:
            print(f"    [WARN] 아이템 파싱 실패: {e}")
            return None

    def _parse_int(self, value) -> int:
        """정수 파싱"""
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            value = value.replace(',', '').strip()
            if value.isdigit():
                return int(value)
        return 0

    def _parse_options(self, option_list) -> List[ProductOption]:
        """
        도매꾹 옵션 리스트 파싱

        Args:
            option_list: 도매꾹 API 응답의 option.list

        Returns:
            ProductOption 리스트
        """
        parsed_options = []

        if not option_list:
            return parsed_options

        # 단일 옵션인 경우 리스트로 변환
        if isinstance(option_list, dict):
            option_list = [option_list]

        if not isinstance(option_list, list):
            return parsed_options

        for opt in option_list:
            if not isinstance(opt, dict):
                continue

            # 옵션 구조: {'name': '색상', 'value': '블랙', 'price': 0, 'stock': 100}
            # 또는: {'optName': '색상', 'optValue': '블랙', 'addPrice': 0}
            option = ProductOption(
                name=opt.get('name', '') or opt.get('optName', ''),
                value=opt.get('value', '') or opt.get('optValue', ''),
                price_diff=self._parse_int(opt.get('price', 0) or opt.get('addPrice', 0)),
                stock=self._parse_int(opt.get('stock', 0) or opt.get('qty', 0))
            )

            if option.value:  # 값이 있는 옵션만 추가
                parsed_options.append(option)

        return parsed_options

    def get_product_detail(self, item_no: str) -> Optional[Dict[str, Any]]:
        """
        상품 상세 정보 조회 (getItemView API)

        Args:
            item_no: 상품번호

        Returns:
            상품 상세 정보 딕셔너리 (desc.license.usable 포함)
        """
        try:
            params = {
                'ver': '4.5',
                'mode': 'getItemView',
                'aid': self.api_key,
                'om': 'json',
                'no': item_no  # 상품번호는 'no' 파라미터로 전달
            }

            response = requests.get(self.API_URL, params=params, timeout=30)
            response.encoding = 'utf-8'
            data = response.json()

            domeggook = data.get('domeggook', {})

            # errors 체크
            if data.get('errors'):
                return None

            # domeggook 자체가 응답 데이터 (res 필드 없음)
            return domeggook

        except Exception as e:
            print(f"  [ERROR] 상품 상세 조회 실패: {e}")
            return None


# 테스트
if __name__ == "__main__":
    import sys
    import io
    if sys.platform == "win32":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

    print("=" * 60)
    print("도매꾹 이미지허용상품 조회 테스트")
    print("=" * 60)

    api = DomeggookImageAPI()

    # 무선이어폰 키워드로 테스트
    products = api.get_image_allowed_products(
        keyword="무선이어폰",
        max_products=10,
        check_each=True
    )

    print(f"\n{'=' * 60}")
    print(f"이미지허용상품 조회 결과: {len(products)}개")
    print("=" * 60)

    for i, p in enumerate(products[:5], 1):
        print(f"\n{i}. {p.name[:50]}...")
        print(f"   상품번호: {p.item_no}")
        print(f"   도매가: {p.price:,}원 → 판매가(30%마진): {p.margin_price:,}원")
        print(f"   이미지: {'있음' if p.image_url else '없음'}")
        print(f"   라이선스: {p.license_msg[:50]}..." if p.license_msg else "   라이선스: 정보없음")
        print(f"   링크: {p.link}")
