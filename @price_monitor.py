# -*- coding: utf-8 -*-
"""
가격 모니터링 스크립트
=====================
등록된 상품의 도매꾹 가격을 모니터링하고,
마진율에 맞게 네이버 가격을 자동 조정합니다.

사용법: python price_monitor.py
  - 최초 실행 후 1시간 간격으로 반복
  - Ctrl+C로 종료
"""

import sys
import io
import os
import json
import math
import time
import requests
from datetime import datetime
from typing import Optional, List, Dict, Tuple
from dotenv import load_dotenv

load_dotenv(override=True)

# Windows 콘솔 인코딩 설정
if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, 'buffer') and not isinstance(sys.stdout, io.TextIOWrapper):
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    except:
        pass

try:
    from google_sheets import GoogleSheetsManager
    from naver_commerce import NaverCommerceAPI
except ImportError as e:
    print(f"[ERROR] 필수 모듈을 찾을 수 없습니다: {e}")
    sys.exit(1)

# 도매꾹 API 키
DOMEGGOOK_API_KEY = os.getenv("DOMEGGOOK_API_KEY")

# 모니터링 설정
CHECK_INTERVAL_HOURS = 1  # 확인 주기 (시간)
PRICE_DIFF_THRESHOLD = 5  # 가격 차이 임계값 (%)
DEFAULT_MARGIN_RATE = 0.30  # 기본 마진율 30%

# 배송비 설정
DEFAULT_DELIVERY_FEE = 3000  # 기본 배송비
FREE_SHIPPING_THRESHOLD = 50000  # 이 금액 이상이면 무료배송으로 등록된 경우가 많음
INCLUDE_DELIVERY_IN_PRICE = True  # 배송비를 판매가에 포함할지 여부

# 구글 시트 설정
SHEET_NAME = "registered_products"

# 컬럼 인덱스 (0-based)
COL_DOMEGGOOK_NO = 1       # B열: 도매꾹번호
COL_NAVER_CHANNEL_NO = 2   # C열: 네이버채널번호
COL_PRODUCT_NAME = 4       # E열: 상품명
COL_DOMEGGOOK_PRICE = 5    # F열: 도매가
COL_NAVER_PRICE = 6        # G열: 판매가
COL_MARGIN = 7             # H열: 마진
COL_DISPLAY_STATUS = 10    # K열: 전시상태
COL_MARGIN_RATE = 13       # N열: 마진율(%)
COL_DELIVERY_FEE = 15      # P열: 배송비 (신규 추가)
COL_OPTION_COUNT = 16      # Q열: 판매중 옵션 수
COL_OPTION_RANGE = 17      # R열: 옵션 가격 범위 (예: 14,600~23,200원)


def get_domeggook_price(item_no: str) -> int:
    """
    도매꾹 상품 가격 조회 (OpenAPI v4.5 getItemView 사용)

    Args:
        item_no: 도매꾹 상품번호

    Returns:
        상품 가격 (원), 실패시 0
    """
    result = get_domeggook_price_and_delivery(item_no)
    return result.get("price", 0)


