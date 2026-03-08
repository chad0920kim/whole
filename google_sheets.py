# -*- coding: utf-8 -*-
"""
Google Sheets 연동 모듈
========================
수집한 상품 데이터를 Google Sheets에 저장하고 관리합니다.
"""

import os
import json
from datetime import datetime
from pathlib import Path
from typing import Optional, List
from dotenv import load_dotenv

load_dotenv(override=True)


class GoogleSheetsManager:
    """Google Sheets 관리 클래스"""

    SCOPES = [
        'https://www.googleapis.com/auth/drive',
        'https://www.googleapis.com/auth/spreadsheets'
    ]

    def __init__(
        self,
        credentials_file: str = None,
        sheet_id: str = None,
        use_oauth: bool = True
    ):
        """
        Args:
            credentials_file: OAuth 클라이언트 JSON 또는 서비스 계정 JSON 경로
            sheet_id: Google Sheets 스프레드시트 ID
            use_oauth: True면 OAuth 사용 (개인 계정), False면 서비스 계정
        """
        self.credentials_file = credentials_file or os.getenv("GOOGLE_CREDENTIALS_FILE")
        self.sheet_id = sheet_id or os.getenv("GOOGLE_SHEET_ID")
        self.use_oauth = use_oauth

        self._credentials = None
        self._sheets_service = None

        # 토큰 파일 경로
        self.token_file = Path(self.credentials_file).parent / "token.json" if self.credentials_file else "token.json"

        # 시트 헤더 정의 - 네이버링크/도매꾹링크 붙여서 배치
        self.sheet_headers = [
            "확인일시", "카테고리", "검색키워드",
            "네이버상품명", "네이버브랜드", "네이버가격",
            "도매꾹상품명", "도매꾹브랜드", "도매꾹가격",
            "네이버링크", "도매꾹링크",
            "AI비교", "마진금액", "마진율(%)"
        ]

        # 시트 초기화 여부 추적
        self._sheet_initialized = {}

    @property
    def credentials(self):
        """인증 정보 (지연 로딩)"""
        if self._credentials is None:
            # 환경변수에 서비스 계정 JSON이 있으면 우선 사용 (CI/CD 환경)
            service_account_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
            if service_account_json:
                from google.oauth2 import service_account
                info = json.loads(service_account_json)
                self._credentials = service_account.Credentials.from_service_account_info(
                    info, scopes=self.SCOPES
                )
            elif self.use_oauth:
                self._credentials = self._get_oauth_credentials()
            else:
                if not self.credentials_file:
                    raise ValueError("GOOGLE_CREDENTIALS_FILE 환경변수 또는 credentials_file 필요")
                from google.oauth2 import service_account
                self._credentials = service_account.Credentials.from_service_account_file(
                    self.credentials_file,
                    scopes=self.SCOPES
                )
        return self._credentials

    def _get_oauth_credentials(self):
        """OAuth 2.0 인증 (개인 계정용)"""
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request

        creds = None

        # 기존 토큰 확인
        if Path(self.token_file).exists():
            creds = Credentials.from_authorized_user_file(str(self.token_file), self.SCOPES)

        # 토큰이 없거나 만료됐으면 갱신/재발급
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    self.credentials_file, self.SCOPES
                )
                creds = flow.run_local_server(port=0)

            # 토큰 저장
            with open(self.token_file, 'w') as token:
                token.write(creds.to_json())

        return creds

    @property
    def sheets_service(self):
        """Google Sheets 서비스 (지연 로딩)"""
        if self._sheets_service is None:
            from googleapiclient.discovery import build
            self._sheets_service = build('sheets', 'v4', credentials=self.credentials)
        return self._sheets_service

    def init_sheet(self, sheet_name: str = "wholesale_products", force: bool = False):
        """
        시트 초기화 (헤더 추가) - 한 번만 실행

        Args:
            sheet_name: 시트 이름
            force: True면 강제 재초기화
        """
        # 이미 초기화된 시트는 스킵 (force가 아닌 경우)
        if not force and self._sheet_initialized.get(sheet_name):
            return

        if not self.sheet_id:
            raise ValueError("GOOGLE_SHEET_ID 환경변수 필요")

        try:
            # 스프레드시트 정보 가져오기
            spreadsheet = self.sheets_service.spreadsheets().get(
                spreadsheetId=self.sheet_id
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
                            "properties": {
                                "title": sheet_name
                            }
                        }
                    }]
                }
                result = self.sheets_service.spreadsheets().batchUpdate(
                    spreadsheetId=self.sheet_id,
                    body=request_body
                ).execute()
                target_sheet_id = result['replies'][0]['addSheet']['properties']['sheetId']
                print(f"[Sheets] 새 시트 생성: {sheet_name}")

            # 헤더만 업데이트 (1행만)
            self.sheets_service.spreadsheets().values().update(
                spreadsheetId=self.sheet_id,
                range=f"{sheet_name}!A1:N1",
                valueInputOption="RAW",
                body={"values": [self.sheet_headers]}
            ).execute()

            # 헤더 스타일만 적용 (1행만, 데이터는 건드리지 않음)
            if target_sheet_id is not None:
                requests = [
                    # 1행: 헤더 스타일
                    {
                        "repeatCell": {
                            "range": {
                                "sheetId": target_sheet_id,
                                "startRowIndex": 0,
                                "endRowIndex": 1
                            },
                            "cell": {
                                "userEnteredFormat": {
                                    "backgroundColor": {"red": 0.2, "green": 0.5, "blue": 0.9},
                                    "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}}
                                }
                            },
                            "fields": "userEnteredFormat(backgroundColor, textFormat)"
                        }
                    },
                    # 1행 고정
                    {
                        "updateSheetProperties": {
                            "properties": {"sheetId": target_sheet_id, "gridProperties": {"frozenRowCount": 1}},
                            "fields": "gridProperties.frozenRowCount"
                        }
                    }
                ]

                self.sheets_service.spreadsheets().batchUpdate(
                    spreadsheetId=self.sheet_id,
                    body={"requests": requests}
                ).execute()

            # 초기화 완료 표시
            self._sheet_initialized[sheet_name] = True
            print(f"[Sheets] 시트 초기화 완료: {sheet_name}")

        except Exception as e:
            print(f"[Sheets] 시트 초기화 실패: {e}")

    def get_sheet_data(self, spreadsheet_id: str, range_name: str) -> list:
        """
        시트에서 데이터 조회

        Args:
            spreadsheet_id: 스프레드시트 ID
            range_name: 범위 (예: "시트1!A1:B10")

        Returns:
            데이터 리스트
        """
        result = self.sheets_service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=range_name
        ).execute()
        return result.get('values', [])

    def create_sheet(self, spreadsheet_id: str, sheet_name: str) -> int:
        """
        새 시트 생성

        Args:
            spreadsheet_id: 스프레드시트 ID
            sheet_name: 시트 이름

        Returns:
            생성된 시트 ID
        """
        request_body = {
            "requests": [{
                "addSheet": {
                    "properties": {
                        "title": sheet_name
                    }
                }
            }]
        }
        result = self.sheets_service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body=request_body
        ).execute()
        sheet_id = result['replies'][0]['addSheet']['properties']['sheetId']
        print(f"[Sheets] 새 시트 생성: {sheet_name}")
        return sheet_id

    def update_sheet_data(self, spreadsheet_id: str, range_name: str, values: list):
        """
        시트 데이터 업데이트

        Args:
            spreadsheet_id: 스프레드시트 ID
            range_name: 범위 (예: "시트1!A1:B10")
            values: 데이터 리스트
        """
        self.sheets_service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=range_name,
            valueInputOption="RAW",
            body={"values": values}
        ).execute()

    def append_sheet_data(self, spreadsheet_id: str, range_name: str, values: list):
        """
        시트에 데이터 추가

        Args:
            spreadsheet_id: 스프레드시트 ID
            range_name: 범위 (예: "시트1!A:O")
            values: 데이터 리스트
        """
        self.sheets_service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range=range_name,
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": values}
        ).execute()

    def batch_update_sheet_data(self, spreadsheet_id: str, data: list):
        """
        여러 범위를 한 번에 업데이트 (API 호출 최소화)

        Args:
            spreadsheet_id: 스프레드시트 ID
            data: 업데이트할 데이터 리스트
                  [{"range": "시트!A1:B2", "values": [[val1, val2], ...]}, ...]
        """
        self.sheets_service.spreadsheets().values().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={
                "valueInputOption": "RAW",
                "data": data
            }
        ).execute()

    def sheet_exists(self, spreadsheet_id: str, sheet_name: str) -> bool:
        """
        시트 존재 여부 확인

        Args:
            spreadsheet_id: 스프레드시트 ID
            sheet_name: 시트 이름

        Returns:
            존재하면 True
        """
        try:
            spreadsheet = self.sheets_service.spreadsheets().get(
                spreadsheetId=spreadsheet_id
            ).execute()
            for sheet in spreadsheet.get("sheets", []):
                if sheet["properties"]["title"] == sheet_name:
                    return True
            return False
        except Exception:
            return False

    def clear_sheet(self, sheet_name: str = "margin_products"):
        """
        시트 데이터 초기화 (헤더만 남기고 모든 데이터 삭제)
        """
        if not self.sheet_id:
            return

        try:
            # 2행부터 모든 데이터 삭제
            self.sheets_service.spreadsheets().values().clear(
                spreadsheetId=self.sheet_id,
                range=f"{sheet_name}!A2:Z10000"
            ).execute()

            print(f"[Sheets] 시트 데이터 초기화 완료: {sheet_name}")

        except Exception as e:
            print(f"[Sheets] 시트 초기화 실패: {e}")

    def get_saved_product_links(self, sheet_name: str = "margin_products") -> set:
        """
        이미 저장된 상품 링크 목록 조회 (중복 방지용)

        Returns:
            저장된 네이버/도매꾹 링크 set
        """
        if not self.sheet_id:
            return set()

        try:
            # J열(네이버링크)과 K열(도매꾹링크) 조회
            result = self.sheets_service.spreadsheets().values().get(
                spreadsheetId=self.sheet_id,
                range=f"{sheet_name}!J:K"
            ).execute()

            values = result.get('values', [])
            saved_links = set()

            for row in values[1:]:  # 헤더 스킵
                if len(row) >= 1 and row[0]:  # J열: 네이버 링크
                    saved_links.add(row[0])
                if len(row) >= 2 and row[1]:  # K열: 도매꾹 링크
                    saved_links.add(row[1])

            return saved_links

        except Exception as e:
            print(f"[Sheets] 저장된 링크 조회 실패: {e}")
            return set()

    def save_margin_products(
        self,
        keyword: str,
        category: str,
        products: list,
        domeggook_matches: dict,
        min_margin: int = 10000,
        sheet_name: str = "margin_products",
        ai_comparator=None
    ) -> int:
        """
        마진 1만원 이상 상품만 시트에 저장 (중복 제외)

        Args:
            keyword: 검색 키워드
            category: 카테고리
            products: ProductInfo 리스트
            domeggook_matches: 도매꾹 매칭 결과 {rank: {name, price, link, brand_match}}
            min_margin: 최소 마진 금액
            sheet_name: 시트 이름
            ai_comparator: AI 비교기 (옵션)

        Returns:
            저장된 상품 수
        """
        if not self.sheet_id:
            raise ValueError("GOOGLE_SHEET_ID 환경변수 필요")

        # 시트 초기화 (없으면 생성)
        try:
            self.init_sheet(sheet_name)
        except Exception as e:
            print(f"[Sheets] 시트 초기화 중 오류 (무시): {e}")

        # 이미 저장된 상품 링크 조회 (중복 방지)
        saved_links = self.get_saved_product_links(sheet_name)

        created_at = datetime.now().strftime("%Y-%m-%d %H:%M")

        rows = []
        skipped = 0
        for product in products:
            # 도매꾹 매칭 정보
            match = domeggook_matches.get(product.rank, {})
            if not match:
                continue

            domeggook_name = match.get('name', '')
            domeggook_price = match.get('price', 0)
            domeggook_link = match.get('link', '')
            domeggook_brand = match.get('brand', '')
            margin_amount = match.get('margin', 0)
            margin_rate = match.get('margin_rate', 0)

            # 마진 기준 이상만 저장
            if margin_amount < min_margin:
                continue

            # 중복 체크 (네이버 링크 또는 도매꾹 링크가 이미 있으면 스킵)
            if product.link in saved_links or domeggook_link in saved_links:
                skipped += 1
                continue

            # AI 비교 (상품명/브랜드 기반 1차 비교)
            ai_result = ""
            if ai_comparator:
                try:
                    print(f"    [AI] 상품 비교 중: {product.name[:25]}...")
                    ai_result = ai_comparator.compare_products(
                        naver_name=product.name,
                        naver_brand=product.brand or "",
                        domeggook_name=domeggook_name,
                        domeggook_brand=domeggook_brand
                    )
                    print(f"    [AI] 비교 결과: {ai_result}")
                except Exception as e:
                    print(f"    [AI] 비교 실패: {e}")
                    ai_result = "확인불가"

            # 링크를 하이퍼링크 형식으로 변환
            naver_hyperlink = f'=HYPERLINK("{product.link}", "보기")' if product.link else ""
            domeggook_hyperlink = f'=HYPERLINK("{domeggook_link}", "보기")' if domeggook_link else ""

            # 새 컬럼 순서: 확인일시, 카테고리, 검색키워드, 네이버상품명, 네이버브랜드, 네이버가격,
            #              도매꾹상품명, 도매꾹브랜드, 도매꾹가격, 네이버링크, 도매꾹링크, AI비교, 마진금액, 마진율
            row = [
                created_at,           # A: 확인일시
                category,             # B: 카테고리
                keyword,              # C: 검색키워드
                product.name,         # D: 네이버상품명
                product.brand or "",  # E: 네이버브랜드
                product.price,        # F: 네이버가격
                domeggook_name,       # G: 도매꾹상품명
                domeggook_brand,      # H: 도매꾹브랜드
                domeggook_price,      # I: 도매꾹가격
                naver_hyperlink,      # J: 네이버링크
                domeggook_hyperlink,  # K: 도매꾹링크
                ai_result,            # L: AI비교
                margin_amount,        # M: 마진금액
                round(margin_rate, 1) # N: 마진율
            ]
            rows.append(row)

        # 시트에 추가 (USER_ENTERED로 하이퍼링크 수식 적용)
        if rows:
            self.sheets_service.spreadsheets().values().append(
                spreadsheetId=self.sheet_id,
                range=f"{sheet_name}!A:N",
                valueInputOption="USER_ENTERED",
                insertDataOption="INSERT_ROWS",
                body={"values": rows}
            ).execute()

            msg = f"[Sheets] 마진 상품 {len(rows)}개 저장"
            if skipped > 0:
                msg += f" (중복 {skipped}개 제외)"
            print(msg)
        elif skipped > 0:
            print(f"[Sheets] 새 상품 없음 (중복 {skipped}개)")

        return len(rows)

    def get_saved_keywords(
        self,
        sheet_name: str = "wholesale_products",
        days_back: int = 7
    ) -> List[str]:
        """
        이전에 저장된 키워드 목록 조회 (중복 방지용)

        Args:
            sheet_name: 시트 이름
            days_back: 최근 며칠간의 데이터 조회

        Returns:
            저장된 키워드 리스트
        """
        if not self.sheet_id:
            return []

        try:
            result = self.sheets_service.spreadsheets().values().get(
                spreadsheetId=self.sheet_id,
                range=f"{sheet_name}!A:E"
            ).execute()

            values = result.get('values', [])
            keywords = set()

            from datetime import datetime, timedelta
            cutoff_date = datetime.now() - timedelta(days=days_back)

            for row in values[1:]:  # 헤더 스킵
                if len(row) >= 4:
                    try:
                        created_at_str = row[1] if len(row) > 1 else ""
                        if created_at_str:
                            created_at = datetime.strptime(created_at_str, "%Y-%m-%d %H:%M")
                            if created_at < cutoff_date:
                                continue
                    except (ValueError, IndexError):
                        pass

                    keyword = row[3] if len(row) > 3 else ""
                    if keyword:
                        keywords.add(keyword.strip().lower())

            return list(keywords)

        except Exception as e:
            print(f"[Sheets] 키워드 조회 실패: {e}")
            return []

    def update_status(
        self,
        content_id: str,
        status: str,
        note: str = "",
        sheet_name: str = "wholesale_products"
    ):
        """
        상태 업데이트

        Args:
            content_id: 콘텐츠 ID
            status: 새 상태
            note: 비고
            sheet_name: 시트 이름
        """
        if not self.sheet_id:
            return

        result = self.sheets_service.spreadsheets().values().get(
            spreadsheetId=self.sheet_id,
            range=f"{sheet_name}!A:A"
        ).execute()

        values = result.get('values', [])
        row_index = None

        for i, row in enumerate(values):
            if row and row[0] == content_id:
                row_index = i + 1
                break

        if row_index:
            # 상태(P열=16) 및 비고(Q열=17) 업데이트
            self.sheets_service.spreadsheets().values().update(
                spreadsheetId=self.sheet_id,
                range=f"{sheet_name}!P{row_index}:Q{row_index}",
                valueInputOption="RAW",
                body={"values": [[status, note]]}
            ).execute()

            print(f"[Sheets] 상태 업데이트: {content_id} -> {status}")

    def save_registered_product(
        self,
        domeggook_no: str,
        naver_channel_no: str,
        naver_origin_no: str,
        name: str,
        domeggook_price: int,
        naver_price: int,
        options: str = "",
        min_quantity: int = 1,
        status: str = "비전시",
        margin_rate: float = 30.0,
        sheet_name: str = "registered_products"
    ) -> bool:
        """
        네이버 등록 상품 정보를 시트에 저장

        Args:
            domeggook_no: 도매꾹 상품번호
            naver_channel_no: 네이버 채널상품번호
            naver_origin_no: 네이버 원상품번호
            name: 상품명
            domeggook_price: 도매가
            naver_price: 판매가
            options: 옵션 정보
            min_quantity: 최소주문수량
            status: 전시상태
            margin_rate: 마진율 (%)
            sheet_name: 시트 이름

        Returns:
            성공 여부
        """
        if not self.sheet_id:
            print("[Sheets] GOOGLE_SHEET_ID 환경변수 필요")
            return False

        try:
            # 시트가 없으면 생성
            headers = [
                "등록일시", "도매꾹번호", "네이버채널번호", "네이버원상품번호",
                "상품명", "도매가", "판매가", "마진", "옵션",
                "최소주문수량", "전시상태", "도매꾹링크", "네이버링크", "마진율(%)"
            ]

            # 시트 존재 확인
            spreadsheet = self.sheets_service.spreadsheets().get(
                spreadsheetId=self.sheet_id
            ).execute()

            sheet_exists = any(
                s['properties']['title'] == sheet_name
                for s in spreadsheet.get('sheets', [])
            )

            if not sheet_exists:
                # 시트 생성
                self.sheets_service.spreadsheets().batchUpdate(
                    spreadsheetId=self.sheet_id,
                    body={
                        "requests": [{
                            "addSheet": {"properties": {"title": sheet_name}}
                        }]
                    }
                ).execute()

                # 헤더 추가
                self.sheets_service.spreadsheets().values().update(
                    spreadsheetId=self.sheet_id,
                    range=f"{sheet_name}!A1",
                    valueInputOption="RAW",
                    body={"values": [headers]}
                ).execute()

            # 데이터 행 추가
            created_at = datetime.now().strftime("%Y-%m-%d %H:%M")
            margin = naver_price - domeggook_price
            domeggook_link = f"https://domeggook.com/{domeggook_no}"
            naver_link = f"https://smartstore.naver.com/dohsohmall/products/{naver_channel_no}"

            row = [
                created_at,
                domeggook_no,
                naver_channel_no,
                naver_origin_no,
                name[:50],  # 상품명 50자 제한
                domeggook_price,
                naver_price,
                margin,
                options,
                min_quantity,
                status,
                domeggook_link,
                naver_link,
                margin_rate  # 마진율(%) - N열
            ]

            self.sheets_service.spreadsheets().values().append(
                spreadsheetId=self.sheet_id,
                range=f"{sheet_name}!A:N",
                valueInputOption="RAW",
                insertDataOption="INSERT_ROWS",
                body={"values": [row]}
            ).execute()

            print(f"[Sheets] 등록 상품 저장 완료: {name[:30]}...")
            return True

        except Exception as e:
            print(f"[Sheets] 저장 실패: {e}")
            return False


# 테스트
if __name__ == "__main__":
    print("Google Sheets Manager")
    print("=" * 50)

    creds_file = os.getenv("GOOGLE_CREDENTIALS_FILE")
    sheet_id = os.getenv("GOOGLE_SHEET_ID")

    print(f"GOOGLE_CREDENTIALS_FILE: {'설정됨' if creds_file else '미설정'}")
    print(f"GOOGLE_SHEET_ID: {'설정됨' if sheet_id else '미설정'}")

    if creds_file and sheet_id:
        try:
            manager = GoogleSheetsManager()
            manager.init_sheet()
            print("시트 초기화 성공!")
        except Exception as e:
            print(f"오류: {e}")
