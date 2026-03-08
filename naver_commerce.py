# -*- coding: utf-8 -*-
"""
네이버 커머스 API 모듈
======================
스마트스토어에 상품을 등록하기 위한 네이버 커머스 API 연동
"""

import os
import time
import base64
import bcrypt
import requests
from typing import Optional, Dict, Any, List
from dotenv import load_dotenv

load_dotenv(override=True)


class NaverCommerceAPI:
    """네이버 커머스 API 클래스"""

    BASE_URL = "https://api.commerce.naver.com"

    def __init__(self, client_id: str = None, client_secret: str = None):
        self.client_id = client_id or os.getenv("NAVER_COMMERCE_CLIENT_ID")
        self.client_secret = client_secret or os.getenv("NAVER_COMMERCE_CLIENT_SECRET")

        if not self.client_id or not self.client_secret:
            raise ValueError("NAVER_COMMERCE_CLIENT_ID, NAVER_COMMERCE_CLIENT_SECRET 환경변수가 필요합니다.")

        self._access_token = None
        self._token_expires = 0

    def _generate_signature(self, timestamp: str) -> str:
        """
        bcrypt 기반 전자서명 생성
        네이버 커머스 API는 bcrypt 해싱 후 base64 인코딩 필요
        """
        # password = client_id + "_" + timestamp
        password = f"{self.client_id}_{timestamp}"

        # bcrypt 해싱 (client_secret을 salt로 사용)
        hashed = bcrypt.hashpw(
            password.encode('utf-8'),
            self.client_secret.encode('utf-8')
        )

        # base64 인코딩
        signature = base64.b64encode(hashed).decode('utf-8')

        return signature

    def get_access_token(self) -> str:
        """
        OAuth 액세스 토큰 발급
        """
        # 캐시된 토큰이 유효하면 재사용
        if self._access_token and time.time() < self._token_expires - 60:
            return self._access_token

        timestamp = str(int(time.time() * 1000))
        signature = self._generate_signature(timestamp)

        headers = {
            "Content-Type": "application/x-www-form-urlencoded"
        }

        data = {
            "client_id": self.client_id,
            "timestamp": timestamp,
            "client_secret_sign": signature,
            "grant_type": "client_credentials",
            "type": "SELF"
        }

        try:
            response = requests.post(
                f"{self.BASE_URL}/external/v1/oauth2/token",
                headers=headers,
                data=data,
                timeout=30
            )

            if response.status_code == 200:
                result = response.json()
                self._access_token = result.get("access_token")
                expires_in = result.get("expires_in", 3600)
                self._token_expires = time.time() + expires_in
                print(f"[네이버] 액세스 토큰 발급 성공")
                return self._access_token
            else:
                print(f"[ERROR] 토큰 발급 실패: {response.status_code}")
                print(f"  Response: {response.text}")
                return None

        except Exception as e:
            print(f"[ERROR] 토큰 발급 오류: {e}")
            return None

    def _get_headers(self) -> dict:
        """API 호출용 헤더 생성"""
        token = self.get_access_token()
        if not token:
            raise ValueError("액세스 토큰을 발급받을 수 없습니다.")

        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

    def get_categories(self) -> List[Dict]:
        """
        전체 카테고리 목록 조회
        """
        try:
            headers = self._get_headers()
            response = requests.get(
                f"{self.BASE_URL}/external/v1/categories",
                headers=headers,
                timeout=30
            )

            if response.status_code == 200:
                return response.json()
            else:
                print(f"[ERROR] 카테고리 조회 실패: {response.status_code}")
                return []

        except Exception as e:
            print(f"[ERROR] 카테고리 조회 오류: {e}")
            return []

    def search_category(self, keyword: str) -> List[Dict]:
        """
        키워드로 카테고리 검색
        """
        try:
            headers = self._get_headers()
            response = requests.get(
                f"{self.BASE_URL}/external/v1/categories",
                headers=headers,
                params={"keyword": keyword},
                timeout=30
            )

            if response.status_code == 200:
                return response.json()
            else:
                print(f"[ERROR] 카테고리 검색 실패: {response.status_code}")
                return []

        except Exception as e:
            print(f"[ERROR] 카테고리 검색 오류: {e}")
            return []

    def get_channel_info(self) -> Dict:
        """
        채널(스토어) 정보 조회
        """
        try:
            headers = self._get_headers()
            response = requests.get(
                f"{self.BASE_URL}/external/v1/seller/channels",
                headers=headers,
                timeout=30
            )

            if response.status_code == 200:
                return response.json()
            else:
                print(f"[ERROR] 채널 정보 조회 실패: {response.status_code}")
                print(f"  Response: {response.text}")
                return {}

        except Exception as e:
            print(f"[ERROR] 채널 정보 조회 오류: {e}")
            return {}

    def register_product(
        self,
        name: str,
        price: int,
        stock: int,
        category_id: str,
        detail_content: str,
        images: List[str],
        delivery_info: Dict = None,
        options: List[Dict] = None
    ) -> Optional[str]:
        """
        상품 등록

        Args:
            name: 상품명
            price: 판매가
            stock: 재고수량
            category_id: 카테고리 ID
            detail_content: 상세설명 HTML
            images: 이미지 URL 리스트
            delivery_info: 배송 정보
            options: 옵션 정보 [{"name": "색상", "values": ["블랙", "화이트"]}]

        Returns:
            등록된 상품 ID (실패시 None)
        """
        try:
            headers = self._get_headers()

            # 기본 배송 정보 (필수 필드 포함)
            if not delivery_info:
                delivery_info = {
                    "deliveryType": "DELIVERY",  # 택배/등기
                    "deliveryAttributeType": "NORMAL",  # 일반배송
                    "deliveryCompany": "CJGLS",  # CJ대한통운
                    "deliveryFee": {
                        "deliveryFeeType": "FREE",  # 무료배송
                        "baseFee": 0,
                        "deliveryFeePayType": "PREPAID"
                    },
                    "claimDeliveryInfo": {
                        "returnDeliveryFee": 3000,  # 반품 배송비
                        "exchangeDeliveryFee": 6000,  # 교환 배송비
                        "shippingAddressId": None,  # 출고지 주소 (아래에서 조회)
                        "returnAddressId": None  # 반품지 주소 (아래에서 조회)
                    }
                }

            # 출고지/반품지 주소 ID 조회
            address_info = self._get_seller_address()
            if address_info:
                delivery_info["claimDeliveryInfo"]["shippingAddressId"] = address_info.get("shippingAddressId")
                delivery_info["claimDeliveryInfo"]["returnAddressId"] = address_info.get("returnAddressId")

            # 옵션 정보 생성
            option_info = None
            actual_stock = stock
            if options and len(options) > 0:
                option_combinations = []
                option_stock_per_item = max(stock // sum(len(opt.get("values", [])) for opt in options), 10)

                # 단일 옵션 그룹
                if len(options) == 1:
                    option_group = options[0]
                    for value in option_group.get("values", []):
                        option_combinations.append({
                            "optionName1": option_group.get("name", "옵션"),
                            "optionValue1": value,
                            "stockQuantity": option_stock_per_item,
                            "price": 0,  # 추가금액 없음
                            "usable": True
                        })
                # 복수 옵션 그룹
                elif len(options) >= 2:
                    from itertools import product as iter_product
                    all_values = [opt.get("values", []) for opt in options[:2]]
                    for combo in iter_product(*all_values):
                        option_combinations.append({
                            "optionName1": options[0].get("name", "옵션1"),
                            "optionValue1": combo[0],
                            "optionName2": options[1].get("name", "옵션2"),
                            "optionValue2": combo[1],
                            "stockQuantity": option_stock_per_item,
                            "price": 0,
                            "usable": True
                        })

                if option_combinations:
                    option_info = {
                        "optionCombinationSortType": "CREATE",
                        "optionCombinations": option_combinations
                    }
                    actual_stock = 0  # 옵션 상품은 기본 재고 0
                    print(f"  옵션 등록: {len(option_combinations)}개 조합")

            # 상품 등록 데이터
            product_data = {
                "originProduct": {
                    "statusType": "SALE",  # 판매중
                    "saleType": "NEW",     # 새상품
                    "name": name,
                    "detailContent": detail_content,
                    "images": {
                        "representativeImage": {
                            "url": images[0] if images else ""
                        },
                        "optionalImages": [{"url": img} for img in images[1:5]] if len(images) > 1 else []
                    },
                    "salePrice": price,
                    "stockQuantity": actual_stock,
                    "leafCategoryId": category_id,
                    "deliveryInfo": delivery_info,
                    "detailAttribute": {
                        "naverShoppingSearchInfo": {
                            "manufacturerMadeProductYn": False  # 제조사 미등록 상품
                        },
                        "afterServiceInfo": {
                            "afterServiceTelephoneNumber": "010-0000-0000",  # A/S 연락처
                            "afterServiceGuideContent": "상품 불량 시 교환/환불 가능"
                        },
                        "originAreaInfo": {
                            "originAreaCode": "03",  # 국내 (기타)
                            "content": "상세페이지 참조"
                        },
                        "minorPurchasable": True,  # 미성년자 구매 가능
                        "productInfoProvidedNotice": {
                            "productInfoProvidedNoticeType": "ETC",  # 기타 (일반상품)
                            "etc": {
                                "returnCostReason": "상품하자/오배송 시 무료 반품",
                                "noRefundReason": "고객 단순 변심 시 왕복 배송비 부담",
                                "qualityAssuranceStandard": "관련 법률 및 소비자분쟁 해결 기준",
                                "compensationProcedure": "고객센터를 통한 교환/환불 접수",
                                "troubleShootingContents": "상품 상세페이지 참조",
                                "itemName": "상세페이지 참조",
                                "modelName": "상세페이지 참조",
                                "manufacturer": "상세페이지 참조",
                                "customerServicePhoneNumber": "010-0000-0000"
                            }
                        }
                    }
                },
                "smartstoreChannelProduct": {
                    "channelProductName": name,  # 채널 상품명
                    "naverShoppingRegistration": False  # 네이버 쇼핑 미등록
                }
            }

            # 옵션 정보 추가
            if option_info:
                product_data["originProduct"]["optionInfo"] = option_info

            # KC인증 대상 제외 설정 (기본)
            product_data["originProduct"]["detailAttribute"]["certificationTargetExcludeContent"] = {
                "kcCertifiedProductExclusionYn": "TRUE",  # KC인증 대상 아님
                "childCertifiedProductExclusionYn": "TRUE"  # 어린이제품 인증 대상 아님
            }

            response = requests.post(
                f"{self.BASE_URL}/external/v2/products",
                headers=headers,
                json=product_data,
                timeout=60
            )

            if response.status_code in [200, 201]:
                result = response.json()
                product_id = result.get("smartstoreChannelProductNo") or result.get("originProductNo")
                print(f"[네이버] 상품 등록 성공: {product_id}")
                return product_id
            else:
                print(f"[ERROR] 상품 등록 실패: {response.status_code}")
                print(f"  Response: {response.text[:500]}")
                return None

        except Exception as e:
            print(f"[ERROR] 상품 등록 오류: {e}")
            return None

    def _get_seller_address(self) -> Optional[Dict]:
        """
        판매자 출고지/반품지 주소 ID 조회
        """
        try:
            headers = self._get_headers()
            response = requests.get(
                f"{self.BASE_URL}/external/v1/seller/addressbooks/for-page",
                headers=headers,
                params={"page": 1, "size": 10},
                timeout=30
            )

            if response.status_code == 200:
                data = response.json()
                addresses = data.get("contents", [])
                if addresses:
                    # 첫번째 주소를 출고지/반품지로 사용
                    addr = addresses[0]
                    return {
                        "shippingAddressId": addr.get("id"),
                        "returnAddressId": addr.get("id")
                    }
            return None

        except Exception as e:
            print(f"  [WARN] 주소 조회 오류: {e}")
            return None

    def get_products(self, page: int = 1, size: int = 100) -> List[Dict]:
        """
        등록된 상품 목록 조회
        """
        try:
            headers = self._get_headers()
            response = requests.get(
                f"{self.BASE_URL}/external/v2/products",
                headers=headers,
                params={"page": page, "size": size},
                timeout=30
            )

            if response.status_code == 200:
                return response.json().get("contents", [])
            else:
                print(f"[ERROR] 상품 목록 조회 실패: {response.status_code}")
                return []

        except Exception as e:
            print(f"[ERROR] 상품 목록 조회 오류: {e}")
            return []

    def get_product(self, channel_product_no: str) -> Optional[Dict]:
        """
        상품 상세 조회

        Args:
            channel_product_no: 채널 상품번호

        Returns:
            상품 상세 정보
        """
        try:
            headers = self._get_headers()
            response = requests.get(
                f"{self.BASE_URL}/external/v2/products/channel-products/{channel_product_no}",
                headers=headers,
                timeout=30
            )

            if response.status_code == 200:
                data = response.json()
                # API 응답이 contents 래핑되어 있는 경우 처리
                if "contents" in data and isinstance(data["contents"], dict):
                    return data["contents"]
                return data
            else:
                print(f"[ERROR] 상품 조회 실패: {response.status_code}")
                print(f"  Response: {response.text[:300]}")
                return None

        except Exception as e:
            print(f"[ERROR] 상품 조회 오류: {e}")
            return None

    def get_product_info(self, channel_product_no: str) -> Optional[dict]:
        """
        상품 가격 및 전시상태 한번에 조회

        Args:
            channel_product_no: 채널 상품번호

        Returns:
            {"price": 가격, "display_status": 전시상태} (실패시 None)
        """
        try:
            product = self.get_product(channel_product_no)
            if product:
                origin_product = product.get("originProduct", {})
                smart = product.get("smartstoreChannelProduct", {})
                return {
                    "price": origin_product.get("salePrice"),
                    "display_status": smart.get("channelProductDisplayStatusType")
                }
            return None
        except Exception:
            return None

    def update_product_price(self, channel_product_no: str, new_price: int) -> bool:
        """
        상품 가격 수정
        channel-products PUT 엔드포인트를 사용하여 직접 수정

        Args:
            channel_product_no: 채널 상품번호
            new_price: 새 판매가

        Returns:
            성공 여부
        """
        try:
            headers = self._get_headers()

            # 먼저 상품 정보 조회하여 현재 정보 얻기
            product = self.get_product(channel_product_no)
            if not product:
                print(f"[ERROR] 상품을 찾을 수 없습니다: {channel_product_no}")
                return False

            # 기존 상품 정보를 복사하여 사용 (PUT은 전체 데이터 필요)
            import copy
            origin_product = copy.deepcopy(product.get("originProduct", {}))
            smart_product = copy.deepcopy(product.get("smartstoreChannelProduct", {}))

            # 가격만 수정
            origin_product["salePrice"] = new_price

            # 전체 데이터로 PUT 요청
            update_data = {
                "originProduct": origin_product,
                "smartstoreChannelProduct": smart_product
            }

            # PUT 요청으로 채널 상품 수정 (channel-products 엔드포인트 사용)
            response = requests.put(
                f"{self.BASE_URL}/external/v2/products/channel-products/{channel_product_no}",
                headers=headers,
                json=update_data,
                timeout=30
            )

            if response.status_code in [200, 204]:
                print(f"[네이버] 가격 수정 성공: {channel_product_no} -> {new_price:,}원")
                return True
            else:
                print(f"[ERROR] 가격 수정 실패: {response.status_code}")
                print(f"  Response: {response.text[:300]}")
                return False

        except Exception as e:
            print(f"[ERROR] 가격 수정 오류: {e}")
            return False

    def update_product_price_and_delivery(
        self,
        channel_product_no: str,
        new_price: int,
        free_shipping: bool,
        delivery_fee: int = 0
    ) -> bool:
        """
        상품 가격과 배송비 설정을 동시에 수정
        channel-products PUT 엔드포인트를 사용하여 직접 수정

        Args:
            channel_product_no: 채널 상품번호
            new_price: 새 판매가
            free_shipping: 무료배송 여부 (True: 무료배송, False: 유료배송)
            delivery_fee: 유료배송 시 배송비 (free_shipping=False일 때 사용)

        Returns:
            성공 여부
        """
        try:
            headers = self._get_headers()

            # 먼저 상품 정보 조회하여 현재 정보 얻기
            product = self.get_product(channel_product_no)
            if not product:
                print(f"[ERROR] 상품을 찾을 수 없습니다: {channel_product_no}")
                return False

            # 기존 상품 정보를 복사하여 사용 (PUT은 전체 데이터 필요)
            import copy
            origin_product = copy.deepcopy(product.get("originProduct", {}))
            smart_product = copy.deepcopy(product.get("smartstoreChannelProduct", {}))

            # 가격 수정
            origin_product["salePrice"] = new_price

            # 배송비 설정 업데이트
            if "deliveryInfo" not in origin_product:
                origin_product["deliveryInfo"] = {}
            if "deliveryFee" not in origin_product["deliveryInfo"]:
                origin_product["deliveryInfo"]["deliveryFee"] = {}

            if free_shipping:
                # 무료배송
                origin_product["deliveryInfo"]["deliveryFee"]["deliveryFeeType"] = "FREE"
                origin_product["deliveryInfo"]["deliveryFee"]["baseFee"] = 0
            else:
                # 유료배송 (고정 배송비)
                origin_product["deliveryInfo"]["deliveryFee"]["deliveryFeeType"] = "PAID"
                origin_product["deliveryInfo"]["deliveryFee"]["baseFee"] = delivery_fee

            # 배송비 결제방식 (필수)
            if "deliveryFeePayType" not in origin_product["deliveryInfo"]["deliveryFee"]:
                origin_product["deliveryInfo"]["deliveryFee"]["deliveryFeePayType"] = "PREPAID"

            # 전체 데이터로 PUT 요청
            update_data = {
                "originProduct": origin_product,
                "smartstoreChannelProduct": smart_product
            }

            # PUT 요청으로 채널 상품 수정 (channel-products 엔드포인트 사용)
            response = requests.put(
                f"{self.BASE_URL}/external/v2/products/channel-products/{channel_product_no}",
                headers=headers,
                json=update_data,
                timeout=30
            )

            if response.status_code in [200, 204]:
                shipping_text = "무료배송" if free_shipping else f"배송비 {delivery_fee:,}원"
                print(f"[네이버] 가격/배송비 수정 성공: {channel_product_no} -> {new_price:,}원 ({shipping_text})")
                return True
            else:
                print(f"[ERROR] 가격/배송비 수정 실패: {response.status_code}")
                print(f"  Response: {response.text[:300]}")
                return False

        except Exception as e:
            print(f"[ERROR] 가격/배송비 수정 오류: {e}")
            return False

    def update_product_with_options(
        self,
        channel_product_no: str,
        new_price: int,
        free_shipping: bool,
        naver_delivery_fee: int,
        naver_options: List[Dict]
    ) -> tuple:
        """
        옵션 상품의 기본가 · 배송비 · 옵션별 추가금액 + 재고를 한 번에 동기화

        변동이 없으면 PUT 호출을 하지 않아 불필요한 API 소모를 방지합니다.

        Args:
            channel_product_no: 채널 상품번호
            new_price: 네이버 기본 판매가
            free_shipping: 무료배송 여부
            naver_delivery_fee: 유료 배송비 (free_shipping=False 일 때 사용)
            naver_options: 옵션 목록
                [{"name": 옵션값, "naver_additional_price": 추가금, "qty": 재고, "visible": bool}]
                name 은 네이버 optionValue1 과 정확히 일치해야 합니다.

        Returns:
            (api_success: bool, anything_changed: bool)
        """
        try:
            headers = self._get_headers()

            product = self.get_product(channel_product_no)
            if not product:
                print(f"  [ERROR] 상품 조회 실패: {channel_product_no}")
                return False, False

            import copy
            origin_product = copy.deepcopy(product.get("originProduct", {}))
            smart_product = copy.deepcopy(product.get("smartstoreChannelProduct", {}))

            changed = False

            # ── 기본가 비교 ──────────────────────────────────────────
            if origin_product.get("salePrice") != new_price:
                origin_product["salePrice"] = new_price
                changed = True

            # ── 배송비 비교 ──────────────────────────────────────────
            if "deliveryInfo" not in origin_product:
                origin_product["deliveryInfo"] = {}
            if "deliveryFee" not in origin_product["deliveryInfo"]:
                origin_product["deliveryInfo"]["deliveryFee"] = {}

            target_fee_type = "FREE" if free_shipping else "PAID"
            current_fee_type = origin_product["deliveryInfo"]["deliveryFee"].get("deliveryFeeType", "")
            current_base_fee = origin_product["deliveryInfo"]["deliveryFee"].get("baseFee", 0)

            if current_fee_type != target_fee_type:
                changed = True
            if not free_shipping and current_base_fee != naver_delivery_fee:
                changed = True

            origin_product["deliveryInfo"]["deliveryFee"]["deliveryFeeType"] = target_fee_type
            origin_product["deliveryInfo"]["deliveryFee"]["baseFee"] = 0 if free_shipping else naver_delivery_fee
            if "deliveryFeePayType" not in origin_product["deliveryInfo"]["deliveryFee"]:
                origin_product["deliveryInfo"]["deliveryFee"]["deliveryFeePayType"] = "PREPAID"

            # ── 옵션 비교 및 업데이트 ────────────────────────────────
            opt_info = origin_product.get("optionInfo", {})
            combinations = opt_info.get("optionCombinations", [])

            if combinations and naver_options:
                dom_opt_map = {opt["name"]: opt for opt in naver_options}
                matched = 0

                for combo in combinations:
                    opt_value = combo.get("optionValue1", "")
                    if opt_value not in dom_opt_map:
                        continue

                    dom = dom_opt_map[opt_value]
                    matched += 1

                    target_additional = dom["naver_additional_price"]
                    target_qty        = dom["qty"]
                    target_usable     = dom["visible"] and dom["qty"] > 0

                    if (combo.get("price", 0)         != target_additional or
                        combo.get("stockQuantity", 0) != target_qty        or
                        combo.get("usable", True)     != target_usable):

                        combo["price"]         = target_additional
                        combo["stockQuantity"] = target_qty
                        combo["usable"]        = target_usable
                        changed = True

                origin_product["optionInfo"]["optionCombinations"] = combinations
                print(f"  옵션 매핑: {matched}/{len(combinations)}개 매칭")

                if matched == 0:
                    print(f"  [WARN] 옵션명 불일치 - 도매꾹/네이버 옵션명을 확인하세요")

            if not changed:
                return True, False

            # ── PUT 요청 ─────────────────────────────────────────────
            update_data = {
                "originProduct": origin_product,
                "smartstoreChannelProduct": smart_product
            }
            response = requests.put(
                f"{self.BASE_URL}/external/v2/products/channel-products/{channel_product_no}",
                headers=headers,
                json=update_data,
                timeout=60
            )

            if response.status_code in [200, 204]:
                return True, True
            else:
                print(f"  [ERROR] 옵션 동기화 PUT 실패: {response.status_code}")
                print(f"  Response: {response.text[:300]}")
                return False, False

        except Exception as e:
            print(f"  [ERROR] 옵션 동기화 오류: {e}")
            return False, False

    def update_product_options(
        self,
        channel_product_no: str,
        options: List[Dict]
    ) -> bool:
        """
        기존 상품에 옵션 추가/수정

        Args:
            channel_product_no: 채널 상품번호
            options: 옵션 목록 [{"name": "색상", "values": ["브라운블랙", "다크브라운"]}]

        Returns:
            성공 여부
        """
        try:
            headers = self._get_headers()

            # 기존 상품 정보 조회
            product = self.get_product(channel_product_no)
            if not product:
                print("[ERROR] 상품을 찾을 수 없습니다")
                return False

            origin_product = product.get("originProduct", {})
            origin_product_no = origin_product.get("originProductNo")
            stock_quantity = origin_product.get("stockQuantity", 100)
            stock_per_option = max(stock_quantity // sum(len(opt.get("values", [])) for opt in options), 10)

            # 옵션 그룹 이름 생성
            option_group_names = {}
            for i, opt in enumerate(options[:3], 1):  # 최대 3개 옵션 그룹
                option_group_names[f"optionGroupName{i}"] = opt.get("name", f"옵션{i}")

            # 옵션 조합 생성
            option_combinations = []

            # 단일 옵션 그룹인 경우
            if len(options) == 1:
                option_group = options[0]
                for value in option_group.get("values", []):
                    option_combinations.append({
                        "optionName1": option_group.get("name", "옵션"),
                        "optionValue1": value,
                        "stockQuantity": stock_per_option,
                        "price": 0,
                        "usable": True
                    })
            # 복수 옵션 그룹인 경우
            elif len(options) >= 2:
                from itertools import product as iter_product
                all_values = [opt.get("values", []) for opt in options[:2]]
                for combo in iter_product(*all_values):
                    option_combinations.append({
                        "optionName1": options[0].get("name", "옵션1"),
                        "optionValue1": combo[0],
                        "optionName2": options[1].get("name", "옵션2"),
                        "optionValue2": combo[1],
                        "stockQuantity": stock_per_option,
                        "price": 0,
                        "usable": True
                    })

            print(f"  옵션 조합 생성: {len(option_combinations)}개")

            # 원상품 수정 API 사용 (PUT /external/v2/products/origin-products/{originProductNo})
            update_data = {
                "originProduct": {
                    "stockQuantity": 0,  # 옵션 상품은 전체 재고 0
                    "optionInfo": {
                        "optionCombinationSortType": "CREATE",
                        "optionCombinationGroupNames": option_group_names,
                        "optionCombinations": option_combinations
                    }
                }
            }

            # PUT 요청으로 원상품 수정
            response = requests.put(
                f"{self.BASE_URL}/external/v2/products/origin-products/{origin_product_no}",
                headers=headers,
                json=update_data,
                timeout=60
            )

            if response.status_code in [200, 204]:
                print(f"[네이버] 상품 옵션 추가 성공: {len(option_combinations)}개 옵션")
                return True
            else:
                print(f"[ERROR] 상품 옵션 추가 실패 (PUT): {response.status_code}")
                print(f"  Response: {response.text[:500]}")

                # PATCH 요청 시도
                print("  PATCH 요청 시도...")
                response = requests.patch(
                    f"{self.BASE_URL}/external/v2/products/origin-products/{origin_product_no}",
                    headers=headers,
                    json=update_data,
                    timeout=60
                )

                if response.status_code in [200, 204]:
                    print(f"[네이버] 상품 옵션 추가 성공 (PATCH): {len(option_combinations)}개 옵션")
                    return True
                else:
                    print(f"[ERROR] 상품 옵션 추가 실패 (PATCH): {response.status_code}")
                    print(f"  Response: {response.text[:500]}")
                    return False

        except Exception as e:
            print(f"[ERROR] 상품 옵션 추가 오류: {e}")
            import traceback
            traceback.print_exc()
            return False

    def upload_image(self, image_url: str) -> Optional[str]:
        """
        외부 이미지 URL을 다운로드 후 네이버 커머스에 업로드

        Args:
            image_url: 외부 이미지 URL

        Returns:
            업로드된 네이버 이미지 URL (실패시 None)
        """
        try:
            # 1. 외부 이미지 다운로드 (Referer 헤더 추가로 핫링크 방지 우회)
            download_headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Referer": "https://domeggook.com/",
                "Accept": "image/webp,image/apng,image/*,*/*;q=0.8"
            }
            img_response = requests.get(image_url, headers=download_headers, timeout=30)
            if img_response.status_code != 200:
                print(f"  [WARN] 이미지 다운로드 실패: {img_response.status_code}")
                return None

            # 이미지 바이트에서 실제 형식 감지
            content = img_response.content
            if content[:8] == b'\x89PNG\r\n\x1a\n':
                content_type = 'image/png'
                filename = "image.png"
            elif content[:3] == b'\xff\xd8\xff':
                content_type = 'image/jpeg'
                filename = "image.jpg"
            elif content[:6] in (b'GIF87a', b'GIF89a'):
                content_type = 'image/gif'
                filename = "image.gif"
            elif content[:2] == b'BM':
                content_type = 'image/bmp'
                filename = "image.bmp"
            else:
                # 기본값
                content_type = 'image/jpeg'
                filename = "image.jpg"

            # 2. 네이버에 multipart/form-data로 업로드
            token = self.get_access_token()
            if not token:
                return None

            headers = {
                "Authorization": f"Bearer {token}"
                # Content-Type은 requests가 자동으로 설정
            }

            files = {
                "imageFiles": (filename, img_response.content, content_type)
            }

            response = requests.post(
                f"{self.BASE_URL}/external/v1/product-images/upload",
                headers=headers,
                files=files,
                timeout=60
            )

            if response.status_code == 200:
                result = response.json()
                images = result.get("images", [])
                if images:
                    uploaded_url = images[0].get("url")
                    print(f"  이미지 업로드 성공")
                    return uploaded_url
            else:
                print(f"  [WARN] 이미지 업로드 실패: {response.status_code} - {response.text[:200]}")

            return None

        except Exception as e:
            print(f"  [WARN] 이미지 업로드 오류: {e}")
            return None

    def get_delivery_template(self) -> Optional[Dict]:
        """
        배송 정보 템플릿 조회 (반품/교환 주소 포함)
        """
        try:
            headers = self._get_headers()
            response = requests.get(
                f"{self.BASE_URL}/external/v1/seller/delivery-templates",
                headers=headers,
                timeout=30
            )

            if response.status_code == 200:
                templates = response.json()
                if templates:
                    return templates[0]  # 첫번째 템플릿 사용
            return None

        except Exception as e:
            print(f"  [WARN] 배송 템플릿 조회 오류: {e}")
            return None

    def register_product_from_domeggook(
        self,
        product,  # ImageAllowedProduct
        category_id: str = None,
        check_min_quantity: bool = True
    ) -> Optional[str]:
        """
        도매꾹 상품을 네이버에 등록 (30% 마진 적용)

        Args:
            product: ImageAllowedProduct 객체
            category_id: 네이버 카테고리 ID (없으면 자동 매칭 시도)
            check_min_quantity: 최소구매수량 체크 여부 (기본 True)

        Returns:
            등록된 상품 ID (실패시 None)
        """
        try:
            # 최소구매수량 체크 (1개만 등록 가능)
            if check_min_quantity and product.min_quantity > 1:
                print(f"  [SKIP] 최소구매수량 {product.min_quantity}개 - 1개만 허용")
                return None

            # 30% 마진 적용 가격
            sale_price = product.margin_price

            # 마진 계산 (배송비 결정용)
            margin = sale_price - product.price
            domeggook_delivery_fee = product.delivery_fee

            # 배송비 결정: 마진이 3000원 이상이면 무료배송, 아니면 도매꾹 배송비 적용
            if margin >= 3000:
                naver_delivery_fee = 0
                delivery_fee_type = "FREE"
                print(f"  배송비: 무료 (마진 {margin:,}원 >= 3,000원)")
            else:
                naver_delivery_fee = domeggook_delivery_fee
                delivery_fee_type = "PAID" if domeggook_delivery_fee > 0 else "FREE"
                print(f"  배송비: {naver_delivery_fee:,}원 (도매꾹 동일)")

            # 배송 정보 설정
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

            # 이미지 준비 (대표이미지 + 추가이미지)
            images = []
            uploaded_detail_images = []  # 상세설명에 넣을 업로드된 이미지

            # 대표 이미지 업로드
            if product.image_url:
                print(f"  대표 이미지 업로드 중...")
                uploaded_url = self.upload_image(product.image_url)
                if uploaded_url:
                    images.append(uploaded_url)

            # 상세 이미지 업로드 (추가 이미지 + 상세설명용)
            for i, img in enumerate(product.detail_images[:4]):
                print(f"  추가 이미지 {i+1}/{min(len(product.detail_images), 4)} 업로드 중...")
                uploaded = self.upload_image(img)
                if uploaded:
                    images.append(uploaded)
                    uploaded_detail_images.append(uploaded)

            # 상세설명 HTML 구성 (도매꾹 상세정보 그대로 반영)
            detail_content = self._build_detail_content(product, uploaded_detail_images)

            # 카테고리 ID가 없으면 AI 분류 또는 자동 매칭 시도
            if not category_id:
                try:
                    from run_register_by_link import find_category
                    # 도매꾹 카테고리 정보도 전달
                    domeggook_cat = getattr(product, 'category_name', '') or ''
                    category_id = find_category(self, product.name, domeggook_cat)
                except ImportError:
                    # fallback: 기존 방식
                    categories = self.search_category(product.name.split()[0] if product.name else "")
                    if categories:
                        category_id = categories[0].get("id")

                if not category_id:
                    print(f"  [WARN] 카테고리를 찾을 수 없습니다. 기본 카테고리 필요")
                    return None

            # 도매꾹 옵션을 네이버 옵션 형식으로 변환
            naver_options = None
            if product.options and len(product.options) > 0:
                # 옵션 그룹화 (같은 옵션명 기준)
                option_groups = {}
                for opt in product.options:
                    opt_name = opt.name or "옵션"
                    if opt_name not in option_groups:
                        option_groups[opt_name] = []
                    if opt.value and opt.value not in option_groups[opt_name]:
                        option_groups[opt_name].append(opt.value)

                # 네이버 옵션 형식으로 변환
                naver_options = [
                    {"name": name, "values": values}
                    for name, values in option_groups.items()
                    if values  # 값이 있는 옵션만
                ]
                if naver_options:
                    print(f"  도매꾹 옵션 발견: {len(naver_options)}개 그룹, "
                          f"총 {sum(len(opt['values']) for opt in naver_options)}개 옵션값")

            # 상품 등록
            return self.register_product(
                name=product.name,
                price=sale_price,
                stock=100,  # 기본 재고
                category_id=category_id,
                detail_content=detail_content,
                images=images,
                delivery_info=delivery_info,
                options=naver_options
            )

        except Exception as e:
            print(f"  [ERROR] 도매꾹 상품 등록 실패: {e}")
            return None

    def _build_detail_content(self, product, uploaded_images: List[str] = None) -> str:
        """
        도매꾹 상품 정보를 기반으로 네이버 상세설명 HTML 생성

        Args:
            product: ImageAllowedProduct 객체
            uploaded_images: 업로드된 이미지 URL 리스트

        Returns:
            상세설명 HTML
        """
        html_parts = []

        # 도매꾹 원본 상세설명이 있으면 그대로 사용
        if product.detail_html:
            html_parts.append(product.detail_html)
        else:
            # 원본 상세설명이 없으면 기본 템플릿 생성
            html_parts.append(f"<h2>{product.name}</h2>")

            # 상품 이미지 추가
            if uploaded_images:
                html_parts.append("<div style='text-align:center;'>")
                for img_url in uploaded_images:
                    html_parts.append(f'<img src="{img_url}" style="max-width:100%; margin:10px 0;" />')
                html_parts.append("</div>")

            # 상품 기본 정보
            html_parts.append("<div style='margin-top:20px;'>")
            if product.brand:
                html_parts.append(f"<p><strong>브랜드:</strong> {product.brand}</p>")
            if product.category_name:
                html_parts.append(f"<p><strong>카테고리:</strong> {product.category_name}</p>")
            html_parts.append("</div>")

        return "\n".join(html_parts)


    # =========================================================================
    # 주문 관련 API (드롭쉬핑용)
    # =========================================================================

    def get_new_orders(
        self,
        status: str = "PAYED",
        from_datetime: str = None,
        to_datetime: str = None
    ) -> List[Dict]:
        """
        새 주문 조회 (결제완료 상태)

        Args:
            status: 주문 상태 (PAYED: 결제완료, DELIVERING: 배송중 등)
            from_datetime: 조회 시작일시 (ISO 8601)
            to_datetime: 조회 종료일시 (ISO 8601)

        Returns:
            주문 목록
        """
        try:
            from datetime import datetime, timedelta

            headers = self._get_headers()

            # 기본값: 최근 7일
            if not to_datetime:
                to_datetime = datetime.now().strftime("%Y-%m-%dT%H:%M:%S.000+09:00")
            if not from_datetime:
                from_date = datetime.now() - timedelta(days=7)
                from_datetime = from_date.strftime("%Y-%m-%dT%H:%M:%S.000+09:00")

            params = {
                "productOrderStatus": status
            }

            # lastChangedFrom/To 파라미터 사용
            response = requests.get(
                f"{self.BASE_URL}/external/v1/pay-order/seller/product-orders/last-changed-statuses",
                headers=headers,
                params={
                    "lastChangedFrom": from_datetime,
                    "lastChangedTo": to_datetime,
                    **params
                },
                timeout=30
            )

            if response.status_code == 200:
                data = response.json()
                orders = data.get("data", {}).get("lastChangeStatuses", [])
                print(f"[네이버] {len(orders)}개 주문 조회됨 (상태: {status})")
                return orders
            else:
                print(f"[ERROR] 주문 조회 실패: {response.status_code}")
                print(f"  Response: {response.text[:300]}")
                return []

        except Exception as e:
            print(f"[ERROR] 주문 조회 오류: {e}")
            return []

    def get_order_detail(self, product_order_id: str) -> Optional[Dict]:
        """
        주문 상세 정보 조회 (배송지 정보 포함)

        Args:
            product_order_id: 상품주문번호

        Returns:
            주문 상세 정보 (배송지 주소, 수취인 정보 등)
        """
        try:
            headers = self._get_headers()

            response = requests.get(
                f"{self.BASE_URL}/external/v1/pay-order/seller/product-orders/{product_order_id}",
                headers=headers,
                timeout=30
            )

            if response.status_code == 200:
                data = response.json()
                return data.get("data")
            else:
                print(f"[ERROR] 주문 상세 조회 실패: {response.status_code}")
                return None

        except Exception as e:
            print(f"[ERROR] 주문 상세 조회 오류: {e}")
            return None

    def get_orders_detail_batch(self, product_order_ids: List[str]) -> List[Dict]:
        """
        주문 상세 정보 일괄 조회

        Args:
            product_order_ids: 상품주문번호 리스트

        Returns:
            주문 상세 정보 리스트
        """
        try:
            headers = self._get_headers()

            response = requests.post(
                f"{self.BASE_URL}/external/v1/pay-order/seller/product-orders/query",
                headers=headers,
                json={"productOrderIds": product_order_ids},
                timeout=30
            )

            if response.status_code == 200:
                data = response.json()
                return data.get("data", [])
            else:
                print(f"[ERROR] 주문 일괄 조회 실패: {response.status_code}")
                return []

        except Exception as e:
            print(f"[ERROR] 주문 일괄 조회 오류: {e}")
            return []

    def dispatch_order(
        self,
        product_order_id: str,
        delivery_company: str,
        tracking_number: str
    ) -> bool:
        """
        주문 발송 처리

        Args:
            product_order_id: 상품주문번호
            delivery_company: 택배사 코드 (CJGLS, LOGEN, HANJIN 등)
            tracking_number: 운송장번호

        Returns:
            성공 여부
        """
        try:
            headers = self._get_headers()

            data = {
                "dispatchProductOrders": [{
                    "productOrderId": product_order_id,
                    "deliveryMethod": "DELIVERY",
                    "deliveryCompanyCode": delivery_company,
                    "trackingNumber": tracking_number
                }]
            }

            response = requests.post(
                f"{self.BASE_URL}/external/v1/pay-order/seller/product-orders/dispatch",
                headers=headers,
                json=data,
                timeout=30
            )

            if response.status_code == 200:
                result = response.json()
                success_list = result.get("data", {}).get("successProductOrderIds", [])
                if product_order_id in success_list:
                    print(f"[네이버] 발송처리 완료: {product_order_id}")
                    return True
                else:
                    fail_list = result.get("data", {}).get("failProductOrderInfos", [])
                    print(f"[ERROR] 발송처리 실패: {fail_list}")
                    return False
            else:
                print(f"[ERROR] 발송처리 API 실패: {response.status_code}")
                return False

        except Exception as e:
            print(f"[ERROR] 발송처리 오류: {e}")
            return False

    def extract_shipping_info(self, order_detail: Dict) -> Optional[Dict]:
        """
        주문 상세에서 배송지 정보 추출

        Args:
            order_detail: get_order_detail 응답

        Returns:
            배송지 정보 딕셔너리
        """
        try:
            shipping = order_detail.get("order", {}).get("shippingAddress", {})
            orderer = order_detail.get("order", {}).get("ordererName", "")

            # 상품 정보
            product_order = order_detail.get("productOrder", {})

            return {
                "receiver_name": shipping.get("name", ""),
                "receiver_tel": shipping.get("tel1", ""),
                "receiver_tel2": shipping.get("tel2", ""),
                "zip_code": shipping.get("zipCode", ""),
                "address": shipping.get("baseAddress", ""),
                "detail_address": shipping.get("detailAddress", ""),
                "full_address": f"{shipping.get('baseAddress', '')} {shipping.get('detailAddress', '')}".strip(),
                "delivery_memo": shipping.get("deliveryMemo", ""),
                "orderer_name": orderer,
                # 상품 정보
                "product_name": product_order.get("productName", ""),
                "quantity": product_order.get("quantity", 1),
                "product_option": product_order.get("productOption", ""),
                "product_order_id": product_order.get("productOrderId", ""),
                "order_id": order_detail.get("order", {}).get("orderId", "")
            }
        except Exception as e:
            print(f"[ERROR] 배송지 정보 추출 오류: {e}")
            return None


# 테스트
if __name__ == "__main__":
    import sys
    import io
    if sys.platform == "win32":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

    print("=" * 60)
    print("네이버 커머스 API 테스트")
    print("=" * 60)

    try:
        api = NaverCommerceAPI()

        # 토큰 발급 테스트
        print("\n[1] 액세스 토큰 발급 테스트")
        token = api.get_access_token()
        if token:
            print(f"  토큰: {token[:30]}...")
        else:
            print("  토큰 발급 실패")

        # 채널 정보 조회
        if token:
            print("\n[2] 채널 정보 조회")
            channel = api.get_channel_info()
            print(f"  채널: {channel}")

    except Exception as e:
        print(f"오류: {e}")