def get_domeggook_price_and_delivery(item_no: str) -> Dict:
    """
    도매꾹 상품 가격 및 배송비 조회 (OpenAPI v4.5 getItemView 사용)

    Args:
        item_no: 도매꾹 상품번호

    Returns:
        {"price": 상품가격, "delivery_fee": 배송비, "delivery_type": 배송유형}
        실패시 {"price": 0, "delivery_fee": 0, "delivery_type": "unknown"}
    """
    default_result = {"price": 0, "delivery_fee": 0, "delivery_type": "unknown"}

    try:
        if not DOMEGGOOK_API_KEY:
            print("  [WARN] DOMEGGOOK_API_KEY가 설정되지 않았습니다")
            return default_result

        # 도매꾹 OpenAPI v4.5 - 상품 상세 조회
        url = "https://domeggook.com/ssl/api/"
        params = {
            "ver": "4.5",
            "mode": "getItemView",
            "aid": DOMEGGOOK_API_KEY,
            "om": "json",
            "no": item_no
        }

        response = requests.get(url, params=params, timeout=15)

        if response.status_code != 200:
            print(f"  [WARN] 도매꾹 API 호출 실패: {response.status_code}")
            return default_result

        data = response.json()

        # 에러 체크
        if data.get('errors'):
            error_msg = data['errors'].get('message', 'Unknown error')
            print(f"  [WARN] 도매꾹 API 오류: {error_msg}")
            return default_result

        # 상품 정보 추출
        domeggook = data.get('domeggook', {})

        # 가격 필드 확인 - price가 딕셔너리 형태일 수 있음
        price_data = domeggook.get('price') or domeggook.get('sellPrice') or 0

        # 가격이 딕셔너리인 경우 dome 가격 추출
        if isinstance(price_data, dict):
            price = price_data.get('dome') or price_data.get('supply') or 0
        else:
            price = price_data

        # 수량별 가격 형식 처리: "1+5900|50+5890" → 첫 번째(1개) 가격만 추출
        if isinstance(price, str):
            # 수량별 가격 형식인지 확인 (예: "1+5900|50+5890")
            if '|' in price or '+' in price:
                # 첫 번째 가격 항목 추출
                first_item = price.split('|')[0]  # "1+5900"
                if '+' in first_item:
                    # "수량+가격" 형식에서 가격만 추출
                    price = first_item.split('+')[1]  # "5900"
            price = int(str(price).replace(",", ""))

        # 배송비 정보 추출 (신형 deli 필드 우선, 구형 delivery 필드 호환)
        delivery_fee = 0
        delivery_type = "unknown"

        deli_info = domeggook.get('deli', {})
        if deli_info:
            # 신형: deli.dome.type / deli.dome.tbl
            dome_deli = deli_info.get('dome', {})
            deli_type_str = dome_deli.get('type', '')
            if '무료' in deli_type_str:
                delivery_fee = 0
                delivery_type = 'free'
            else:
                tbl = dome_deli.get('tbl', '')
                if tbl:
                    # "1+3000|5+4000|..." → 1개 기준 배송비 추출
                    first = tbl.split('|')[0]
                    if '+' in first:
                        try:
                            delivery_fee = int(first.split('+')[1])
                            delivery_type = 'quantity'
                        except (ValueError, IndexError):
                            delivery_fee = DEFAULT_DELIVERY_FEE
                            delivery_type = 'default'
                    else:
                        delivery_fee = DEFAULT_DELIVERY_FEE
                        delivery_type = 'default'
                else:
                    delivery_fee = DEFAULT_DELIVERY_FEE
                    delivery_type = 'default'
        else:
            # 구형: delivery 필드
            delivery_info = domeggook.get('delivery', {})
            if isinstance(delivery_info, dict):
                delivery_type = delivery_info.get('type', 'fix')
                if delivery_type == 'free':
                    delivery_fee = 0
                else:
                    fee_data = delivery_info.get('fee') or delivery_info.get('price') or 0
                    if isinstance(fee_data, dict):
                        delivery_fee = fee_data.get('basic') or fee_data.get('default') or 0
                    elif isinstance(fee_data, str):
                        if '|' in fee_data or '+' in fee_data:
                            first_item = fee_data.split('|')[0]
                            if '+' in first_item:
                                fee_data = first_item.split('+')[1]
                        delivery_fee = int(str(fee_data).replace(",", ""))
                    else:
                        delivery_fee = int(fee_data) if fee_data else 0
            if delivery_fee == 0 and delivery_type != 'free':
                if not delivery_info or delivery_info == {}:
                    delivery_fee = DEFAULT_DELIVERY_FEE
                    delivery_type = "default"

        # 옵션별 추가금액 파싱 (selectOpt)
        select_opt_raw = domeggook.get("selectOpt", "")
        options = parse_domeggook_options(select_opt_raw)

        return {
            "price": int(price),
            "delivery_fee": int(delivery_fee),
            "delivery_type": delivery_type,
            "options": options
        }

    except Exception as e:
        print(f"  [WARN] 도매꾹 가격/배송비 조회 오류 ({item_no}): {e}")
        return default_result


