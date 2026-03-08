# -*- coding: utf-8 -*-
"""
도매꾹 → 네이버 스마트스토어 자동 상품 등록
============================================
도매꾹에서 이미지허용상품을 조회하여
30% 마진을 적용해 네이버 스마트스토어에 자동 등록합니다.
등록 이력은 구글시트에 저장됩니다.
"""

import sys
import io
import os
import argparse
from datetime import datetime
from typing import List, Dict

from domeggook_image import DomeggookImageAPI, ImageAllowedProduct
from naver_commerce import NaverCommerceAPI

# 구글시트 저장 여부 (환경변수로 설정 가능)
SAVE_TO_SHEETS = os.getenv("SAVE_TO_SHEETS", "true").lower() == "true"

# Windows 콘솔 인코딩 설정
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')


def auto_register(
    keyword: str = "",
    max_products: int = 10,
    category_id: str = None,
    dry_run: bool = False
) -> Dict:
    """
    도매꾹 이미지허용상품을 네이버에 자동 등록

    Args:
        keyword: 검색 키워드
        max_products: 최대 등록 상품 수
        category_id: 네이버 카테고리 ID (없으면 자동 매칭)
        dry_run: True면 실제 등록하지 않고 시뮬레이션만

    Returns:
        등록 결과 딕셔너리
    """
    result = {
        "total": 0,
        "success": 0,
        "failed": 0,
        "products": []
    }

    print("=" * 60)
    print("도매꾹 → 네이버 스마트스토어 자동 상품 등록")
    print("=" * 60)
    print(f"  검색 키워드: {keyword or '전체'}")
    print(f"  최대 상품 수: {max_products}")
    print(f"  마진율: 30%")
    if dry_run:
        print("  [DRY RUN 모드 - 실제 등록하지 않음]")
    print()

    # 1. 도매꾹 API 초기화
    print("[1/3] 도매꾹 API 연결...")
    try:
        domeggook = DomeggookImageAPI()
    except Exception as e:
        print(f"  [ERROR] 도매꾹 API 초기화 실패: {e}")
        return result

    # 2. 이미지허용상품 조회
    print("\n[2/3] 이미지허용상품 조회 중...")
    products = domeggook.get_image_allowed_products(
        keyword=keyword,
        max_products=max_products * 2,  # 이미지 불허 상품 제외 고려
        check_each=True
    )

    if not products:
        print("  이미지허용상품이 없습니다.")
        return result

    # 최대 상품 수 제한
    products = products[:max_products]
    result["total"] = len(products)
    print(f"\n  → 등록 대상 상품: {len(products)}개")

    # 3. 네이버 API 초기화
    print("\n[3/3] 네이버 스마트스토어 등록 시작...")
    try:
        naver = NaverCommerceAPI()
        token = naver.get_access_token()
        if not token:
            print("  [ERROR] 네이버 API 인증 실패")
            return result
    except Exception as e:
        print(f"  [ERROR] 네이버 API 초기화 실패: {e}")
        return result

    # 채널 정보 확인
    channel_info = naver.get_channel_info()
    if channel_info:
        channel = channel_info[0] if isinstance(channel_info, list) else channel_info
        print(f"  스토어: {channel.get('name', 'Unknown')}")
        print(f"  URL: {channel.get('url', '')}")
    print()

    # 4. 상품 등록
    for i, product in enumerate(products, 1):
        print(f"\n[{i}/{len(products)}] {product.name[:40]}...")
        print(f"  도매가: {product.price:,}원 → 판매가(30%↑): {product.margin_price:,}원")
        print(f"  이미지: {'있음' if product.image_url else '없음'}")

        product_result = {
            "item_no": product.item_no,
            "name": product.name,
            "domeggook_price": product.price,
            "naver_price": product.margin_price,
            "status": "pending",
            "naver_product_id": None
        }

        if dry_run:
            print(f"  [DRY RUN] 등록 스킵")
            product_result["status"] = "dry_run"
        else:
            # 실제 등록
            product_id = naver.register_product_from_domeggook(
                product=product,
                category_id=category_id
            )

            if product_id:
                product_result["status"] = "success"
                product_result["naver_product_id"] = product_id
                result["success"] += 1
                print(f"  ✓ 등록 성공: {product_id}")
            else:
                product_result["status"] = "failed"
                result["failed"] += 1
                print(f"  ✗ 등록 실패")

        result["products"].append(product_result)

    # 5. 구글시트에 등록 이력 저장
    if SAVE_TO_SHEETS and not dry_run and result["success"] > 0:
        save_to_google_sheets(result["products"], products)

    # 결과 요약
    print("\n" + "=" * 60)
    print("등록 결과 요약")
    print("=" * 60)
    print(f"  총 대상: {result['total']}개")
    print(f"  성공: {result['success']}개")
    print(f"  실패: {result['failed']}개")

    return result


