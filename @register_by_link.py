# -*- coding: utf-8 -*-
"""
도매꾹 상품 링크로 네이버 스마트스토어 등록 (통합 버전)
=====================================================
프로젝트 내 모든 기능 통합:
- 다단 옵션 파싱 (1단~3단)
- 품절/판매종료 옵션 처리 (재고 0)
- 상세 이미지 네이버 업로드 후 HTML 재구성
- 30% 마진 고정
- 비전시/전시 상태 선택

사용법: python run_register_by_link.py
  - 실행 후 터미널에서 순차적으로 입력
"""

import sys
import io
import re
import json
import requests
from typing import Optional, List, Tuple
from dataclasses import dataclass, field

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
except ImportError as e:
    print(f"[ERROR] 필수 모듈을 찾을 수 없습니다: {e}")
    sys.exit(1)

# OpenAI (AI 카테고리 분류용)
try:
    from openai import OpenAI
    import os
    from dotenv import load_dotenv
    load_dotenv(override=True)
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

# AI 카테고리 분류 설정
USE_AI_CATEGORY = True


# ============================================================================
# 품절/판매종료 키워드
# ============================================================================
SOLDOUT_KEYWORDS = ['품절', '판매종료', '판매중지', '재고없음', '매진', 'sold out', 'soldout']


# ============================================================================
# 데이터 클래스
# ============================================================================
@dataclass
class ProductOption:
    """상품 옵션 (단일 또는 조합)"""
    name: str           # 옵션명 (색상, 사이즈 등) - 1단 옵션용
    value: str          # 옵션값 (블랙, L 등) - 1단 옵션용
    stock: int = 30     # 재고 (품절이면 0)
    price_diff: int = 0 # 추가금액
    is_soldout: bool = False  # 품절 여부
    # 다단 옵션용 필드
    value2: str = ""    # 2단 옵션값
    value3: str = ""    # 3단 옵션값


@dataclass
class OptionGroup:
    """옵션 그룹 (다단 옵션 지원)"""
    name: str           # 그룹명 (스타일, 색상, 크기)
    values: List[str] = field(default_factory=list)  # 옵션값 목록


@dataclass
class DomeggookProduct:
    """도매꾹 상품 정보 (통합)"""
    item_no: str
    name: str
    price: int
    image_url: str = ""
    detail_images: List[str] = field(default_factory=list)
    detail_html: str = ""
    options: List[ProductOption] = field(default_factory=list)
    option_group_name: str = "옵션"  # 옵션 그룹명 (색상, 사이즈 등) - 1단용
    option_groups: List[OptionGroup] = field(default_factory=list)  # 다단 옵션 그룹들
    delivery_fee: int = 3000
    category_code: str = ""
    category_name: str = ""
    min_quantity: int = 1  # 최소주문수량 (domeMoq)
    brand: str = ""
    seller_id: str = ""
    license_msg: str = ""
    margin_price: int = 0  # 마진 적용 판매가
    option_info: str = ""  # 원본 옵션 정보 문자열
    kc_cert: List[dict] = field(default_factory=list)  # KC 인증 정보


# ============================================================================
# 유틸리티 함수
# ============================================================================
def extract_item_id(link: str) -> Optional[str]:
    """링크에서 도매꾹 상품번호 추출"""
    if not link:
        return None

    # 숫자만 있는 경우 (상품번호 직접 입력)
    if link.isdigit():
        return link

    # URL 패턴 매칭
    patterns = [
        r'domeggook\.com/([0-9]+)',
        r'no=([0-9]+)',
        r'itemNo=([0-9]+)',
    ]

    for pattern in patterns:
        match = re.search(pattern, link)
        if match:
            return match.group(1)

    return None


def parse_price(price_data) -> int:
    """가격 데이터 파싱 (문자열, 구간별 가격 등 처리)"""
    if isinstance(price_data, int):
        return price_data
    if isinstance(price_data, str):
        # 콤마 제거
        price_str = price_data.replace(',', '').strip()
        # 구간별 가격 처리 (예: "1+5000|10+4800") -> 첫 번째 가격 사용
        if '|' in price_str:
            price_str = price_str.split('|')[0]
        if '+' in price_str:
            price_str = price_str.split('+')[1]
        if price_str.isdigit():
            return int(price_str)
    return 0


def is_soldout(text: str) -> bool:
    """품절/판매종료 여부 확인"""
    text_lower = text.lower()
    for keyword in SOLDOUT_KEYWORDS:
        if keyword in text_lower:
            return True
    return False


def extract_detail_images(item_html: str) -> List[str]:
    """상세설명 HTML에서 이미지 URL 추출"""
    if not item_html:
        return []

    # img 태그의 src 속성에서 모든 이미지 URL 추출
    img_pattern = r'<img[^>]+src=["\']([^"\']+)["\']'
    images = re.findall(img_pattern, item_html)

    cleaned_images = []
    for img in images:
        img = img.strip()
        # 유효한 이미지 URL인지 확인
        if not img or not img.startswith('http'):
            continue
        # 이미지 확장자 또는 CDN 도메인 확인
        valid_extensions = ('.jpg', '.jpeg', '.png', '.gif', '.webp')
        valid_domains = ('domeggook.com', 'kakaocdn', 'esmplus.com', 'cdn', 'naver.net')
        is_valid = any(ext in img.lower() for ext in valid_extensions) or \
                   any(domain in img.lower() for domain in valid_domains)
        if is_valid and img not in cleaned_images:
            cleaned_images.append(img)

    return cleaned_images


