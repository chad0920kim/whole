# -*- coding: utf-8 -*-
"""
도매 상품 발굴 시스템 (Wholesale Product Finder)
================================================
1. 네이버 쇼핑에서 카테고리별 인기 상품 수집
2. 도매꾹에서 사입 가능한 상품 매칭
3. Google Sheets에 결과 저장
"""

import os
import sys
import io
import argparse
from datetime import datetime
from dotenv import load_dotenv

# Windows 콘솔 UTF-8 설정
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

load_dotenv(override=True)

from naver_shopping import NaverShoppingAPI, ProductInfo
from domeggook import DomeggookSearcher
from google_sheets import GoogleSheetsManager
from ai_comparator import AIProductComparator


class WholesaleProductFinder:
    """도매 상품 발굴 시스템"""

    def __init__(self, use_sheets: bool = True, use_ai: bool = True):
        """
        Args:
            use_sheets: Google Sheets 저장 여부
            use_ai: AI 상품 비교 사용 여부
        """
        self.naver_api = NaverShoppingAPI()
        self.domeggook = DomeggookSearcher()
        self.use_sheets = use_sheets
        self.use_ai = use_ai
        self._sheets_manager = None
        self._ai_comparator = None

    @property
    def sheets_manager(self):
        """Google Sheets 매니저 (지연 로딩)"""
        if self._sheets_manager is None and self.use_sheets:
            try:
                self._sheets_manager = GoogleSheetsManager()
            except Exception as e:
                print(f"[WARN] Google Sheets 연결 실패: {e}")
                self.use_sheets = False
        return self._sheets_manager

    @property
    def ai_comparator(self):
        """AI 비교기 (지연 로딩)"""
        if self._ai_comparator is None and self.use_ai:
            try:
                self._ai_comparator = AIProductComparator()
                if not self._ai_comparator.client:
                    print("[WARN] OpenAI API 키가 없어 AI 비교를 사용할 수 없습니다.")
                    self.use_ai = False
                    self._ai_comparator = None
            except Exception as e:
                print(f"[WARN] AI 비교기 초기화 실패: {e}")
                self.use_ai = False
        return self._ai_comparator

    def find_wholesale_products(
        self,
        keyword: str,
        category: str = "",
        top_n: int = 10,
        min_margin: int = 10000
    ) -> dict:
        """
        키워드로 도매 상품 발굴

        Args:
            keyword: 검색 키워드
            category: 카테고리
            top_n: 수집할 상품 수
            min_margin: 최소 마진 금액 (기본 10,000원)

        Returns:
            {
                "keyword": str,
                "category": str,
                "products": [ProductInfo],
                "matches": {rank: {...}},
                "content_id": str
            }
        """
        print("\n" + "=" * 60)
        print(f"도매 상품 발굴: {keyword}")
        print("=" * 60)

        # 1. 네이버 쇼핑에서 인기 상품 수집
        products = self.naver_api.get_top_products(keyword, top_n=top_n)

        if not products:
            print(f"[ERROR] '{keyword}' 상품을 찾을 수 없습니다.")
            return {"keyword": keyword, "category": category, "products": [], "matches": {}}

        # 2. 도매꾹에서 매칭 상품 찾기
        matches = self.domeggook.match_products(products, min_margin=min_margin)

        # 3. 결과 요약
        print("\n" + "=" * 60)
        print("매칭 결과 요약")
        print("=" * 60)

        matched_count = len(matches)
        total_margin = sum(m['margin'] for m in matches.values())
        avg_margin_rate = sum(m['margin_rate'] for m in matches.values()) / matched_count if matched_count > 0 else 0

        print(f"  - 수집 상품: {len(products)}개")
        print(f"  - 매칭 성공: {matched_count}개 ({matched_count/len(products)*100:.1f}%)")
        print(f"  - 평균 마진율: {avg_margin_rate:.1f}%")

        # 고마진 상품 출력
        if matches:
            print("\n[고마진 상품 TOP 5]")
            sorted_matches = sorted(matches.items(), key=lambda x: x[1]['margin'], reverse=True)
            for rank, match in sorted_matches[:5]:
                product = next((p for p in products if p.rank == rank), None)
                if product:
                    print(f"  #{rank} {product.name[:30]}...")
                    print(f"      네이버: {product.price:,}원 → 도매꾹: {match['price']:,}원")
                    print(f"      마진: {match['margin']:,}원 ({match['margin_rate']:.1f}%)")

        # 4. Google Sheets 저장 (마진 1만원 이상 상품만 + AI 비교)
        saved_count = 0
        if self.use_sheets and self.sheets_manager and matches:
            try:
                saved_count = self.sheets_manager.save_margin_products(
                    keyword=keyword,
                    category=category,
                    products=products,
                    domeggook_matches=matches,
                    min_margin=min_margin,
                    ai_comparator=self.ai_comparator if self.use_ai else None
                )
            except Exception as e:
                print(f"[WARN] Sheets 저장 실패: {e}")

        return {
            "keyword": keyword,
            "category": category,
            "products": products,
            "matches": matches,
            "saved_count": saved_count
        }

    def find_trending_wholesale_products(
        self,
        top_keywords: int = 5,
        top_products: int = 10,
        min_margin: int = 10000
    ) -> list:
        """
        트렌딩 키워드 기반 도매 상품 발굴

        Args:
            top_keywords: 분석할 키워드 수
            top_products: 키워드당 수집할 상품 수
            min_margin: 최소 마진 금액 (기본 10,000원)

        Returns:
            결과 리스트
        """
        print("\n" + "=" * 60)
        print("트렌딩 키워드 기반 도매 상품 발굴")
        print("=" * 60)

        # 트렌딩 키워드 수집
        trending_keywords = self.naver_api.get_trending_keywords(top_n=top_keywords)

        if not trending_keywords:
            print("[ERROR] 트렌딩 키워드를 수집할 수 없습니다.")
            return []

        results = []

        for kw_info in trending_keywords:
            keyword = kw_info['keyword']
            category = kw_info.get('category', '')

            # 중복 체크
            if self.use_sheets and self.sheets_manager:
                saved_keywords = self.sheets_manager.get_saved_keywords()
                if keyword.lower() in saved_keywords:
                    print(f"\n[SKIP] '{keyword}' - 이미 수집된 키워드")
                    continue

            # 도매 상품 발굴
            result = self.find_wholesale_products(
                keyword=keyword,
                category=category,
                top_n=top_products,
                min_margin=min_margin
            )
            results.append(result)

        # 전체 결과 요약
        print("\n" + "=" * 60)
        print("전체 결과 요약")
        print("=" * 60)

        total_products = sum(len(r['products']) for r in results)
        total_matches = sum(len(r['matches']) for r in results)

        print(f"  - 분석 키워드: {len(results)}개")
        print(f"  - 수집 상품: {total_products}개")
        print(f"  - 매칭 상품: {total_matches}개")

        return results

    def scan_all_categories(
        self,
        products_per_keyword: int = 10,
        min_margin: int = 10000,
        clear_sheet: bool = False
    ) -> dict:
        """
        전체 카테고리 스캔하여 마진 상품 발굴

        Args:
            products_per_keyword: 키워드당 수집할 상품 수
            min_margin: 최소 마진 금액
            clear_sheet: True면 기존 시트 데이터 초기화

        Returns:
            전체 결과 요약
        """
        import time

        print("\n" + "=" * 60)
        print("전체 카테고리 도매 상품 스캔")
        print("=" * 60)

        # 시트 초기화 (옵션)
        if clear_sheet and self.use_sheets and self.sheets_manager:
            try:
                self.sheets_manager.init_sheet("margin_products")
                self.sheets_manager.clear_sheet("margin_products")
            except Exception as e:
                print(f"[WARN] 시트 초기화 실패: {e}")

        all_results = []
        total_saved = 0

        # 카테고리별 키워드로 검색
        for cat_code, cat_name in self.naver_api.CATEGORIES.items():
            keywords = self.naver_api.CATEGORY_KEYWORDS.get(cat_code, [])

            print(f"\n[카테고리: {cat_name}]")

            for keyword in keywords:
                time.sleep(0.5)  # API 요청 간격

                result = self.find_wholesale_products(
                    keyword=keyword,
                    category=cat_name,
                    top_n=products_per_keyword,
                    min_margin=min_margin
                )

                all_results.append(result)
                total_saved += result.get('saved_count', 0)

        # 전체 결과 요약
        print("\n" + "=" * 60)
        print("전체 스캔 결과")
        print("=" * 60)

        total_products = sum(len(r['products']) for r in all_results)
        total_matches = sum(len(r['matches']) for r in all_results)

        print(f"  - 분석 카테고리: {len(self.naver_api.CATEGORIES)}개")
        print(f"  - 분석 키워드: {len(all_results)}개")
        print(f"  - 수집 상품: {total_products}개")
        print(f"  - 매칭 상품: {total_matches}개")
        print(f"  - 저장된 마진 상품: {total_saved}개")

        return {
            "categories": len(self.naver_api.CATEGORIES),
            "keywords": len(all_results),
            "products": total_products,
            "matches": total_matches,
            "saved": total_saved,
            "results": all_results
        }

    def run_interactive(self):
        """대화형 모드 실행"""
        print("\n" + "=" * 60)
        print("도매 상품 발굴 시스템")
        print("=" * 60)

        while True:
            print("\n[메뉴]")
            print("  1. 키워드로 상품 검색")
            print("  2. 트렌딩 키워드 자동 분석")
            print("  3. 카테고리별 인기 상품 분석")
            print("  4. 시즌 키워드 분석")
            print("  0. 종료")

            choice = input("\n선택: ").strip()

            if choice == "1":
                keyword = input("검색 키워드: ").strip()
                if keyword:
                    self.find_wholesale_products(keyword)

            elif choice == "2":
                count = input("분석할 키워드 수 (기본 5): ").strip()
                count = int(count) if count.isdigit() else 5
                self.find_trending_wholesale_products(top_keywords=count)

            elif choice == "3":
                print("\n[카테고리 목록]")
                for code, name in self.naver_api.CATEGORIES.items():
                    print(f"  {code}: {name}")

                category = input("\n카테고리 코드 선택: ").strip()
                if category in self.naver_api.CATEGORIES:
                    keywords = self.naver_api.CATEGORY_KEYWORDS.get(category, [])
                    for kw in keywords[:3]:
                        self.find_wholesale_products(
                            keyword=kw,
                            category=self.naver_api.CATEGORIES[category]
                        )

            elif choice == "4":
                print("\n[시즌 키워드]")
                season_keywords = self.naver_api.get_seasonal_keywords()
                for i, kw in enumerate(season_keywords, 1):
                    print(f"  {i}. {kw}")

                idx = input("\n분석할 키워드 번호 (전체: 0): ").strip()
                if idx == "0":
                    for kw in season_keywords:
                        self.find_wholesale_products(keyword=kw, category="시즌")
                elif idx.isdigit() and 1 <= int(idx) <= len(season_keywords):
                    self.find_wholesale_products(
                        keyword=season_keywords[int(idx)-1],
                        category="시즌"
                    )

            elif choice == "0":
                print("\n프로그램을 종료합니다.")
                break

            else:
                print("잘못된 선택입니다.")


