import { json, firstRow } from "../../../_lib/common.js";
export async function onRequestPost({ params, env }) {
  const id=Number.parseInt(params.id||"",10); if(!Number.isInteger(id)) return json({detail:"Invalid outreach ID"},400);
  const row=await firstRow(env.DB,"SELECT id FROM outreach WHERE id=?",id).catch(()=>null); if(!row) return json({detail:"Outreach not found"},404);
  const stamp=new Date().toISOString(); await env.DB.prepare("UPDATE outreach SET status='sent',sent_at=? WHERE id=?").bind(stamp,id).run(); return json({ok:true});
}