# ============================================================================
# 옵션 파싱 (1단~3단 옵션 지원)
# ============================================================================
def parse_domeggook_options(select_opt: str) -> Tuple[List[ProductOption], str, List[OptionGroup]]:
    """
    도매꾹 selectOpt 필드 파싱 (1단~3단 옵션 지원)

    도매꾹 옵션 구조:
    1단: {"type": "combination", "set": [{"name": "색상", "opts": [...]}]}
    다단: {"type": "combination", "set": [...], "data": {"00_00_00": {"name": "조합명", "qty": "100"}}}

    Args:
        select_opt: JSON 문자열 형태의 옵션 정보

    Returns:
        (옵션 조합 리스트, 첫번째 옵션 그룹명, 옵션 그룹 리스트)
    """
    options = []
    option_group_name = "옵션"
    option_groups = []

    if not select_opt:
        return options, option_group_name, option_groups

    try:
        # JSON 파싱
        if isinstance(select_opt, str):
            opt_data = json.loads(select_opt)
        else:
            opt_data = select_opt

        # 새 형식: {"type": "combination", "set": [...], "data": {...}}
        if isinstance(opt_data, dict) and 'set' in opt_data:
            opt_sets = opt_data.get('set', [])
            opt_combinations = opt_data.get('data', {})

            # 옵션 그룹 추출
            for opt_set in opt_sets:
                if isinstance(opt_set, dict):
                    group = OptionGroup(
                        name=opt_set.get('name', '옵션'),
                        values=opt_set.get('opts', [])
                    )
                    option_groups.append(group)

            if option_groups:
                option_group_name = option_groups[0].name

            # 다단 옵션 조합이 있는 경우 (data 필드)
            if opt_combinations and len(option_groups) > 1:
                for key, combo in opt_combinations.items():
                    if not isinstance(combo, dict):
                        continue

                    combo_name = combo.get('name', '')
                    combo_qty = combo.get('qty', '30')
                    combo_price = combo.get('domPrice', '0')

                    # 품절 여부
                    soldout = is_soldout(combo_name)
                    try:
                        stock = int(combo_qty) if combo_qty else 30
                    except:
                        stock = 30

                    if stock <= 0 or soldout:
                        soldout = True
                        stock = 0

                    try:
                        price_diff = int(combo_price) if combo_price else 0
                    except:
                        price_diff = 0

                    # 조합명에서 각 옵션값 분리 (예: "일자형/블랙/2XL")
                    values = combo_name.split('/')
                    value1 = values[0] if len(values) > 0 else ""
                    value2 = values[1] if len(values) > 1 else ""
                    value3 = values[2] if len(values) > 2 else ""

                    options.append(ProductOption(
                        name=option_groups[0].name if option_groups else "옵션",
                        value=value1,
                        value2=value2,
                        value3=value3,
                        stock=stock,
                        price_diff=price_diff,
                        is_soldout=soldout
                    ))

            # 1단 옵션만 있는 경우
            elif len(option_groups) == 1:
                opt_set = opt_sets[0]
                opt_values = opt_set.get('opts', [])
                opt_prices = opt_set.get('domPrice', [])
                change_keys = opt_set.get('changeKey', [])

                for i, opt_value in enumerate(opt_values):
                    if not opt_value:
                        continue

                    try:
                        opt_price = int(opt_prices[i]) if i < len(opt_prices) else 0
                    except:
                        opt_price = 0

                    # data 필드에서 실제 재고/품절 정보 확인
                    opt_stock = 30
                    soldout = is_soldout(str(opt_value))

                    # changeKey로 data 조회
                    if opt_combinations and i < len(change_keys):
                        key = str(change_keys[i]).zfill(2)
                        combo_data = opt_combinations.get(key, {})
                        if combo_data:
                            # qty: 재고 수량
                            try:
                                opt_stock = int(combo_data.get('qty', '30') or '30')
                            except:
                                opt_stock = 30

                            # hid=1: 숨김(품절) 처리된 옵션
                            if combo_data.get('hid') == '1' or combo_data.get('hid') == 1:
                                soldout = True
                                opt_stock = 0

                            # qty가 0이면 품절
                            if opt_stock <= 0:
                                soldout = True
                                opt_stock = 0

                    # 옵션명에 품절 키워드가 있으면 품절 처리
                    if soldout:
                        opt_stock = 0

                    options.append(ProductOption(
                        name=option_group_name,
                        value=str(opt_value),
                        stock=opt_stock,
                        price_diff=opt_price,
                        is_soldout=soldout
                    ))

        # 구 형식: [{"name": "옵션", "value": [...]}]
        else:
            if not isinstance(opt_data, list):
                opt_data = [opt_data]

            for item in opt_data:
                if not isinstance(item, dict):
                    continue

                if 'name' in item:
                    option_group_name = item.get('name', '옵션')

                values = item.get('value', [])
                if isinstance(values, str):
                    values = [values]

                for val in values:
                    if isinstance(val, dict):
                        opt_value = val.get('name', '') or val.get('value', '')
                        opt_stock = val.get('stock', 30) or val.get('qty', 30)
                        opt_price = val.get('price', 0) or val.get('addPrice', 0)
                    else:
                        opt_value = str(val)
                        opt_stock = 30
                        opt_price = 0

                    if not opt_value:
                        continue

                    soldout = is_soldout(opt_value)
                    if soldout:
                        opt_stock = 0

                    try:
                        opt_stock = int(opt_stock)
                    except:
                        opt_stock = 30

                    if opt_stock <= 0:
                        soldout = True
                        opt_stock = 0

                    options.append(ProductOption(
                        name=option_group_name,
                        value=opt_value,
                        stock=opt_stock,
                        price_diff=int(opt_price) if opt_price else 0,
                        is_soldout=soldout
                    ))

    except json.JSONDecodeError:
        pass
    except Exception as e:
        print(f"  [WARN] 옵션 파싱 오류: {e}")

    return options, option_group_name, option_groups


