import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "집픽 | 서울 부동산 온기",
  description: "서울 지역별 실거래 흐름과 온기 확산을 한눈에 확인합니다."
};

export default function RootLayout({
  children
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ko">
      <body>{children}</body>
    </html>
  );
}