def parse_domeggook_options(select_opt_raw: str) -> List[Dict]:
    """
    도매꾹 selectOpt JSON 문자열에서 옵션 정보 파싱

    Returns:
        [{"name": 옵션명, "additional_price": 도매꾹 추가금, "qty": 재고, "visible": 판매중여부}]
        hid=2(완전삭제) 옵션은 제외
    """
    if not select_opt_raw:
        return []
    try:
        select_opt = json.loads(select_opt_raw)
        options = []
        for key in sorted(select_opt.get("data", {}).keys()):
            opt_data = select_opt["data"][key]
            hid = str(opt_data.get("hid", "0"))
            if hid == "2":  # 완전삭제된 옵션 제외
                continue
            name = opt_data.get("name", "")
            if not name:
                continue
            options.append({
                "name": name,
                "additional_price": int(opt_data.get("domPrice", 0) or 0),
                "qty": int(opt_data.get("qty", 0) or 0),
                "visible": hid == "0"   # 0=판매중, 1=품절숨김
            })
        return options
    except Exception as e:
        print(f"  [WARN] 도매꾹 옵션 파싱 오류: {e}")
        return []


def calculate_naver_options(
    base_cost: int,
    base_naver_price: int,
    margin_rate: float,
    domeggook_options: List[Dict]
) -> List[Dict]:
    """
    도매꾹 옵션 기반 네이버 옵션별 추가금액/재고 계산

    네이버 옵션 추가금 = margin_price(기본 도매가 + 옵션 추가금) - 네이버 기본가

    Returns:
        [{"name", "naver_additional_price", "qty", "visible"}]
    """
    result = []
    for opt in domeggook_options:
        total_cost = base_cost + opt["additional_price"]
        opt_naver_total = calculate_margin_price(total_cost, margin_rate)
        naver_additional = opt_naver_total - base_naver_price
        result.append({
            "name": opt["name"],
            "naver_additional_price": naver_additional,
            "qty": opt["qty"],
            "visible": opt["visible"]
        })
    return result


def calculate_margin_price(cost_price: int, margin_rate: float = 0.30) -> int:
    """
    마진을 적용한 판매가 계산 (100원 단위 올림)

    배송비는 마진율 계산에 포함하지 않음!
    - 판매가 = 도매가 / (1 - 마진율)
    - 마진 = 판매가 - 도매가
    - 배송비 정책은 마진과 배송비를 비교하여 별도로 결정

    Args:
        cost_price: 원가 (도매꾹 가격)
        margin_rate: 마진율 (기본 30%)

    Returns:
        판매가 (100원 단위 올림)
    """
    # 판매가 = 도매가 / (1 - 마진율)
    sale_price = cost_price / (1 - margin_rate)

    # 100원 단위 올림
    return int(math.ceil(sale_price / 100) * 100)


def calculate_margin_price_with_info(cost_price: int, margin_rate: float = 0.30, delivery_fee: int = 0) -> Tuple[int, int, bool]:
    """
    마진을 적용한 판매가 계산 (상세 정보 반환)

    배송비는 마진율 계산에 포함하지 않음!
    - 판매가 = 도매가 / (1 - 마진율)
    - 마진 = 판매가 - 도매가
    - 마진 >= 배송비면 무료배송, 아니면 유료배송

    Args:
        cost_price: 원가 (도매꾹 가격)
        margin_rate: 마진율 (기본 30%)
        delivery_fee: 배송비 (기본 0)

    Returns:
        (판매가, 마진, 무료배송여부)
    """
    sale_price = calculate_margin_price(cost_price, margin_rate)
    margin = sale_price - cost_price

    # 배송비 정책: 마진 >= 배송비면 무료배송
    if delivery_fee == 0:
        is_free_shipping = True
    elif margin >= delivery_fee:
        is_free_shipping = True
    else:
        is_free_shipping = False

    return sale_price, margin, is_free_shipping


