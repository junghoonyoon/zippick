#!/usr/bin/env python3
"""부동산 앱 실행에 필요한 설정을 점검한다."""
import config


def main():
    errors = []
    if not config.YOUTUBE_API_KEY:
        errors.append("유튜브키가 비어 있어요.")

    provider = config.ANALYSIS_PROVIDER.lower()
    if provider == "openrouter" and not config.OPENROUTER_API_KEY:
        errors.append("분석방식=openrouter 이지만 오픈라우터키가 비어 있어요.")
    if provider == "gemini" and not config.GEMINI_API_KEY:
        errors.append("분석방식=gemini 이지만 제미나이키가 비어 있어요.")

    if errors:
        for error in errors:
            print(f"- {error}")
        return 1
    print("설정 확인 완료")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