# ============================================================================
# 도매꾹 상품 정보 조회
# ============================================================================
def get_domeggook_product(item_no: str, margin_rate: float = 1.3) -> Optional[DomeggookProduct]:
    """
    도매꾹 상품 정보 조회 (상세 이미지, 옵션 포함)

    Args:
        item_no: 도매꾹 상품번호
        margin_rate: 마진율 (기본 1.3 = 30%)

    Returns:
        DomeggookProduct 또는 None
    """
    api = DomeggookImageAPI()
    detail = api.get_product_detail(item_no)

    if not detail:
        return None

    # 기본 정보
    basis = detail.get('basis', {})
    price_info = detail.get('price', {})
    thumb = detail.get('thumb', {})
    qty = detail.get('qty', {})
    desc = detail.get('desc', {})
    deli = detail.get('deli', {})

    name = basis.get('title', '')

    # 가격 파싱 (수량별 가격인 경우 첫 번째 가격 사용)
    dome_price = price_info.get('dome', 0)
    if isinstance(dome_price, str) and '|' in dome_price:
        first_price = dome_price.split('|')[0]
        if '+' in first_price:
            price = int(first_price.split('+')[1])
        else:
            price = int(first_price) if first_price.isdigit() else 0
    else:
        try:
            price = int(dome_price or 0)
        except (ValueError, TypeError):
            price = 0

    # 마진 적용 판매가 (100원 단위 올림)
    margin_price = int(price * margin_rate)
    margin_price = ((margin_price + 99) // 100) * 100  # 100원 단위 올림

    # 대표 이미지
    image_url = (
        thumb.get('original') or
        thumb.get('large') or
        thumb.get('largePng') or ''
    )

    # 상세 이미지 추출 (API 제공 이미지 + HTML 내 이미지)
    add_images = detail.get('addImage', [])
    detail_images = []
    if isinstance(add_images, list):
        detail_images = [img.get('url', img) if isinstance(img, dict) else img for img in add_images[:5]]
    elif isinstance(add_images, dict):
        detail_images = [add_images.get('url', '')]

    # 상세설명 HTML
    contents = desc.get('contents', {})
    item_html = contents.get('item', '') if isinstance(contents, dict) else ''
    notice_html = desc.get('notice', '') or desc.get('content', '')
    detail_html = item_html or notice_html

    # 상세 이미지가 없으면 HTML에서 추출
    if not detail_images and detail_html:
        detail_images = extract_detail_images(detail_html)[:5]
        if detail_images:
            print(f"  [INFO] 추가 이미지가 없어 상세설명에서 {len(detail_images)}개를 추출했습니다.")

    # 옵션 정보
    select_opt = detail.get('selectOpt', '')
    options, option_group_name, option_groups = parse_domeggook_options(select_opt)

    # 배송비
    delivery_fee = 3000
    if isinstance(deli, dict):
        dome_deli = deli.get('dome', {})
        if isinstance(dome_deli, dict):
            delivery_fee = int(dome_deli.get('fee', 3000) or 3000)
        else:
            delivery_fee = int(deli.get('fee', 3000) or 3000)

    # 최소주문수량
    min_quantity = int(qty.get('domeMoq', 1) or 1) if isinstance(qty, dict) else 1

    # 카테고리
    category = detail.get('category', {})
    category_code = category.get('code', '') if isinstance(category, dict) else ''
    category_name = category.get('name', '') if isinstance(category, dict) else ''

    # 브랜드, 판매자
    brand = detail.get('brand', {}).get('name', '') if isinstance(detail.get('brand'), dict) else ''
    seller_id = detail.get('seller', {}).get('id', '') if isinstance(detail.get('seller'), dict) else ''

    # 라이선스 정보
    license_info = desc.get('license', {})
    license_msg = license_info.get('msg', '') if isinstance(license_info, dict) else ''

    # KC 인증 정보 추출
    detail_section = detail.get('detail', {})
    safety_cert = detail_section.get('safetyCert', []) if isinstance(detail_section, dict) else []
    kc_cert_list = []
    # 유효하지 않은 인증번호 패턴
    INVALID_CERT_PATTERNS = ['-', '상세', '참조', '없음', '해당없음', 'N/A', 'n/a', '확인중']
    if isinstance(safety_cert, list):
        for cert in safety_cert:
            if isinstance(cert, dict) and cert.get('cert') == 'Y':
                # KC 인증이 있는 경우
                cert_type = cert.get('certType', cert.get('type', ''))  # 전기용품, 방송통신기자재 등
                cert_name = cert.get('certName', cert.get('name', ''))  # 안전확인, 적합인증 등
                cert_no = cert.get('no', '')  # 인증번호
                # 유효한 인증번호인지 확인 (최소 5자 이상, 특수 패턴 제외)
                if cert_no and len(cert_no) >= 5:
                    is_valid = not any(p in cert_no for p in INVALID_CERT_PATTERNS)
                    if is_valid:
                        kc_cert_list.append({
                            'type': cert_type,
                            'name': cert_name,
                            'no': cert_no
                        })
                        print(f"  [INFO] KC 인증 발견: {cert_type} {cert_name} ({cert_no})")

    return DomeggookProduct(
        item_no=item_no,
        name=name,
        price=price,
        margin_price=margin_price,
        image_url=image_url,
        detail_images=detail_images,
        detail_html=detail_html,
        options=options,
        option_group_name=option_group_name,
        option_groups=option_groups,
        delivery_fee=delivery_fee,
        category_code=category_code,
        category_name=category_name,
        min_quantity=min_quantity,
        brand=brand,
        seller_id=seller_id,
        license_msg=license_msg,
        option_info=str(select_opt)[:500] if select_opt else "",
        kc_cert=kc_cert_list
    )


# ============================================================================
# 상세설명 HTML 생성
# ============================================================================
def build_detail_content(product: DomeggookProduct, uploaded_images: List[str]) -> str:
    """
    네이버에 업로드된 이미지로 상세설명 HTML 생성

    Args:
        product: 도매꾹 상품 정보
        uploaded_images: 네이버에 업로드된 이미지 URL 리스트

    Returns:
        상세설명 HTML
    """
    html = f'''
<div style="text-align:center; padding:20px; max-width:900px; margin:0 auto;">
    <h2 style="font-size:24px; margin-bottom:20px;">{product.name}</h2>
'''

    for i, img_url in enumerate(uploaded_images):
        html += f'''
    <div style="margin-bottom:10px;">
        <img src="{img_url}" style="max-width:100%; height:auto;" alt="상품 상세 이미지 {i+1}" />
    </div>
'''

    html += '''
</div>
'''
    return html


# ============================================================================
# 네이버 상품 등록
# ============================================================================
def register_to_naver(
    product: DomeggookProduct,
    naver_api: NaverCommerceAPI,
    category_id: str = None,
    display: bool = False,
    check_min_quantity: bool = False
) -> Tuple[Optional[str], Optional[str], Optional[int]]:
    """
    도매꾹 상품을 네이버에 등록

    Args:
        product: 도매꾹 상품 정보
        naver_api: NaverCommerceAPI 인스턴스
        category_id: 네이버 카테고리 ID
        display: True면 전시, False면 비전시
        check_min_quantity: 최소구매수량 체크 여부

    Returns:
        (채널상품번호, 원상품번호, 판매가) 또는 (None, None, None)
    """
    # 최소구매수량 체크
    if check_min_quantity and product.min_quantity > 1:
        print(f"  [SKIP] 최소구매수량 {product.min_quantity}개 - 1개만 허용")
        return None, None, None

    # 판매가 100원 단위 올림
    sale_price = ((product.margin_price + 99) // 100) * 100
    margin = sale_price - product.price

    # 마진율 계산 (옵션 추가금액에도 동일 적용)
    margin_rate = sale_price / product.price if product.price > 0 else 1.3

    print(f"\n[상품 등록] {product.name}")
    print(f"  도매꾹 상품번호: {product.item_no}")
    print(f"  도매가: {product.price:,}원 → 판매가: {sale_price:,}원 (마진: {margin:,}원)")

    # 1. 대표 이미지 업로드
    print(f"  대표 이미지 업로드 중...")
    uploaded_image = None
    if product.image_url:
        uploaded_image = naver_api.upload_image(product.image_url)

    if not uploaded_image:
        print("  [ERROR] 대표 이미지 업로드 실패!")
        return None, None, None

    print(f"  대표 이미지 업로드 성공")

    # 2. 상세 이미지 업로드
    uploaded_detail_images = [uploaded_image]  # 대표 이미지 포함

    if product.detail_images:
        print(f"  상세 이미지 업로드 중... ({len(product.detail_images)}개)")
        for i, img_url in enumerate(product.detail_images):
            print(f"    [{i+1}/{len(product.detail_images)}] 업로드 중...")
            uploaded = naver_api.upload_image(img_url)
            if uploaded:
                uploaded_detail_images.append(uploaded)
                print(f"      → 성공")
            else:
                print(f"      → 실패 (스킵)")
    elif product.detail_html:
        # 상세 이미지가 없으면 HTML에서 추출하여 업로드
        html_images = extract_detail_images(product.detail_html)
        if html_images:
            print(f"  상세설명에서 추출된 이미지 업로드 중... ({len(html_images)}개)")
            for i, img_url in enumerate(html_images[:10]):  # 최대 10개
                print(f"    [{i+1}/{min(len(html_images), 10)}] 업로드 중...")
                uploaded = naver_api.upload_image(img_url)
                if uploaded:
                    uploaded_detail_images.append(uploaded)

    # 3. 상세설명 HTML 생성 (업로드된 이미지 사용)
    detail_content = build_detail_content(product, uploaded_detail_images)
    print(f"  상세설명: {len(detail_content)} 글자, 이미지 {len(uploaded_detail_images)}개")

    # 4. 배송비 결정 (마진 >= 도매꾹 배송비면 무료배송)
    domeggook_delivery_fee = product.delivery_fee or 0
    if domeggook_delivery_fee == 0:
        # 도매꾹이 무료배송이면 네이버도 무료배송
        naver_delivery_fee = 0
        delivery_fee_type = "FREE"
        print(f"  배송비: 무료 (도매꾹 무료배송)")
    elif margin >= domeggook_delivery_fee:
        # 마진 >= 배송비면 무료배송 (배송비는 마진에서 부담)
        naver_delivery_fee = 0
        delivery_fee_type = "FREE"
        print(f"  배송비: 무료 (마진 {margin:,}원 >= 배송비 {domeggook_delivery_fee:,}원)")
    else:
        # 마진 < 배송비면 유료배송 (고객이 배송비 부담)
        naver_delivery_fee = domeggook_delivery_fee
        delivery_fee_type = "PAID"
        print(f"  배송비: {naver_delivery_fee:,}원 (마진 {margin:,}원 < 배송비 {domeggook_delivery_fee:,}원)")

    # 5. 배송 정보
    delivery_info = {
        "deliveryType": "DELIVERY",
        "deliveryAttributeType": "NORMAL",
        "deliveryCompany": "CJGLS",
        "deliveryFee": {
            "deliveryFeeType": delivery_fee_type,
            "baseFee": naver_delivery_fee,
            "deliveryFeePayType": "PREPAID"
        },
        "claimDeliveryInfo": {
            "returnDeliveryFee": 3000,
            "exchangeDeliveryFee": 6000,
            "shippingAddressId": None,
            "returnAddressId": None
        }
    }

    address_info = naver_api._get_seller_address()
    if address_info:
        delivery_info["claimDeliveryInfo"]["shippingAddressId"] = address_info.get("shippingAddressId")
        delivery_info["claimDeliveryInfo"]["returnAddressId"] = address_info.get("returnAddressId")

    # 6. 옵션 처리 (1단~3단 옵션 지원)
    option_info = None
    total_stock = 0

    if product.options:
        option_combinations = []

        # 옵션 그룹명 출력
        if product.option_groups:
            group_names = [g.name for g in product.option_groups]
            print(f"  옵션 그룹: {' / '.join(group_names)} ({len(product.options)}개 조합)")
        else:
            print(f"  옵션 ({product.option_group_name}): {len(product.options)}개")

        soldout_count = 0
        for opt in product.options:
            stock = opt.stock if not opt.is_soldout else 0
            total_stock += stock
            if opt.is_soldout:
                soldout_count += 1

            # 옵션값 표시 (다단인 경우 / 로 연결)
            if opt.value2:
                opt_display = f"{opt.value}/{opt.value2}"
                if opt.value3:
                    opt_display += f"/{opt.value3}"
            else:
                opt_display = opt.value

            status = "품절" if opt.is_soldout else f"재고 {stock}"

            # 옵션 추가금액에도 마진율 적용 (100원 단위 올림)
            if opt.price_diff > 0:
                option_price_with_margin = int(opt.price_diff * margin_rate)
                option_price_with_margin = ((option_price_with_margin + 99) // 100) * 100
                price_info = f", +{opt.price_diff:,}원→+{option_price_with_margin:,}원"
            else:
                option_price_with_margin = 0
                price_info = ""
            print(f"    - {opt_display}: {status}{price_info}")

            # 옵션값에서 특수문자 제거 (\ * ? " < > 불허)
            def clean_option_value(val: str) -> str:
                if not val:
                    return ""
                # 불허 특수문자 제거
                for char in ['\\', '*', '?', '"', '<', '>']:
                    val = val.replace(char, '')
                return val.strip()[:25]  # 25자 제한

            # 네이버 옵션 조합 생성
            combo = {
                "optionName1": clean_option_value(opt.value),
                "stockQuantity": stock,
                "price": option_price_with_margin,  # 마진 적용된 추가금액
                "usable": True  # 항상 true, 품절은 재고 0으로만 표시
            }

            # 2단 옵션
            if opt.value2:
                combo["optionName2"] = clean_option_value(opt.value2)

            # 3단 옵션
            if opt.value3:
                combo["optionName3"] = clean_option_value(opt.value3)

            option_combinations.append(combo)

        if soldout_count > 0:
            print(f"  품절 옵션: {soldout_count}개")

        # 옵션 그룹명 설정
        option_group_names = {}
        if product.option_groups:
            for i, group in enumerate(product.option_groups[:3], 1):
                option_group_names[f"optionGroupName{i}"] = group.name
        else:
            option_group_names["optionGroupName1"] = product.option_group_name

        option_info = {
            "optionCombinationSortType": "CREATE",
            "optionCombinationGroupNames": option_group_names,
            "optionCombinations": option_combinations,
            "useStockManagement": True
        }
    else:
        total_stock = 100
        print(f"  옵션 없음 (재고: {total_stock})")

    # 7. 상품 데이터 구성
    product_data = {
        "originProduct": {
            "statusType": "SALE",
            "saleType": "NEW",
            "name": product.name,
            "detailContent": detail_content,
            "images": {
                "representativeImage": {"url": uploaded_image},
                "optionalImages": [{"url": img} for img in uploaded_detail_images[1:5]]  # 최대 4개 추가 이미지
            },
            "salePrice": sale_price,
            "stockQuantity": total_stock,
            "leafCategoryId": category_id,
            "deliveryInfo": delivery_info,
            "detailAttribute": {
                "naverShoppingSearchInfo": {"manufacturerMadeProductYn": False},
                "afterServiceInfo": {
                    "afterServiceTelephoneNumber": "010-0000-0000",
                    "afterServiceGuideContent": "상세페이지 참조"
                },
                "originAreaInfo": {"originAreaCode": "03", "content": "상세페이지 참조"},
                "minorPurchasable": True,
                "productInfoProvidedNotice": {
                    "productInfoProvidedNoticeType": "ETC",
                    "etc": {
                        "returnCostReason": "상세페이지 참조",
                        "noRefundReason": "상세페이지 참조",
                        "qualityAssuranceStandard": "상세페이지 참조",
                        "compensationProcedure": "상세페이지 참조",
                        "troubleShootingContents": "상세페이지 참조",
                        "itemName": "상세페이지 참조",
                        "modelName": "상세페이지 참조",
                        "manufacturer": "상세페이지 참조",
                        "customerServicePhoneNumber": "010-0000-0000"
                    }
                }
            }
        },
        "smartstoreChannelProduct": {
            "channelProductName": product.name,
            "channelProductDisplayStatusType": "SUSPENSION",  # 전시중지 (미전시)
            "naverShoppingRegistration": False
        }
    }

    # 옵션 정보 추가
    if option_info:
        product_data["originProduct"]["detailAttribute"]["optionInfo"] = option_info

    # KC인증 정보 추가
    if product.kc_cert:
        # KC인증이 있는 경우
        cert_infos = []
        for cert in product.kc_cert:
            cert_infos.append({
                "certificationKindType": "KC_CERTIFICATION",
                "name": f"{cert.get('type', '')} {cert.get('name', '')}".strip(),
                "certificationNumber": cert.get('no', ''),
                "certificationMark": True
            })
        if cert_infos:
            product_data["originProduct"]["detailAttribute"]["productCertificationInfos"] = cert_infos
            product_data["originProduct"]["detailAttribute"]["certificationTargetExcludeContent"] = {
                "kcCertifiedProductExclusionYn": "FALSE",  # KC인증 대상임
                "childCertifiedProductExclusionYn": "TRUE"  # 어린이제품 인증 대상 아님 (KC로 대체)
            }
            print(f"  KC인증 정보 {len(cert_infos)}개 추가됨")
    else:
        # KC인증이 없는 경우 - 인증 대상 제외로 설정
        product_data["originProduct"]["detailAttribute"]["certificationTargetExcludeContent"] = {
            "kcCertifiedProductExclusionYn": "TRUE",  # KC인증 대상 아님
            "childCertifiedProductExclusionYn": "TRUE"  # 어린이제품 인증 대상 아님
        }

    # 8. 상품 등록 요청
    print(f"  등록 요청 중...")
    headers = naver_api._get_headers()

    response = requests.post(
        f"{naver_api.BASE_URL}/external/v2/products",
        headers=headers,
        json=product_data,
        timeout=60
    )

    if response.status_code in [200, 201]:
        result = response.json()
        channel_product_no = result.get("smartstoreChannelProductNo") or result.get("originProductNo")
        origin_product_no = result.get("originProductNo")

        print(f"  등록 성공!")
        print(f"    채널상품번호: {channel_product_no}")
        print(f"    원상품번호: {origin_product_no}")
        print(f"    전시상태: {'전시' if display else '비전시'}")

        return channel_product_no, origin_product_no, sale_price
    else:
        print(f"  [ERROR] 등록 실패: {response.status_code}")
        print(f"  {response.text[:500]}")
        return None, None, None


# ============================================================================
# 카테고리 자동 매칭 (AI 분류 + 키워드 매칭)
# ============================================================================
# 카테고리 캐시 (모듈 레벨)
_category_cache = None
_leaf_category_cache = None

# 제외 카테고리 (권한 필요 또는 특수 인증 필요)
EXCLUDED_CATEGORY_KEYWORDS = [
    '출산', '육아', '유아', '아동',  # KC인증 필수
    '도서', '책', 'e북', '음반',      # ISBN 필수
    '주류', '와인', '맥주', '소주', '위스키', '전통주', '과일주',  # 주류 판매 권한 필요
    '의약품', '의약외품', '건강기능식품',  # 의약품 판매 권한 필요
    '담배', '전자담배',  # 담배 판매 권한 필요
]


def _load_categories(naver_api: NaverCommerceAPI):
    """네이버 카테고리 목록 로드 (캐싱)"""
    global _category_cache, _leaf_category_cache

    if _category_cache is not None:
        return

    import requests
    headers = naver_api._get_headers()
    response = requests.get(
        f"{naver_api.BASE_URL}/external/v1/categories",
        headers=headers,
        timeout=60
    )

    if response.status_code == 200:
        _category_cache = response.json()
        _leaf_category_cache = [c for c in _category_cache if c.get('last') is True]
        print(f"  [카테고리] {len(_leaf_category_cache)}개 리프 카테고리 로드됨")
    else:
        _category_cache = []
        _leaf_category_cache = []


def _classify_with_ai(product_name: str, domeggook_category: str = "") -> Optional[str]:
    """AI로 상품 카테고리 분류"""
    if not OPENAI_AVAILABLE:
        return None

    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        return None

    try:
        client = OpenAI(api_key=api_key)

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

        response = client.chat.completions.create(
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


def _match_ai_category(ai_category: str) -> Optional[str]:
    """AI 추천 카테고리에 맞는 네이버 카테고리 ID 찾기"""
    global _leaf_category_cache

    if not _leaf_category_cache or not ai_category:
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

    for cat in _leaf_category_cache:
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
        return best_cat.get('id'), best_cat.get('wholeCategoryName', '')

    return None, None


def find_category(naver_api: NaverCommerceAPI, search_term: str, domeggook_category: str = None) -> Optional[str]:
    """
    카테고리 자동 매칭 (AI 분류 우선)

    1순위: AI 카테고리 분류 (가장 정확함)
    2순위: 도매꾹 카테고리명으로 매칭
    3순위: 상품명 키워드로 매칭
    4순위: 네이버 쇼핑 API 검색
    """
    global _leaf_category_cache

    # 카테고리 로드 (최초 1회)
    _load_categories(naver_api)

    if not _leaf_category_cache:
        return None

    # 1순위: AI 카테고리 분류 시도
    if USE_AI_CATEGORY and OPENAI_AVAILABLE:
        print(f"  카테고리 매칭: AI 분류 시도...")
        ai_category = _classify_with_ai(search_term, domeggook_category or "")
        if ai_category:
            print(f"    [AI] 추천: {ai_category}")
            cat_id, cat_name = _match_ai_category(ai_category)
            if cat_id:
                cat_short = cat_name.split('>')[-1].strip() if cat_name else ""
                print(f"    [AI] 매칭: {cat_short} ({cat_id})")
                return cat_id

    # 제외할 일반적인 단어 (카테고리 매칭에 부적합)
    SKIP_WORDS = {
        '국산', '수입', '정품', '신상', '신제품', '특가', '할인', '세일', '무료배송',
        '당일발송', '빠른배송', '인기', '추천', '베스트', '한정', '단독', '공식',
        '정식', '오리지널', '프리미엄', '고급', '신형', '구형', '최신', '업그레이드',
        '한일', '삼성', 'lg', '대우', '위닉스', '쿠쿠', '필립스',  # 브랜드명
        '1개', '2개', '3개', '1ea', '2ea', '세트', 'set', '묶음',
        '대용량', '소용량', '미니', '빅', '라지', '스몰',
    }

    # 제외 카테고리 (권한 필요 또는 특수 인증 필요)
    EXCLUDED_KEYWORDS = EXCLUDED_CATEGORY_KEYWORDS

    # 검색 키워드 목록 생성
    search_keywords = []

    # 1순위: 도매꾹 카테고리명 (가장 신뢰도 높음)
    if domeggook_category:
        cat_parts = [p.strip() for p in domeggook_category.split('>')]
        for part in reversed(cat_parts):
            if part and len(part) >= 2 and part.lower() not in SKIP_WORDS:
                search_keywords.append(part)

    # 2순위: 상품명에서 키워드 추출 (마지막 단어 = 품목명 우선)
    if search_term:
        import re
        clean_name = re.sub(r'[\[\]\(\)\{\}]', ' ', search_term)
        parts = [p for p in clean_name.split() if p.lower() not in SKIP_WORDS and len(p) >= 2]
        if parts:
            # 마지막 단어부터 (품목명일 가능성 높음)
            for p in reversed(parts[-3:]):
                search_keywords.append(p)
            # 나머지 단어
            for p in parts[:-3]:
                search_keywords.append(p)

    # 중복 제거
    unique_keywords = []
    seen = set()
    for kw in search_keywords:
        kw_lower = kw.lower()
        if kw and kw_lower not in seen and len(kw) >= 2 and kw_lower not in SKIP_WORDS:
            unique_keywords.append(kw)
            seen.add(kw_lower)

    if not unique_keywords:
        return None

    print(f"  카테고리 매칭 시도 중... (키워드: {unique_keywords[:5]})")

    for keyword in unique_keywords:
        keyword_lower = keyword.lower()

        # 1. 정확 일치: 카테고리명의 마지막 부분이 키워드와 일치
        exact_matches = []
        for cat in _leaf_category_cache:
            whole_name = cat.get('wholeCategoryName', '')
            # 제외 카테고리 필터링
            if any(ex in whole_name.lower() for ex in EXCLUDED_KEYWORDS):
                continue
            cat_parts = whole_name.split('>')
            if cat_parts:
                last_part = cat_parts[-1].strip().lower()
                if last_part == keyword_lower:
                    exact_matches.append(cat)

        if exact_matches:
            best = exact_matches[0]
            print(f"    -> 정확 일치: {best.get('wholeCategoryName')} ({best.get('id')})")
            return best.get('id')

        # 2. 부분 일치: 카테고리명에 키워드 포함
        partial_matches = []
        for cat in _leaf_category_cache:
            whole_name = cat.get('wholeCategoryName', '').lower()
            if keyword_lower in whole_name:
                partial_matches.append(cat)

        # 제외 카테고리 필터링
        partial_matches = [
            cat for cat in partial_matches
            if not any(ex in cat.get('wholeCategoryName', '').lower() for ex in EXCLUDED_KEYWORDS)
        ]

        if partial_matches:
            # 깊이가 깊은 카테고리 우선 (더 구체적)
            partial_matches.sort(key=lambda x: x.get('wholeCategoryName', '').count('>'), reverse=True)
            best = partial_matches[0]
            print(f"    -> 부분 일치: {best.get('wholeCategoryName')} ({best.get('id')})")
            return best.get('id')

    # 3. 네이버 쇼핑 API로 검색해서 카테고리 찾기
    print(f"  [INFO] 네이버 쇼핑 API로 카테고리 검색 중...")
    try:
        from naver_shopping import NaverShoppingAPI
        shopping_api = NaverShoppingAPI()

        # 상품명으로 검색
        items = shopping_api.search_products(search_term, display=5)
        if items:
            # 검색 결과에서 카테고리 추출
            for item in items:
                cat1 = item.get('category1', '')
                cat2 = item.get('category2', '')
                cat3 = item.get('category3', '')
                cat4 = item.get('category4', '')

                # 가장 구체적인 카테고리부터 매칭 시도
                for cat_name in [cat4, cat3, cat2, cat1]:
                    if not cat_name or len(cat_name) < 2:
                        continue
                    # 제외 카테고리 체크
                    if any(ex in cat_name.lower() for ex in EXCLUDED_KEYWORDS):
                        continue

                    cat_lower = cat_name.lower()
                    for cat in _leaf_category_cache:
                        whole_name = cat.get('wholeCategoryName', '').lower()
                        if any(ex in whole_name for ex in EXCLUDED_KEYWORDS):
                            continue
                        if cat_lower in whole_name:
                            print(f"    -> 쇼핑API 매칭: {cat.get('wholeCategoryName')} ({cat.get('id')})")
                            return cat.get('id')
    except Exception as e:
        print(f"  [WARN] 쇼핑 API 검색 실패: {e}")

    print(f"  [WARN] 매칭되는 카테고리를 찾지 못했습니다.")
    return None


# ============================================================================
# 메인 함수
# ============================================================================
def main():
    # 터미널에서 모든 입력 받기
    print("=" * 60)
    print("도매꾹 상품 간편 등록")
    print("=" * 60)
    print()

    # 1. 상품 링크/번호 입력
    link_input = input("상품 링크 또는 번호: ").strip()
    if not link_input:
        print("입력된 정보가 없습니다.")
        return

    item_no = extract_item_id(link_input)
    if not item_no:
        print(f"[ERROR] 유효하지 않은 링크입니다: {link_input}")
        return

    # 2. 카테고리 ID 입력 (선택)
    category_input = input("카테고리 ID (없으면 Enter로 자동 매칭): ").strip()
    category_id = category_input if category_input else None

    # 3. 전시 상태 입력
    display_input = input("전시 상태 (y=전시, Enter=비전시): ").strip().lower()
    display = display_input in ['y', 'yes', '전시']

    # 4. 최소구매수량 체크 여부
    moq_input = input("최소구매수량 체크 (y=체크, Enter=체크안함): ").strip().lower()
    check_moq = moq_input in ['y', 'yes']

    print()
    print("-" * 60)
    print(f"  상품번호: {item_no}")
    print(f"  카테고리: {'자동 매칭' if not category_id else category_id}")
    print(f"  전시상태: {'전시' if display else '비전시'}")
    print(f"  마진율: 30% (고정)")
    print("-" * 60)

    # 2. 도매꾹 상품 정보 조회
    print("\n[1/2] 도매꾹 상품 정보 조회 중...")
    try:
        product = get_domeggook_product(item_no, margin_rate=1.3)

        if not product:
            print(f"  [ERROR] 도매꾹 API에서 상품 정보를 가져올 수 없습니다.")
            print(f"  - 상품번호: {item_no}")
            print(f"  - 웹사이트 확인: https://domeggook.com/{item_no}")
            return

        print(f"  상품명: {product.name}")
        print(f"  도매가: {product.price:,}원")
        print(f"  판매가: {product.margin_price:,}원 (마진: {product.margin_price - product.price:,}원)")
        print(f"  최소구매수량: {product.min_quantity}개")
        print(f"  대표이미지: {'있음' if product.image_url else '없음'}")
        print(f"  상세이미지: {len(product.detail_images)}개")
        print(f"  옵션: {len(product.options)}개")

        if product.license_msg:
            print(f"  라이선스: {product.license_msg}")

    except Exception as e:
        print(f"  [ERROR] 도매꾹 API 조회 실패: {e}")
        import traceback
        traceback.print_exc()
        return

    # 3. 네이버 스마트스토어 등록
    print("\n[2/2] 네이버 스마트스토어 등록 시도...")
    try:
        naver = NaverCommerceAPI()

        # 카테고리 확인
        if not category_id:
            category_id = find_category(naver, product.name, product.category_name)

        if not category_id:
            # 기본 카테고리 사용 (생활/건강 > 생활잡화 > 기타생활잡화)
            DEFAULT_CATEGORY_ID = "50000803"
            print(f"  [WARN] 카테고리 매칭 실패 - 기본 카테고리 사용 ({DEFAULT_CATEGORY_ID})")
            category_id = DEFAULT_CATEGORY_ID

        # 상품 등록
        channel_no, origin_no, final_price = register_to_naver(
            product=product,
            naver_api=naver,
            category_id=category_id,
            display=display,
            check_min_quantity=check_moq
        )

        if channel_no:
            print("\n" + "=" * 60)
            print("등록 성공!")
            print("=" * 60)
            print(f"  네이버 채널상품번호: {channel_no}")
            print(f"  네이버 원상품번호: {origin_no}")
            print(f"  도매꾹 상품번호: {product.item_no}")
            print(f"  상품명: {product.name}")
            print(f"  도매가: {product.price:,}원")
            print(f"  판매가: {final_price:,}원")
            print(f"  마진: {final_price - product.price:,}원")
            print(f"  전시상태: {'전시' if display else '비전시'}")
            print(f"\n  상품 관리 링크:")
            print(f"  https://smartstore.naver.com/dohsohmall/products/{channel_no}")

            # 구글 시트 저장
            try:
                print("\n  구글 시트에 등록 이력 저장 중...")
                sheets = GoogleSheetsManager()

                # 옵션 정보 요약
                option_summary = ""
                if product.options:
                    soldout_count = sum(1 for opt in product.options if opt.is_soldout)
                    option_summary = f"{len(product.options)}개 옵션"
                    if soldout_count > 0:
                        option_summary += f" (품절 {soldout_count}개)"
                else:
                    option_summary = "옵션없음"

                sheets.save_registered_product(
                    domeggook_no=product.item_no,
                    naver_channel_no=channel_no,
                    naver_origin_no=origin_no,
                    name=product.name,
                    domeggook_price=product.price,
                    naver_price=final_price,
                    options=option_summary,
                    min_quantity=product.min_quantity,
                    status="전시" if display else "비전시",
                    margin_rate=30.0  # 30% 마진
                )
                print("  구글 시트 저장 완료")
            except Exception as e:
                print(f"  [WARN] 구글 시트 저장 실패: {e}")
        else:
            print("\n[ERROR] 상품 등록에 실패했습니다.")

    except Exception as e:
        print(f"  [ERROR] 네이버 등록 처리 중 오류: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
