import { politiciansApi } from "@/lib/api";
import type { Politician } from "@/lib/types";
import PoliticianActions from "./actions";

export const dynamic = "force-dynamic";

async function fetchPoliticians() {
    try {
        const [politicians, count] = await Promise.all([
            politiciansApi.list(),
            politiciansApi.getCount(),
        ]);
        return { politicians, count };
    } catch {
        return { politicians: [], count: { total: 0, house: 0, senate: 0 } };
    }
}

export default async function PoliticiansPage() {
    const { politicians, count } = await fetchPoliticians();

    return (
        <>
            <header className="page-header">
                <h1 className="page-title">Politicians</h1>
                <p className="page-subtitle">Manage the whitelist of tracked politicians</p>
            </header>

            {/* Stats */}
            <div className="stats-grid" style={{ marginBottom: "1.5rem" }}>
                <div className="stat-card">
                    <div className="stat-label">Total Tracked</div>
                    <div className="stat-value">{count.total}</div>
                </div>
                <div className="stat-card">
                    <div className="stat-label">House</div>
                    <div className="stat-value" style={{ color: "var(--accent-purple)" }}>{count.house}</div>
                </div>
                <div className="stat-card">
                    <div className="stat-label">Senate</div>
                    <div className="stat-value" style={{ color: "var(--accent-cyan)" }}>{count.senate}</div>
                </div>
            </div>

            {/* Add Form */}
            <PoliticianActions />

            {/* Politicians Table */}
            <div className="table-container">
                <div className="table-header">
                    <h2 className="table-title">Whitelist</h2>
                </div>

                {politicians.length === 0 ? (
                    <div style={{ padding: "3rem", textAlign: "center", color: "var(--text-secondary)" }}>
                        No politicians on the whitelist. Add some above!
                    </div>
                ) : (
                    <table className="table">
                        <thead>
                            <tr>
                                <th>Name</th>
                                <th>Chamber</th>
                                <th>Notes</th>
                            </tr>
                        </thead>
                        <tbody>
                            {politicians.map((p: Politician) => (
                                <tr key={p.name}>
                                    <td style={{ fontWeight: 500 }}>{p.name}</td>
                                    <td>
                                        <span className={`badge badge-${p.chamber}`}>
                                            {p.chamber}
                                        </span>
                                    </td>
                                    <td style={{ color: "var(--text-secondary)", fontSize: "0.875rem" }}>
                                        {p.notes || "—"}
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                )}
            </div>
        </>
    );
}