def calculate_optimal_pricing(cost_price: int, margin_rate: float, delivery_fee: int) -> Dict:
    """
    마진과 배송비를 고려한 최적 가격 및 배송비 정책 계산

    로직:
    - 판매가 = 도매가 / (1 - 마진율)  (배송비는 마진율 계산에 포함하지 않음!)
    - 마진 = 판매가 - 도매가
    - 마진 >= 배송비: 무료배송으로 판매 (배송비는 마진에서 부담)
    - 마진 < 배송비: 유료배송으로 판매 (고객이 배송비 부담)

    Args:
        cost_price: 원가 (도매꾹 가격)
        margin_rate: 마진율
        delivery_fee: 도매꾹 배송비

    Returns:
        {
            "sale_price": 판매가,
            "margin": 순수 마진 (배송비 차감 전),
            "net_margin": 실제 순이익 (배송비 차감 후),
            "free_shipping": 무료배송 여부,
            "naver_delivery_fee": 네이버에 설정할 배송비 (유료배송 시),
            "policy_reason": 정책 결정 이유
        }
    """
    # 판매가 계산 (배송비 미포함)
    sale_price = calculate_margin_price(cost_price, margin_rate)
    margin = sale_price - cost_price

    # 도매꾹이 무료배송인 경우
    if delivery_fee == 0:
        return {
            "sale_price": sale_price,
            "margin": margin,
            "net_margin": margin,
            "free_shipping": True,
            "naver_delivery_fee": 0,
            "policy_reason": "도매꾹 무료배송"
        }

    # 마진 >= 배송비: 무료배송 가능 (배송비는 마진에서 부담)
    if margin >= delivery_fee:
        net_margin = margin - delivery_fee
        return {
            "sale_price": sale_price,
            "margin": margin,
            "net_margin": net_margin,
            "free_shipping": True,
            "naver_delivery_fee": 0,
            "policy_reason": f"마진({margin:,})>=배송비({delivery_fee:,})"
        }

    # 마진 < 배송비: 유료배송으로 전환 (고객이 배송비 부담)
    return {
        "sale_price": sale_price,
        "margin": margin,
        "net_margin": margin,
        "free_shipping": False,
        "naver_delivery_fee": delivery_fee,
        "policy_reason": f"마진({margin:,})<배송비({delivery_fee:,})"
    }


def get_registered_products(sheets: GoogleSheetsManager) -> List[Dict]:
    """
    구글 시트에서 등록된 상품 목록 조회

    Returns:
        상품 정보 리스트 [{row_num, domeggook_no, naver_channel_no, name,
                         domeggook_price, naver_price, margin_rate, display_status}, ...]
    """
    try:
        sheet_id = os.getenv("GOOGLE_SHEET_ID")
        if not sheet_id:
            print("[ERROR] GOOGLE_SHEET_ID 환경변수가 설정되지 않았습니다")
            return []

        # 데이터 조회 (A~N열, 2행부터)
        data = sheets.get_sheet_data(sheet_id, f"{SHEET_NAME}!A2:N")

        products = []
        for idx, row in enumerate(data, start=2):
            if len(row) < 7:  # 최소 G열까지 데이터 필요
                continue

            domeggook_no = row[COL_DOMEGGOOK_NO] if len(row) > COL_DOMEGGOOK_NO else ""
            naver_channel_no = row[COL_NAVER_CHANNEL_NO] if len(row) > COL_NAVER_CHANNEL_NO else ""
            name = row[COL_PRODUCT_NAME] if len(row) > COL_PRODUCT_NAME else ""

            # 가격 파싱
            try:
                domeggook_price = int(str(row[COL_DOMEGGOOK_PRICE]).replace(",", "")) if len(row) > COL_DOMEGGOOK_PRICE else 0
            except:
                domeggook_price = 0

            try:
                naver_price = int(str(row[COL_NAVER_PRICE]).replace(",", "")) if len(row) > COL_NAVER_PRICE else 0
            except:
                naver_price = 0

            # 마진율 파싱 (N열)
            try:
                margin_rate_str = row[COL_MARGIN_RATE] if len(row) > COL_MARGIN_RATE else ""
                if margin_rate_str:
                    margin_rate = float(str(margin_rate_str).replace("%", "")) / 100
                else:
                    margin_rate = DEFAULT_MARGIN_RATE
            except:
                margin_rate = DEFAULT_MARGIN_RATE

            # 전시상태 (K열)
            display_status = row[COL_DISPLAY_STATUS] if len(row) > COL_DISPLAY_STATUS else ""

            if domeggook_no and naver_channel_no:
                products.append({
                    "row_num": idx,
                    "domeggook_no": str(domeggook_no),
                    "naver_channel_no": str(naver_channel_no),
                    "name": name,
                    "domeggook_price": domeggook_price,
                    "naver_price": naver_price,
                    "margin_rate": margin_rate,
                    "display_status": display_status
                })

        return products

    except Exception as e:
        print(f"[ERROR] 등록 상품 조회 실패: {e}")
        import traceback
        traceback.print_exc()
        return []


