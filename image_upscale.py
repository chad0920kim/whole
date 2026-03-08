# -*- coding: utf-8 -*-
"""
이미지 업스케일링 (AI 기반)
"""
import sys
import io
import os

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from PIL import Image
import requests


def upscale_with_realesrgan(image_path: str, scale: int = 4) -> str:
    """
    Real-ESRGAN을 사용한 이미지 업스케일링

    Args:
        image_path: 원본 이미지 경로
        scale: 확대 배율 (2 또는 4)

    Returns:
        업스케일된 이미지 경로
    """
    try:
        from realesrgan import RealESRGANer
        from basicsr.archs.rrdbnet_arch import RRDBNet
        import torch
        import cv2
        import numpy as np

        # 모델 설정
        model = RRDBNet(num_in_ch=3, num_out_ch=3, num_feat=64,
                       num_block=23, num_grow_ch=32, scale=scale)

        # GPU 사용 가능 여부 확인
        device = 'cuda' if torch.cuda.is_available() else 'cpu'
        print(f"사용 장치: {device}")

        # 모델 가중치 다운로드 (처음 실행시)
        model_path = f"weights/RealESRGAN_x{scale}plus.pth"
        if not os.path.exists(model_path):
            os.makedirs("weights", exist_ok=True)
            url = f"https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x{scale}plus.pth"
            print(f"모델 다운로드 중: {url}")
            response = requests.get(url)
            with open(model_path, 'wb') as f:
                f.write(response.content)

        # 업스케일러 초기화
        upsampler = RealESRGANer(
            scale=scale,
            model_path=model_path,
            model=model,
            tile=0,
            tile_pad=10,
            pre_pad=0,
            half=True if device == 'cuda' else False,
            device=device
        )

        # 이미지 로드
        img = cv2.imread(image_path, cv2.IMREAD_UNCHANGED)

        # 업스케일링
        output, _ = upsampler.enhance(img, outscale=scale)

        # 저장
        base_name = os.path.splitext(image_path)[0]
        output_path = f"{base_name}_upscaled_x{scale}.png"
        cv2.imwrite(output_path, output)

        print(f"업스케일 완료: {output_path}")
        return output_path

    except ImportError:
        print("Real-ESRGAN 라이브러리가 설치되지 않았습니다.")
        print("설치 방법: pip install realesrgan basicsr")
        return None


def upscale_with_pillow(image_path: str, scale: int = 2) -> str:
    """
    Pillow를 사용한 간단한 이미지 업스케일링 (LANCZOS 필터)

    Args:
        image_path: 원본 이미지 경로
        scale: 확대 배율

    Returns:
        업스케일된 이미지 경로
    """
    img = Image.open(image_path)

    # 원본 크기
    width, height = img.size
    print(f"원본 크기: {width} x {height}")

    # 새 크기
    new_width = width * scale
    new_height = height * scale
    print(f"새 크기: {new_width} x {new_height}")

    # 업스케일 (LANCZOS 필터 사용 - 고품질)
    upscaled = img.resize((new_width, new_height), Image.LANCZOS)

    # 저장
    base_name = os.path.splitext(image_path)[0]
    ext = os.path.splitext(image_path)[1]
    output_path = f"{base_name}_upscaled_x{scale}{ext}"
    upscaled.save(output_path, quality=95)

    print(f"업스케일 완료: {output_path}")
    return output_path