def save_to_google_sheets(registered_products: List[Dict], source_products: List[ImageAllowedProduct]):
    """
    등록 이력을 구글시트에 저장

    저장 항목:
    - 등록일시
    - 도매꾹 상품명
    - 도매꾹 상품링크
    - 네이버 등록 상품번호
    - 도매꾹 원가
    - 등록 판매가
    - 도매꾹 배송비
    - 네이버 배송비
    """
    try:
        from google_sheets import GoogleSheetsManager

        sheets = GoogleSheetsManager()
        sheet_name = "auto_register_history"

        # 시트 초기화 (헤더 설정)
        init_auto_register_sheet(sheets, sheet_name)

        # 등록 성공한 상품만 저장
        rows = []
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # source_products를 item_no 기준으로 매핑
        product_map = {p.item_no: p for p in source_products}

        for reg in registered_products:
            if reg.get("status") != "success":
                continue

            item_no = reg.get("item_no", "")
            source = product_map.get(item_no)
            if not source:
                continue

            # 도매꾹 링크 하이퍼링크
            domeggook_link = f'=HYPERLINK("{source.link}", "{item_no}")'

            # 옵션 정보 문자열로 변환
            option_str = source.get_option_string() if hasattr(source, 'get_option_string') else source.option_info

            row = [
                created_at,                          # 등록일시
                source.name,                         # 도매꾹 상품명
                domeggook_link,                      # 도매꾹 상품링크
                str(reg.get("naver_product_id", "")),  # 네이버 등록 상품번호
                source.price,                        # 도매꾹 원가
                reg.get("naver_price", 0),           # 등록 판매가
                source.delivery_fee,                 # 도매꾹 배송비
                0,                                   # 네이버 배송비 (무료배송)
                option_str                           # 도매꾹 옵션
            ]
            rows.append(row)

        if rows:
            # 시트에 추가
            sheets.sheets_service.spreadsheets().values().append(
                spreadsheetId=sheets.sheet_id,
                range=f"{sheet_name}!A:I",
                valueInputOption="USER_ENTERED",
                body={"values": rows}
            ).execute()
            print(f"\n[Sheets] 등록 이력 {len(rows)}건 저장 완료")

    except Exception as e:
        print(f"\n[WARN] 구글시트 저장 실패: {e}")


def init_auto_register_sheet(sheets, sheet_name: str):
    """자동등록 이력 시트 초기화"""
    headers = [
        "등록일시", "도매꾹상품명", "도매꾹링크", "네이버상품번호",
        "도매꾹원가", "등록판매가", "도매꾹배송비", "네이버배송비", "도매꾹옵션"
    ]

    try:
        # 스프레드시트 정보 가져오기
        spreadsheet = sheets.sheets_service.spreadsheets().get(
            spreadsheetId=sheets.sheet_id
        ).execute()

        # 시트가 이미 있는지 확인
        sheet_exists = False
        target_sheet_id = None
        for sheet in spreadsheet.get("sheets", []):
            if sheet["properties"]["title"] == sheet_name:
                sheet_exists = True
                target_sheet_id = sheet["properties"]["sheetId"]
                break

        # 시트가 없으면 새로 생성
        if not sheet_exists:
            request_body = {
                "requests": [{
                    "addSheet": {
                        "properties": {"title": sheet_name}
                    }
                }]
            }
            result = sheets.sheets_service.spreadsheets().batchUpdate(
                spreadsheetId=sheets.sheet_id,
                body=request_body
            ).execute()
            target_sheet_id = result['replies'][0]['addSheet']['properties']['sheetId']

            # 헤더 추가
            sheets.sheets_service.spreadsheets().values().update(
                spreadsheetId=sheets.sheet_id,
                range=f"{sheet_name}!A1:I1",
                valueInputOption="RAW",
                body={"values": [headers]}
            ).execute()

            # 헤더 스타일 적용
            requests = [
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": target_sheet_id,
                            "startRowIndex": 0,
                            "endRowIndex": 1,
                            "startColumnIndex": 0,
                            "endColumnIndex": 9
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "backgroundColor": {"red": 0.2, "green": 0.6, "blue": 0.3},
                                "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}}
                            }
                        },
                        "fields": "userEnteredFormat(backgroundColor, textFormat)"
                    }
                },
                {
                    "updateSheetProperties": {
                        "properties": {"sheetId": target_sheet_id, "gridProperties": {"frozenRowCount": 1}},
                        "fields": "gridProperties.frozenRowCount"
                    }
                }
            ]
            sheets.sheets_service.spreadsheets().batchUpdate(
                spreadsheetId=sheets.sheet_id,
                body={"requests": requests}
            ).execute()

            print(f"[Sheets] 새 시트 생성: {sheet_name}")

    except Exception as e:
        print(f"[WARN] 시트 초기화 실패: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="도매꾹 이미지허용상품을 네이버 스마트스토어에 자동 등록"
    )
    parser.add_argument(
        "-k", "--keyword",
        type=str,
        default="",
        help="검색 키워드 (예: 무선이어폰)"
    )
    parser.add_argument(
        "-n", "--max-products",
        type=int,
        default=5,
        help="최대 등록 상품 수 (기본: 5)"
    )
    parser.add_argument(
        "-c", "--category",
        type=str,
        default=None,
        help="네이버 카테고리 ID (없으면 자동 매칭)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="실제 등록하지 않고 시뮬레이션만 수행"
    )

    args = parser.parse_args()

    result = auto_register(
        keyword=args.keyword,
        max_products=args.max_products,
        category_id=args.category,
        dry_run=args.dry_run
    )

    return 0 if result["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
