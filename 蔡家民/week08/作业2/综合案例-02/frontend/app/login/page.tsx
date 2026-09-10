"use client";
import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { BeakerIcon, LockClosedIcon } from "@heroicons/react/24/outline";
import { api } from "@/lib/api";

export default function LoginPage() {
  const [password,setPassword] = useState(""); const [error,setError] = useState(""); const [busy,setBusy] = useState(false); const router=useRouter();
  async function submit(event:FormEvent){event.preventDefault();setBusy(true);setError("");try{await api("/api/auth/login",{method:"POST",body:JSON.stringify({password})});router.replace("/")}catch(e){setError(e instanceof Error?e.message:"登录失败")}finally{setBusy(false)}}
  return <main className="login"><section className="card login-card">
    <div className="brand"><span className="brand-mark"><BeakerIcon width={20}/></span><span>深度研究助手</span></div>
    <p className="eyebrow">Secure workspace</p><h1>欢迎回来</h1><p className="lede">输入团队共享密码，进入研究工作台。</p>
    <form onSubmit={submit} style={{display:"grid",gap:16,marginTop:26}}><div className="field"><label htmlFor="password">共享密码</label><div style={{position:"relative"}}><LockClosedIcon width={18} style={{position:"absolute",left:12,top:13,color:"#8290a8"}}/><input id="password" type="password" value={password} onChange={e=>setPassword(e.target.value)} autoFocus style={{paddingLeft:39}}/></div></div>{error&&<div className="error">{error}</div>}<button className="btn btn-primary" disabled={busy}>{busy?"正在验证…":"进入工作台"}</button></form>
  </section></main>;
}