def update_sheet_prices(
    sheets: GoogleSheetsManager,
    row_num: int,
    domeggook_price: int,
    naver_price: int,
    margin: int,
    display_status: str = "",
    naver_delivery_fee: int = 0,
    option_count: int = 0,
    option_price_range: str = ""
):
    """
    구글 시트에 가격 정보 업데이트 (API 호출 최소화 및 할당량 초과 방지)

    Args:
        sheets: GoogleSheetsManager 인스턴스
        row_num: 행 번호
        domeggook_price: 도매가 (F열)
        naver_price: 판매가 (G열)
        margin: 마진 (H열) - 배송비 차감 전 순수 마진
        display_status: 전시상태 (K열)
        naver_delivery_fee: 네이버 배송비 (P열) - 무료배송이면 0, 유료배송이면 실제 배송비
        option_count: 판매중 옵션 수 (Q열) - 옵션 상품만
        option_price_range: 옵션 가격 범위 (R열) - 예: "14,600~23,200원"
    """
    try:
        sheet_id = os.getenv("GOOGLE_SHEET_ID")
        if not sheet_id:
            return

        # batchUpdate를 사용하여 여러 범위를 한 번에 업데이트
        batch_data = [
            # F~H열 (도매가, 판매가, 마진)
            {
                "range": f"{SHEET_NAME}!F{row_num}:H{row_num}",
                "values": [[domeggook_price, naver_price, margin]]
            },
            # P열 (네이버 배송비 - 무료배송이면 0)
            {
                "range": f"{SHEET_NAME}!P{row_num}",
                "values": [[naver_delivery_fee]]
            }
        ]

        # 전시상태가 있으면 K열도 추가
        if display_status:
            batch_data.append({
                "range": f"{SHEET_NAME}!K{row_num}",
                "values": [[display_status]]
            })

        # 옵션 정보가 있으면 Q~R열 추가
        if option_count > 0 or option_price_range:
            batch_data.append({
                "range": f"{SHEET_NAME}!Q{row_num}:R{row_num}",
                "values": [[option_count, option_price_range]]
            })

        # batchUpdate 호출 (단일 API 호출로 처리)
        sheets.batch_update_sheet_data(sheet_id, batch_data)

        # API 할당량 초과 방지를 위한 딜레이 (60 writes/min = 최소 1초 간격)
        time.sleep(1.2)

    except Exception as e:
        print(f"  [WARN] 시트 업데이트 실패 (행 {row_num}): {e}")


