"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { ArchiveBoxIcon, BeakerIcon, ChartBarIcon, HomeIcon, ArrowRightStartOnRectangleIcon } from "@heroicons/react/24/outline";
import { api } from "@/lib/api";

const links = [
  ["/", "研究工作台", HomeIcon],
  ["/history", "历史报告", ArchiveBoxIcon],
  ["/admin", "运行管理", ChartBarIcon],
] as const;

export default function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const router = useRouter();
  return <div className="shell">
    <aside className="sidebar">
      <Link href="/" className="brand"><span className="brand-mark"><BeakerIcon width={20}/></span><span>深度研究助手</span></Link>
      <nav className="nav">{links.map(([href,label,Icon]) => <Link key={href} href={href} className={path === href ? "active" : ""}><Icon width={19}/><span>{label}</span></Link>)}</nav>
      <div className="sidebar-foot nav"><button onClick={async()=>{await api("/api/auth/logout",{method:"POST"});router.push("/login")}}><ArrowRightStartOnRectangleIcon width={19}/><span>退出登录</span></button></div>
    </aside>
    <main className="main"><div className="container">{children}</div></main>
  </div>;
}