def main():
    parser = argparse.ArgumentParser(description="도매 상품 발굴 시스템")
    parser.add_argument("--keyword", "-k", type=str, help="검색 키워드")
    parser.add_argument("--trending", "-t", action="store_true", help="트렌딩 키워드 분석")
    parser.add_argument("--scan", "-s", action="store_true", help="전체 카테고리 스캔")
    parser.add_argument("--count", "-c", type=int, default=5, help="분석할 키워드 수")
    parser.add_argument("--products", "-p", type=int, default=10, help="키워드당 상품 수")
    parser.add_argument("--margin", "-m", type=int, default=5000, help="최소 마진 금액 (기본 5000원)")
    parser.add_argument("--clear", action="store_true", help="기존 시트 데이터 초기화")
    parser.add_argument("--no-sheets", action="store_true", help="Google Sheets 저장 비활성화")
    parser.add_argument("--no-ai", action="store_true", help="AI 상품 비교 비활성화")
    parser.add_argument("--interactive", "-i", action="store_true", help="대화형 모드")

    args = parser.parse_args()

    finder = WholesaleProductFinder(
        use_sheets=not args.no_sheets,
        use_ai=not args.no_ai
    )

    if args.interactive:
        finder.run_interactive()
    elif args.keyword:
        finder.find_wholesale_products(
            keyword=args.keyword,
            top_n=args.products,
            min_margin=args.margin
        )
    elif args.trending:
        finder.find_trending_wholesale_products(
            top_keywords=args.count,
            top_products=args.products,
            min_margin=args.margin
        )
    elif args.scan:
        finder.scan_all_categories(
            products_per_keyword=args.products,
            min_margin=args.margin,
            clear_sheet=args.clear
        )
    else:
        # 기본: 전체 카테고리 스캔 (시트 초기화 포함)
        finder.scan_all_categories(
            products_per_keyword=args.products,
            min_margin=args.margin,
            clear_sheet=True
        )


if __name__ == "__main__":
    main()