def check_and_update_prices():
    """
    가격 확인 및 업데이트 실행
    """
    print("\n" + "=" * 60)
    print(f"[가격 모니터링] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    try:
        sheets = GoogleSheetsManager()
        naver_api = NaverCommerceAPI()

        # 등록 상품 조회
        products = get_registered_products(sheets)
        if not products:
            print("  등록된 상품이 없습니다.")
            return

        print(f"  등록 상품 {len(products)}개 확인 중...")
        print("-" * 60)

        updated_count = 0
        display_updated_count = 0
        error_count = 0

        for product in products:
            try:
                domeggook_no = product["domeggook_no"]
                naver_channel_no = product["naver_channel_no"]
                name = product["name"][:30]
                stored_domeggook_price = product["domeggook_price"]
                stored_naver_price = product["naver_price"]
                margin_rate = product["margin_rate"]
                row_num = product["row_num"]

                print(f"\n[{domeggook_no}] {name}")

                # 1. 도매꾹 현재 가격 및 배송비 조회
                domeggook_info = get_domeggook_price_and_delivery(domeggook_no)
                current_domeggook_price = domeggook_info.get("price", 0)
                delivery_fee = domeggook_info.get("delivery_fee", 0)
                delivery_type = domeggook_info.get("delivery_type", "unknown")
                domeggook_options = domeggook_info.get("options", [])

                if current_domeggook_price == 0:
                    print(f"  도매꾹 가격 조회 실패")
                    error_count += 1
                    continue

                # 2. 네이버 현재 가격 및 전시상태 조회
                product_info = naver_api.get_product_info(naver_channel_no)
                if product_info is None:
                    print(f"  네이버 상품정보 조회 실패")
                    error_count += 1
                    continue

                current_naver_price = product_info.get("price", 0)
                display_status = product_info.get("display_status", "")
                display_label = {
                    "ON": "전시중",
                    "OFF": "전시안함",
                    "SUSPENSION": "판매중지"
                }.get(display_status, display_status)

                # 3. 최적 가격 및 배송비 정책 계산 (마진과 배송비 비교)
                pricing = calculate_optimal_pricing(
                    current_domeggook_price, margin_rate, delivery_fee
                )
                target_price = pricing["sale_price"]
                margin = pricing["margin"]
                is_free_shipping = pricing["free_shipping"]
                naver_delivery_fee = pricing["naver_delivery_fee"]
                policy_reason = pricing["policy_reason"]

                # 4. 가격 차이 확인
                price_diff = abs(current_naver_price - target_price)
                diff_percent = (price_diff / target_price) * 100 if target_price > 0 else 0

                # 도매꾹 가격 변동 확인
                domeggook_changed = stored_domeggook_price != current_domeggook_price
                domeggook_change_text = ""
                if domeggook_changed:
                    domeggook_change_text = f" (변동: {stored_domeggook_price:,}→{current_domeggook_price:,})"

                # 배송비 정보 텍스트
                if delivery_type == 'free':
                    delivery_text = "무료배송"
                elif delivery_fee > 0:
                    delivery_text = f"배송비 {delivery_fee:,}원"
                else:
                    delivery_text = "배송비 미확인"

                # 네이버 배송비 정책 텍스트
                naver_shipping_text = "무료배송" if is_free_shipping else f"유료배송({naver_delivery_fee:,}원)"

                # 옵션별 네이버 가격 계산 (옵션 상품인 경우)
                naver_options = []
                if domeggook_options:
                    naver_options = calculate_naver_options(
                        current_domeggook_price, target_price, margin_rate, domeggook_options
                    )

                print(f"  도매꾹: {current_domeggook_price:,}원{domeggook_change_text} | {delivery_text}")
                print(f"  네이버: {current_naver_price:,}원 | 적정가: {target_price:,}원 (마진 {margin:,}원, {naver_shipping_text})")
                print(f"  전시상태: {display_label} | 정책: {policy_reason}")

                # 옵션 요약 출력
                if naver_options:
                    active = [(o, d) for o, d in zip(naver_options, domeggook_options) if d["visible"] and d["qty"] > 0]
                    inactive = [(o, d) for o, d in zip(naver_options, domeggook_options) if not (d["visible"] and d["qty"] > 0)]
                    for opt, dom in active[:5]:
                        print(f"    [판매중] {opt['name']}: +{opt['naver_additional_price']:,}원 (재고:{dom['qty']})")
                    if len(active) > 5:
                        print(f"    ... 외 {len(active) - 5}개")
                    for opt, dom in inactive:
                        status = "품절" if dom["visible"] else "숨김"
                        print(f"    [{status}] {opt['name']}")

                # 5. 시트 업데이트 (항상 최신 정보로 업데이트)
                # 옵션 요약 계산 (Q·R열용)
                option_count = 0
                option_price_range = ""
                if naver_options:
                    active_totals = [
                        target_price + opt["naver_additional_price"]
                        for opt, dom in zip(naver_options, domeggook_options)
                        if dom["visible"] and dom["qty"] > 0
                    ]
                    option_count = len(active_totals)
                    if active_totals:
                        min_p, max_p = min(active_totals), max(active_totals)
                        option_price_range = (
                            f"{min_p:,}원" if min_p == max_p
                            else f"{min_p:,}~{max_p:,}원"
                        )
                    else:
                        option_price_range = "전품절"

                update_sheet_prices(
                    sheets, row_num,
                    current_domeggook_price, target_price, margin,
                    display_label, naver_delivery_fee,
                    option_count, option_price_range
                )
                if product["display_status"] != display_label:
                    display_updated_count += 1

                # 6. 네이버 업데이트
                if naver_options:
                    # 옵션 상품: 옵션별 가격+재고 동기화 (임계값 무관, 변동 있을 때만 PUT)
                    opt_success, opt_changed = naver_api.update_product_with_options(
                        naver_channel_no,
                        target_price,
                        is_free_shipping,
                        naver_delivery_fee,
                        naver_options
                    )
                    if opt_changed:
                        updated_count += 1
                        print(f"  [완료] 옵션 가격/재고 동기화")
                    elif opt_success:
                        print(f"  [정상] 옵션 변동 없음")
                    else:
                        print(f"  [실패] 옵션 동기화 실패")
                        error_count += 1
                else:
                    # 단일 상품: 5% 임계값 초과 시 가격+배송비 수정
                    if diff_percent >= PRICE_DIFF_THRESHOLD:
                        print(f"  [조정필요] 가격 차이 {diff_percent:.1f}% ({current_naver_price:,}→{target_price:,}원)")
                        success = naver_api.update_product_price_and_delivery(
                            naver_channel_no,
                            target_price,
                            is_free_shipping,
                            naver_delivery_fee
                        )
                        if success:
                            updated_count += 1
                            print(f"  [완료] 가격/배송비 수정 성공")
                            update_sheet_prices(
                                sheets, row_num,
                                current_domeggook_price, target_price, margin,
                                display_label, naver_delivery_fee
                            )
                        else:
                            print(f"  [실패] 가격/배송비 수정 실패")
                            error_count += 1
                    else:
                        print(f"  [정상] 가격 차이 {diff_percent:.1f}%")

                # API 호출 간격 (429 에러 방지)
                time.sleep(1.5)

            except Exception as e:
                print(f"  [ERROR] 처리 오류: {e}")
                error_count += 1

        # 결과 요약
        print("\n" + "=" * 60)
        print(f"[완료] 가격수정: {updated_count}건 | 전시상태 업데이트: {display_updated_count}건 | 오류: {error_count}건")
        print("=" * 60)

    except Exception as e:
        print(f"[ERROR] 가격 모니터링 실패: {e}")
        import traceback
        traceback.print_exc()


def run_monitor():
    """
    가격 모니터링 반복 실행 (1시간 간격)
    """
    print("=" * 60)
    print("가격 모니터링 시작")
    print("=" * 60)
    print(f"  - 확인 주기: {CHECK_INTERVAL_HOURS}시간")
    print(f"  - 가격 조정 임계값: {PRICE_DIFF_THRESHOLD}% 이상 차이시")
    print(f"  - 기본 마진율: {DEFAULT_MARGIN_RATE * 100:.0f}%")
    print("  - 종료: Ctrl+C")
    print("=" * 60)

    # 최초 실행
    check_and_update_prices()

    # 반복 실행
    while True:
        try:
            next_check = datetime.now().strftime("%H:%M")
            print(f"\n[대기] 다음 확인: {CHECK_INTERVAL_HOURS}시간 후 ({next_check})")

            # 1시간 대기
            time.sleep(CHECK_INTERVAL_HOURS * 3600)

            # 가격 확인
            check_and_update_prices()

        except KeyboardInterrupt:
            print("\n\n모니터링 종료")
            break
        except Exception as e:
            print(f"\n[ERROR] 모니터링 오류: {e}")
            import traceback
            traceback.print_exc()
            # 오류 발생 시 5분 후 재시도
            time.sleep(300)


def run_once():
    """
    단일 실행 (한 번만 확인)
    """
    check_and_update_prices()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="가격 모니터링 스크립트")
    parser.add_argument("--once", action="store_true", help="한 번만 실행 (반복 없음)")
    args = parser.parse_args()

    if args.once:
        run_once()
    else:
        run_monitor()
