import { useEffect, useState } from "react";
import { Lock, ShieldCheck, ShieldX } from "lucide-react";
import { api } from "../api";
import { Empty } from "../components/ui";

const ACTIONS: Record<string, string> = {
  "file.upload": "Uploaded file", "file.duplicate_upload": "Duplicate upload ignored", "file.rejected": "Upload rejected",
  "classification.override": "Corrected category", "pii.reveal": "Unmasked narration", "case.create": "Created case",
};

export default function Audit({ caseId, role, version }: { caseId: string; role: string; version: string }) {
  const [d, setD] = useState<Awaited<ReturnType<typeof api.audit>> | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { setD(null); setErr(null); api.audit(caseId).then(setD).catch((e) => setErr(e.message)); }, [caseId, role, version]);
  if (err) return <div className="content-inner"><Empty icon={<Lock size={30} />} title="Audit log is restricted">{err}. Switch to the Senior reviewer or Auditor role in the sidebar.</Empty></div>;
  if (!d) return <div className="content-inner"><div className="skeleton" style={{ height: 200 }} /></div>;
  const v = d.verification;
  return (
    <div className="content-inner">
      <div className={`note ${v.ok ? "ok" : "crit"} row`}>
        {v.ok ? <ShieldCheck size={18} /> : <ShieldX size={18} />}
        <span>{v.ok ? <>Hash chain verified across all {v.entries} entries. Each entry includes the hash of the one before, so any edit or deletion is detectable.</> : <>Chain broken at entry {v.broken_at}.</>}</span>
      </div>
      <div className="card">
        <table className="tbl">
          <thead><tr><th>#</th><th>Time (UTC)</th><th>Who</th><th>Action</th><th>Details</th><th>Hash</th></tr></thead>
          <tbody>
            {d.entries.map((e) => {
              let det: Record<string, unknown> = {};
              try { det = JSON.parse(e.details); } catch { /* keep empty */ }
              const text = Object.entries(det).filter(([k]) => k !== "sha256").map(([k, val]) => `${k}: ${typeof val === "object" ? JSON.stringify(val) : val}`).join(" · ");
              return (
                <tr key={e.seq}>
                  <td className="num small">{e.seq}</td>
                  <td className="num small" style={{ whiteSpace: "nowrap" }}>{String(e.ts).replace("T", " ").slice(0, 19)}</td>
                  <td className="small">{e.actor} <span className="pill">{e.role}</span></td>
                  <td className="small">{ACTIONS[e.action] ?? e.action}</td>
                  <td className="small muted" style={{ maxWidth: 420 }}>{text}</td>
                  <td className="hash">{e.hash.slice(0, 10)}…</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