def upscale_with_opencv(image_path: str, scale: int = 2, method: str = "edsr") -> str:
    """
    OpenCV DNN Super Resolution을 사용한 업스케일링

    Args:
        image_path: 원본 이미지 경로
        scale: 확대 배율 (2, 3, 4)
        method: 모델 종류 (edsr, espcn, fsrcnn, lapsrn)

    Returns:
        업스케일된 이미지 경로
    """
    try:
        import cv2
        from cv2 import dnn_superres

        # Super Resolution 객체 생성
        sr = dnn_superres.DnnSuperResImpl_create()

        # 모델 다운로드/로드
        model_name = f"{method.upper()}_x{scale}.pb"
        model_path = f"models/{model_name}"

        if not os.path.exists(model_path):
            os.makedirs("models", exist_ok=True)

            # 모델 URL
            model_urls = {
                "edsr": f"https://github.com/Saafke/EDSR_Tensorflow/raw/master/models/EDSR_x{scale}.pb",
                "espcn": f"https://github.com/fannymonori/TF-ESPCN/raw/master/export/ESPCN_x{scale}.pb",
                "fsrcnn": f"https://github.com/Saafke/FSRCNN_Tensorflow/raw/master/models/FSRCNN_x{scale}.pb",
                "lapsrn": f"https://github.com/fannymonori/TF-LapSRN/raw/master/export/LapSRN_x{scale}.pb"
            }

            if method.lower() in model_urls:
                url = model_urls[method.lower()]
                print(f"모델 다운로드 중: {url}")
                response = requests.get(url)
                with open(model_path, 'wb') as f:
                    f.write(response.content)
            else:
                print(f"지원하지 않는 모델: {method}")
                return None

        # 모델 로드
        sr.readModel(model_path)
        sr.setModel(method.lower(), scale)

        # 이미지 로드
        img = cv2.imread(image_path)
        print(f"원본 크기: {img.shape[1]} x {img.shape[0]}")

        # 업스케일링
        result = sr.upsample(img)
        print(f"새 크기: {result.shape[1]} x {result.shape[0]}")

        # 저장
        base_name = os.path.splitext(image_path)[0]
        output_path = f"{base_name}_upscaled_{method}_x{scale}.png"
        cv2.imwrite(output_path, result)

        print(f"업스케일 완료: {output_path}")
        return output_path

    except ImportError:
        print("OpenCV contrib 모듈이 필요합니다.")
        print("설치 방법: pip install opencv-contrib-python")
        return None
    except Exception as e:
        print(f"오류: {e}")
        return None


def main():
    """메인 함수"""
    import argparse

    parser = argparse.ArgumentParser(description="이미지 업스케일링")
    parser.add_argument("image", help="업스케일할 이미지 경로")
    parser.add_argument("--scale", type=int, default=2, help="확대 배율 (기본값: 2)")
    parser.add_argument("--method", choices=["pillow", "opencv", "realesrgan"],
                       default="pillow", help="업스케일 방법")
    parser.add_argument("--model", default="edsr",
                       help="OpenCV 모델 (edsr, espcn, fsrcnn, lapsrn)")

    args = parser.parse_args()

    if not os.path.exists(args.image):
        print(f"파일을 찾을 수 없습니다: {args.image}")
        return

    print("=" * 60)
    print("이미지 업스케일링")
    print("=" * 60)
    print(f"  입력: {args.image}")
    print(f"  배율: x{args.scale}")
    print(f"  방법: {args.method}")
    print("=" * 60)

    if args.method == "pillow":
        upscale_with_pillow(args.image, args.scale)
    elif args.method == "opencv":
        upscale_with_opencv(args.image, args.scale, args.model)
    elif args.method == "realesrgan":
        upscale_with_realesrgan(args.image, args.scale)


if __name__ == "__main__":
    # 테스트용 직접 실행
    import sys
    if len(sys.argv) == 1:
        # 인자 없이 실행시 기본 테스트
        test_image = "test_image.png"
        if os.path.exists(test_image):
            upscale_with_pillow(test_image, 2)
        else:
            print("사용법: python image_upscale.py <이미지경로> [--scale 2] [--method pillow]")
            print()
            print("방법:")
            print("  pillow     - 기본 (빠르고 간단)")
            print("  opencv     - OpenCV DNN Super Resolution")
            print("  realesrgan - Real-ESRGAN (AI 기반, 고품질)")
    else:
        main()
