# -*- coding: utf-8 -*-
"""도매꾹 상품 KC 인증 정보 확인"""
import sys
import io
import json

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from domeggook_image import DomeggookImageAPI

api = DomeggookImageAPI()

# 핸드폰케이스 상품 상세 조회
item_no = "9277585"
print(f"상품번호 {item_no} 상세정보 조회")
print("=" * 60)

detail = api.get_product_detail(item_no)

if detail:
    print(json.dumps(detail, ensure_ascii=False, indent=2))
else:
    print("상품 정보를 가져올 수 없습니다.")
