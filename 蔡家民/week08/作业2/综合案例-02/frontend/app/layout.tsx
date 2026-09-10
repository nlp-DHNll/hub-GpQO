import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "深度研究助手",
  description: "可追溯的多轮深度研究工作台",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="zh-CN"><body>{children}</body></html>;
}
