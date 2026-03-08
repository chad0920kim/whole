# -*- coding: utf-8 -*-
"""
AI 상품 비교 모듈
==================
OpenAI API를 사용하여 네이버/도매꾹 상품의 상세 페이지를 분석하고
동일 상품인지 비교합니다.
"""

import os
import re
import requests
from bs4 import BeautifulSoup
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv(override=True)


class AIProductComparator:
    """AI 기반 상품 비교 클래스"""

    def __init__(self):
        api_key = os.getenv('OPENAI_API_KEY')
        if not api_key:
            # smm2 폴더의 .env에서 가져오기
            smm2_env = os.path.join(os.path.dirname(__file__), '..', 'smm2', '.env')
            if os.path.exists(smm2_env):
                from dotenv import dotenv_values
                smm2_config = dotenv_values(smm2_env)
                api_key = smm2_config.get('OPENAI_API_KEY')

        self.client = OpenAI(api_key=api_key) if api_key else None
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }

    def fetch_page_content(self, url: str, max_length: int = 3000) -> str:
        """웹 페이지에서 상품 정보 추출"""
        if not url:
            return ""

        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            response.encoding = 'utf-8'
            soup = BeautifulSoup(response.text, 'html.parser')

            # 스크립트, 스타일 제거
            for tag in soup(['script', 'style', 'nav', 'footer', 'header']):
                tag.decompose()

            # 상품 정보 영역 찾기
            text = ""

            # 네이버 쇼핑
            if 'naver' in url or 'smartstore' in url:
                # 상품명
                title = soup.find('h2', class_='_3oDjSvLFlz') or soup.find('h3', class_='_22kNQuEXmb')
                if title:
                    text += f"상품명: {title.get_text().strip()}\n"

                # 상세 설명 영역
                detail = soup.find('div', id='INTRODUCE') or soup.find('div', class_='_2RhXy0p29z')
                if detail:
                    text += f"상세설명: {detail.get_text()[:2000]}\n"

            # 도매꾹
            elif 'domeggook' in url:
                # 상품명
                title = soup.find('h1', class_='title') or soup.find('div', class_='item_title')
                if title:
                    text += f"상품명: {title.get_text().strip()}\n"

                # 상품 정보
                info = soup.find('div', class_='item_info') or soup.find('div', id='item_detail')
                if info:
                    text += f"상품정보: {info.get_text()[:1500]}\n"

                # 상세 설명
                detail = soup.find('div', id='detail_page') or soup.find('div', class_='detail_content')
                if detail:
                    text += f"상세설명: {detail.get_text()[:1500]}\n"

            # 일반적인 경우
            if not text:
                text = soup.get_text(separator=' ', strip=True)

            # 공백 정리
            text = re.sub(r'\s+', ' ', text)
            return text[:max_length]

        except Exception as e:
            print(f"    [AI] 페이지 로드 실패: {e}")
            return ""

    def compare_products(
        self,
        naver_name: str,
        naver_brand: str,
        domeggook_name: str,
        domeggook_brand: str,
        naver_link: str = "",
        domeggook_link: str = ""
    ) -> str:
        """
        두 상품이 동일 상품인지 GPT로 상품명/브랜드 1차 비교

        Returns:
            "동일" / "유사" / "다름" / "확인불가"
        """
        if not self.client:
            return "확인불가"

        try:
            # 상품명과 브랜드만으로 빠른 비교 (페이지 접속 없이)
            prompt = f"""다음 두 상품이 동일한 상품인지 상품명과 브랜드를 비교하여 판단해주세요.

[상품1 - 네이버 쇼핑]
상품명: {naver_name}
브랜드: {naver_brand or '미확인'}

[상품2 - 도매꾹]
상품명: {domeggook_name}
브랜드: {domeggook_brand or '미확인'}

판단 기준:
- 동일: 브랜드와 모델명/규격이 일치하는 같은 상품
- 유사: 같은 카테고리/종류이지만 브랜드나 모델이 다른 상품
- 다름: 완전히 다른 종류의 상품

반드시 "동일", "유사", "다름" 중 하나로만 답변하세요."""

            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "상품 비교 전문가입니다. 상품명과 브랜드를 분석하여 동일 상품 여부를 정확히 판단합니다. 반드시 '동일', '유사', '다름' 중 하나로만 답변합니다."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=10,
                temperature=0.1
            )

            result = response.choices[0].message.content.strip()

            # 결과 정규화
            if "동일" in result:
                return "동일"
            elif "유사" in result:
                return "유사"
            elif "다름" in result:
                return "다름"
            else:
                return "확인불가"

        except Exception as e:
            print(f"    [AI] 비교 실패: {e}")
            return "확인불가"


# 테스트
if __name__ == "__main__":
    import sys
    import io
    if sys.platform == "win32":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

    comparator = AIProductComparator()

    if comparator.client:
        result = comparator.compare_products(
            naver_name="삼성 갤럭시 버즈3 프로",
            naver_link="",
            domeggook_name="삼성 갤럭시 버즈 3 프로 케이스",
            domeggook_link=""
        )
        print(f"비교 결과: {result}")
    else:
        print("OpenAI API 키가 없습니다.")
