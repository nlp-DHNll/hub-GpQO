"use client";
import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { ArrowRightIcon, SparklesIcon } from "@heroicons/react/24/outline";
import Shell from "@/components/Shell";
import { api } from "@/lib/api";
import type { Research } from "@/lib/types";

const depthInfo = {quick:["快速","1 轮 · ≤2 分钟"],standard:["标准","2 轮 · ≤6 分钟"],deep:["深度","3 轮 · ≤12 分钟"]} as const;

export default function Home(){
  const [recent,setRecent]=useState<Research[]>([]); const [busy,setBusy]=useState(false); const [error,setError]=useState("");
  const [form,setForm]=useState({topic:"",goal:"",date_range:"不限",region:"全球",audience:"业务决策者",depth:"standard"});
  useEffect(()=>{api<Research[]>("/api/research").then(r=>setRecent(r.slice(0,5))).catch(()=>{})},[]);
  async function submit(e:FormEvent){e.preventDefault();setBusy(true);setError("");try{const out=await api<{research_id:string}>("/api/research",{method:"POST",body:JSON.stringify(form)});location.href=`/research/${out.research_id}`}catch(e){setError(e instanceof Error?e.message:"创建失败")}finally{setBusy(false)}}
  return <Shell><p className="eyebrow">Research workspace</p><h1>把复杂问题，变成可追溯的结论</h1><p className="lede">系统会规划问题、检索中英文公开资料、判断信息是否充分，并生成带来源引用的中文研究报告。</p>
    <div className="grid"><section className="card card-pad"><h2>发起新研究</h2><form onSubmit={submit} className="form-grid">
      <div className="field span-2"><label>研究主题</label><input required minLength={2} maxLength={500} placeholder="例如：2026 年企业级 AI Agent 平台竞争格局" value={form.topic} onChange={e=>setForm({...form,topic:e.target.value})}/></div>
      <div className="field span-2"><label>研究目标</label><textarea placeholder="希望解决什么决策问题？" value={form.goal} onChange={e=>setForm({...form,goal:e.target.value})}/></div>
      <div className="field"><label>时间范围</label><input value={form.date_range} onChange={e=>setForm({...form,date_range:e.target.value})}/></div>
      <div className="field"><label>地区</label><input value={form.region} onChange={e=>setForm({...form,region:e.target.value})}/></div>
      <div className="field span-2"><label>报告受众</label><input value={form.audience} onChange={e=>setForm({...form,audience:e.target.value})}/></div>
      <div className="field span-2"><label>研究深度</label><div className="depths">{Object.entries(depthInfo).map(([key,[name,info]])=><div key={key} className={`depth ${form.depth===key?"selected":""}`} onClick={()=>setForm({...form,depth:key})}><strong>{name}</strong><span>{info}</span></div>)}</div></div>
      {error&&<div className="error span-2">{error}</div>}<button className="btn btn-primary span-2" disabled={busy}><SparklesIcon width={18}/>{busy?"正在创建…":"开始深度研究"}</button>
    </form></section>
    <aside className="card card-pad"><h2>最近研究</h2><div className="list">{recent.length?recent.map(item=><Link className="list-item" href={`/research/${item.research_id}`} key={item.research_id}><div style={{display:"flex",justifyContent:"space-between",gap:8}}><strong>{item.topic}</strong><span className={`badge ${item.status}`}>{item.status}</span></div><div className="meta" style={{marginTop:8}}>V{item.version} · {new Date(item.updated_at).toLocaleString("zh-CN")}</div></Link>):<p className="meta">还没有研究记录。</p>}</div>{recent.length>0&&<Link href="/history" className="btn btn-secondary" style={{marginTop:16,width:"100%"}}>查看全部 <ArrowRightIcon width={16}/></Link>}</aside></div>
  </Shell>
}
