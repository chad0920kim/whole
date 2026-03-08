# -*- coding: utf-8 -*-
"""
도매꾹 → 네이버 상품 등록 통합 모듈
====================================
- 도매꾹 상세 이미지 추출 및 반영
- 옵션 품절/판매종료 처리 (재고 0)
- 비전시 상태로 등록
"""
import sys
import io
import re
import json
import requests
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field

if sys.platform == "win32" and not isinstance(sys.stdout, io.TextIOWrapper):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from domeggook_image import DomeggookImageAPI
from naver_commerce import NaverCommerceAPI


# 품절/판매종료 키워드
SOLDOUT_KEYWORDS = ['품절', '판매종료', '판매중지', '재고없음', '매진', 'sold out', 'soldout']


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
    """도매꾹 상품 정보"""
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


def get_domeggook_product(item_no: str) -> Optional[DomeggookProduct]:
    """
    도매꾹 상품 정보 조회 (상세 이미지, 옵션 포함)

    Args:
        item_no: 도매꾹 상품번호

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

    name = basis.get('title', '')

    # 가격 파싱 (수량별 가격인 경우 첫 번째 가격 사용)
    dome_price = price_info.get('dome', 0)
    if isinstance(dome_price, str) and '|' in dome_price:
        # "1+1220|300+1210|1000+1200" 형식
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

    # 대표 이미지
    image_url = (
        thumb.get('original') or
        thumb.get('large') or
        thumb.get('largePng') or ''
    )

    # 상세 이미지 추출
    desc = detail.get('desc', {})
    contents = desc.get('contents', {})
    item_html = contents.get('item', '') if isinstance(contents, dict) else ''
    detail_images = extract_detail_images(item_html)

    # 옵션 정보
    select_opt = detail.get('selectOpt', '')
    options, option_group_name, option_groups = parse_domeggook_options(select_opt)

    # 배송비
    deli = detail.get('deli', {})
    if isinstance(deli, dict):
        dome_deli = deli.get('dome', {})
        if isinstance(dome_deli, dict):
            delivery_fee = int(dome_deli.get('fee', 3000) or 3000)
        else:
            delivery_fee = int(deli.get('fee', 3000) or 3000)
    else:
        delivery_fee = 3000

    # 최소주문수량
    qty = detail.get('qty', {})
    min_quantity = int(qty.get('domeMoq', 1) or 1) if isinstance(qty, dict) else 1

    # 카테고리
    category = detail.get('category', {})
    category_code = category.get('code', '') if isinstance(category, dict) else ''
    category_name = category.get('name', '') if isinstance(category, dict) else ''

    return DomeggookProduct(
        item_no=item_no,
        name=name,
        price=price,
        image_url=image_url,
        detail_images=detail_images,
        detail_html=item_html,
        options=options,
        option_group_name=option_group_name,
        option_groups=option_groups,
        delivery_fee=delivery_fee,
        category_code=category_code,
        category_name=category_name,
        min_quantity=min_quantity
    )


def build_detail_content(product: DomeggookProduct, uploaded_image: str) -> str:
    """
    네이버 상세설명 HTML 생성

    Args:
        product: 도매꾹 상품 정보
        uploaded_image: 업로드된 대표 이미지 URL

    Returns:
        상세설명 HTML
    """
    # 도매꾹 원본 상세설명 HTML이 있으면 그대로 사용
    if product.detail_html and len(product.detail_html) > 100:
        return product.detail_html

    # 원본 HTML이 없으면 이미지로 구성
    html = f'''
<div style="text-align:center; padding:20px; max-width:900px; margin:0 auto;">
    <h2 style="font-size:24px; margin-bottom:20px;">{product.name}</h2>
'''

    # 상세 이미지가 있으면 사용
    if product.detail_images:
        for i, img_url in enumerate(product.detail_images):
            html += f'''
    <div style="margin-bottom:10px;">
        <img src="{img_url}" style="max-width:100%; height:auto;" alt="상품 상세 이미지 {i+1}" />
    </div>
'''
    else:
        # 상세 이미지가 없으면 대표 이미지 사용
        html += f'''
    <div style="margin-bottom:10px;">
        <img src="{uploaded_image}" style="max-width:100%; height:auto;" alt="상품 이미지" />
    </div>
'''

    html += '''
</div>
'''
    return html


def build_detail_content_with_uploaded_images(product: DomeggookProduct, uploaded_images: list) -> str:
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


def register_to_naver(
    product: DomeggookProduct,
    category_id: str = "50000561",
    price_multiplier: float = 1.5,
    display: bool = False,
    name_prefix: str = ""
) -> Tuple[Optional[str], Optional[str], Optional[int]]:
    """
    도매꾹 상품을 네이버에 등록

    Args:
        product: 도매꾹 상품 정보
        category_id: 네이버 카테고리 ID
        price_multiplier: 가격 배율 (기본 1.5배)
        display: True면 전시, False면 비전시
        name_prefix: 상품명 앞에 붙일 접두사

    Returns:
        (채널상품번호, 원상품번호, 판매가) 또는 (None, None, None)
    """
    naver_api = NaverCommerceAPI()

    # 판매가 계산
    sale_price = int(product.price * price_multiplier)

    print(f"\n[상품 등록] {product.name}")
    print(f"  도매꾹 상품번호: {product.item_no}")
    print(f"  도매가: {product.price:,}원 → 판매가: {sale_price:,}원")

    # 1. 대표 이미지 업로드
    print(f"  이미지 업로드 중...")
    uploaded_image = None
    if product.image_url:
        uploaded_image = naver_api.upload_image(product.image_url)

    if not uploaded_image:
        print("  이미지 업로드 실패!")
        return None, None, None

    print(f"  이미지 업로드 성공")

    # 2. 상세설명 생성
    detail_content = build_detail_content(product, uploaded_image)
    print(f"  상세설명: {len(detail_content)} 글자, 이미지 {len(product.detail_images)}개")

    # 3. 배송 정보
    delivery_info = {
        "deliveryType": "DELIVERY",
        "deliveryAttributeType": "NORMAL",
        "deliveryCompany": "CJGLS",
        "deliveryFee": {
            "deliveryFeeType": "PAID",
            "baseFee": 3000,
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

    # 4. 옵션 처리 (1단~3단 옵션 지원)
    option_info = None
    total_stock = 0

    if product.options:
        option_combinations = []
        num_option_groups = len(product.option_groups) if product.option_groups else 1

        # 옵션 그룹명 출력
        if product.option_groups:
            group_names = [g.name for g in product.option_groups]
            print(f"  옵션 그룹: {' / '.join(group_names)} ({len(product.options)}개 조합)")
        else:
            print(f"  옵션 ({product.option_group_name}): {len(product.options)}개")

        for opt in product.options:
            stock = opt.stock if not opt.is_soldout else 0
            total_stock += stock

            # 옵션값 표시 (다단인 경우 / 로 연결)
            if opt.value2:
                opt_display = f"{opt.value}/{opt.value2}"
                if opt.value3:
                    opt_display += f"/{opt.value3}"
            else:
                opt_display = opt.value

            status = "품절" if opt.is_soldout else f"재고 {stock}"
            print(f"    - {opt_display}: {status}")

            # 네이버 옵션 조합 생성
            combo = {
                "optionName1": opt.value[:25] if opt.value else "",  # 25자 제한
                "stockQuantity": stock,
                "price": opt.price_diff,
                "usable": True  # 항상 true, 품절은 재고 0으로만 표시
            }

            # 2단 옵션
            if opt.value2:
                combo["optionName2"] = opt.value2[:25] if opt.value2 else ""

            # 3단 옵션
            if opt.value3:
                combo["optionName3"] = opt.value3[:25] if opt.value3 else ""

            option_combinations.append(combo)

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

    # 5. 상품명
    product_name = f"{name_prefix}{product.name}" if name_prefix else product.name

    # 6. 상품 데이터 구성
    product_data = {
        "originProduct": {
            "statusType": "SALE",
            "saleType": "NEW",
            "name": product_name,
            "detailContent": detail_content,
            "images": {
                "representativeImage": {"url": uploaded_image},
                "optionalImages": []
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
            "channelProductName": product_name,
            "naverShoppingRegistration": False
        }
    }

    # 옵션 정보 추가
    if option_info:
        product_data["originProduct"]["detailAttribute"]["optionInfo"] = option_info

    # KC인증 대상 제외 설정 (기본)
    product_data["originProduct"]["detailAttribute"]["certificationTargetExcludeContent"] = {
        "kcCertifiedProductExclusionYn": "TRUE",  # KC인증 대상 아님
        "childCertifiedProductExclusionYn": "TRUE"  # 어린이제품 인증 대상 아님
    }

    # 7. 상품 등록 요청
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
        print(f"  등록 실패: {response.status_code}")
        print(f"  {response.text[:500]}")
        return None, None, None


def update_product_detail(
    channel_product_no: str,
    product: DomeggookProduct
) -> bool:
    """
    기존 네이버 상품의 상세설명 업데이트
    - 도매꾹 상세 이미지를 네이버에 업로드 후 사용

    Args:
        channel_product_no: 네이버 채널상품번호
        product: 도매꾹 상품 정보

    Returns:
        성공 여부
    """
    naver_api = NaverCommerceAPI()

    # 1. 기존 상품 조회
    print(f"\n[상세설명 업데이트] {channel_product_no}")
    naver_product = naver_api.get_product(channel_product_no)

    if not naver_product:
        print("  상품 조회 실패")
        return False

    origin = naver_product.get("originProduct", {})

    # 2. originProductNo 조회 (검색 API에서 channelProductNo로 정확히 찾기)
    origin_product_no = origin.get("originProductNo")
    headers = naver_api._get_headers()

    if not origin_product_no:
        search_response = requests.post(
            f"{naver_api.BASE_URL}/external/v1/products/search",
            headers=headers,
            json={"channelProductNos": [channel_product_no]},
            timeout=30
        )
        if search_response.status_code == 200:
            contents = search_response.json().get("contents", [])
            for content in contents:
                channel_products = content.get("channelProducts", [])
                for cp in channel_products:
                    if str(cp.get("channelProductNo")) == str(channel_product_no):
                        origin_product_no = content.get("originProductNo")
                        break
                if origin_product_no:
                    break

    if not origin_product_no:
        print("  originProductNo를 찾을 수 없습니다")
        return False

    print(f"  originProductNo: {origin_product_no}")

    # 3. origin-products API로 정확한 상품 정보 조회
    origin_response = requests.get(
        f"{naver_api.BASE_URL}/external/v2/products/origin-products/{origin_product_no}",
        headers=headers,
        timeout=30
    )
    if origin_response.status_code == 200:
        origin_data = origin_response.json()
        origin = origin_data.get("originProduct", origin)

    # 4. 대표 이미지 (기존 것 사용)
    images = origin.get("images", {})
    rep_image = images.get("representativeImage", {})
    uploaded_image = rep_image.get("url", "")

    # 5. 상세 이미지를 네이버에 업로드
    print(f"  상세 이미지 업로드 중... ({len(product.detail_images)}개)")
    uploaded_detail_images = []
    for i, img_url in enumerate(product.detail_images):
        print(f"    [{i+1}/{len(product.detail_images)}] {img_url[:50]}...")
        uploaded = naver_api.upload_image(img_url)
        if uploaded:
            uploaded_detail_images.append(uploaded)
            print(f"      → 업로드 성공")
        else:
            print(f"      → 업로드 실패, 원본 URL 사용")
            uploaded_detail_images.append(img_url)

    # 6. 업로드된 이미지로 상세설명 HTML 생성
    detail_content = build_detail_content_with_uploaded_images(product, uploaded_detail_images)
    print(f"  새 상세설명: {len(detail_content)} 글자, 이미지 {len(uploaded_detail_images)}개")

    # 6. 업데이트 데이터 (상세설명만 변경, 기존 detailAttribute 유지)
    update_data = {
        "originProduct": {
            "statusType": origin.get("statusType", "SALE"),
            "saleType": origin.get("saleType", "NEW"),
            "leafCategoryId": origin.get("leafCategoryId"),
            "name": origin.get("name"),
            "detailContent": detail_content,
            "salePrice": origin.get("salePrice"),
            "stockQuantity": origin.get("stockQuantity", 0),
            "images": images,
            "deliveryInfo": origin.get("deliveryInfo", {}),
            "detailAttribute": origin.get("detailAttribute", {})  # 필수 필드 - 기존 값 유지
        }
    }

    # 7. 업데이트 요청
    response = requests.put(
        f"{naver_api.BASE_URL}/external/v2/products/origin-products/{origin_product_no}",
        headers=headers,
        json=update_data,
        timeout=60
    )

    if response.status_code in [200, 204]:
        print("  업데이트 성공!")
        return True
    else:
        print(f"  업데이트 실패: {response.status_code}")
        print(f"  {response.text[:300]}")
        return False


def update_product_options(channel_product_no: str, domeggook_item_no: str) -> bool:
    """
    네이버 상품의 옵션 정보 업데이트 (품절 반영)

    Args:
        channel_product_no: 네이버 채널상품번호
        domeggook_item_no: 도매꾹 상품번호

    Returns:
        성공 여부
    """
    print(f"\n[옵션 업데이트] 네이버 {channel_product_no} ← 도매꾹 {domeggook_item_no}")

    # 1. 도매꾹 상품 정보 조회
    product = get_domeggook_product(domeggook_item_no)
    if not product:
        print("  도매꾹 상품 조회 실패")
        return False

    print(f"  상품명: {product.name}")
    print(f"  옵션 수: {len(product.options)}개")

    soldout_count = sum(1 for opt in product.options if opt.is_soldout)
    if soldout_count > 0:
        print(f"  품절 옵션: {soldout_count}개")

    # 2. 네이버 상품 조회
    naver_api = NaverCommerceAPI()
    naver_product = naver_api.get_product(channel_product_no)

    if not naver_product:
        print("  네이버 상품 조회 실패")
        return False

    origin = naver_product.get("originProduct", {})

    # originProductNo 조회
    origin_product_no = origin.get("originProductNo")
    headers = naver_api._get_headers()

    if not origin_product_no:
        search_response = requests.post(
            f"{naver_api.BASE_URL}/external/v1/products/search",
            headers=headers,
            json={"channelProductNos": [channel_product_no]},
            timeout=30
        )
        if search_response.status_code == 200:
            contents = search_response.json().get("contents", [])
            for content in contents:
                channel_products = content.get("channelProducts", [])
                for cp in channel_products:
                    if str(cp.get("channelProductNo")) == str(channel_product_no):
                        origin_product_no = content.get("originProductNo")
                        break
                if origin_product_no:
                    break

    if not origin_product_no:
        print("  originProductNo를 찾을 수 없습니다")
        return False

    # 3. 옵션 조합 생성 (품절 = 재고 0)
    option_combinations = []
    total_stock = 0

    for opt in product.options:
        stock = 0 if opt.is_soldout else opt.stock
        total_stock += stock

        combo = {
            "optionName1": opt.value[:25] if opt.value else "",
            "stockQuantity": stock,
            "price": opt.price_diff,
            "usable": True  # 항상 true, 품절은 재고 0으로만 표시
        }

        # 다단 옵션
        if opt.value2:
            combo["optionName2"] = opt.value2[:25]
        if opt.value3:
            combo["optionName3"] = opt.value3[:25]

        option_combinations.append(combo)

    # 4. 옵션 그룹명 설정
    option_group_names = {}
    if product.option_groups:
        for i, group in enumerate(product.option_groups[:3], 1):
            option_group_names[f"optionGroupName{i}"] = group.name
    else:
        option_group_names["optionGroupName1"] = product.option_group_name

    # 5. 업데이트 데이터 구성
    detail_attr = origin.get("detailAttribute", {})
    detail_attr["optionInfo"] = {
        "optionCombinationSortType": "CREATE",
        "optionCombinationGroupNames": option_group_names,
        "optionCombinations": option_combinations,
        "useStockManagement": True
    }

    leaf_category_id = origin.get("leafCategoryId")

    update_data = {
        "originProduct": {
            "statusType": origin.get("statusType", "SALE"),
            "saleType": origin.get("saleType", "NEW"),
            "leafCategoryId": str(leaf_category_id) if leaf_category_id else None,
            "name": origin.get("name"),
            "detailContent": origin.get("detailContent", ""),
            "salePrice": origin.get("salePrice"),
            "stockQuantity": total_stock,
            "images": origin.get("images", {}),
            "deliveryInfo": origin.get("deliveryInfo", {}),
            "detailAttribute": detail_attr
        }
    }

    if not leaf_category_id:
        del update_data["originProduct"]["leafCategoryId"]

    # 6. PUT 요청
    response = requests.put(
        f"{naver_api.BASE_URL}/external/v2/products/origin-products/{origin_product_no}",
        headers=headers,
        json=update_data,
        timeout=60
    )

    if response.status_code in [200, 204]:
        print(f"  옵션 업데이트 성공! (총 재고: {total_stock}, 품절: {soldout_count}개)")
        return True
    else:
        print(f"  옵션 업데이트 실패: {response.status_code}")
        print(f"  {response.text[:300]}")
        return False


# 테스트
if __name__ == "__main__":
    print("=" * 60)
    print("도매꾹 → 네이버 상품 등록 테스트")
    print("=" * 60)

    # 테스트 상품: 꽈배기 비니
    item_no = "42119521"

    print(f"\n[1] 도매꾹 상품 조회: {item_no}")
    product = get_domeggook_product(item_no)

    if product:
        print(f"  상품명: {product.name}")
        print(f"  가격: {product.price:,}원")
        print(f"  최소주문수량: {product.min_quantity}개")
        print(f"  배송비: {product.delivery_fee:,}원")
        print(f"  대표이미지: {'있음' if product.image_url else '없음'}")
        print(f"  상세이미지: {len(product.detail_images)}개")
        print(f"  옵션: {len(product.options)}개 ({product.option_group_name})")

        # 옵션 상세
        if product.options:
            print(f"\n  옵션 목록:")
            for opt in product.options:
                status = "품절" if opt.is_soldout else f"재고 {opt.stock}"
                print(f"    - {opt.value}: {status}")

        # 등록 테스트 (실제 등록하려면 주석 해제)
        # print(f"\n[2] 네이버 등록")
        # channel_no, origin_no, price = register_to_naver(
        #     product,
        #     category_id="50000803",  # 모자
        #     display=False
        # )
    else:
        print("  상품 조회 실패")
