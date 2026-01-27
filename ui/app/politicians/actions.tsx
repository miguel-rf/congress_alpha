"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

export default function PoliticianActions() {
    const router = useRouter();
    const [isAdding, setIsAdding] = useState(false);
    const [name, setName] = useState("");
    const [chamber, setChamber] = useState("house");
    const [notes, setNotes] = useState("");
    const [error, setError] = useState("");

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setError("");

        if (!name.trim()) {
            setError("Name is required");
            return;
        }

        try {
            const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/politicians`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ name: name.trim(), chamber, notes: notes.trim() }),
            });

            if (!res.ok) {
                const data = await res.json();
                throw new Error(data.detail || "Failed to add politician");
            }

            setName("");
            setNotes("");
            setIsAdding(false);
            router.refresh();
        } catch (err) {
            setError(err instanceof Error ? err.message : "Failed to add politician");
        }
    };

    if (!isAdding) {
        return (
            <div style={{ marginBottom: "1.5rem" }}>
                <button className="btn btn-primary" onClick={() => setIsAdding(true)}>
                    + Add Politician
                </button>
            </div>
        );
    }

    return (
        <div className="card" style={{ marginBottom: "1.5rem" }}>
            <h3 style={{ marginBottom: "1rem", fontSize: "1rem" }}>Add Politician</h3>

            <form onSubmit={handleSubmit}>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 150px 1fr auto", gap: "1rem", alignItems: "end" }}>
                    <div>
                        <label style={{ display: "block", marginBottom: "0.5rem", fontSize: "0.875rem", color: "var(--text-secondary)" }}>
                            Name
                        </label>
                        <input
                            type="text"
                            className="input"
                            placeholder="e.g., Nancy Pelosi"
                            value={name}
                            onChange={(e) => setName(e.target.value)}
                        />
                    </div>

                    <div>
                        <label style={{ display: "block", marginBottom: "0.5rem", fontSize: "0.875rem", color: "var(--text-secondary)" }}>
                            Chamber
                        </label>
                        <select
                            className="input"
                            value={chamber}
                            onChange={(e) => setChamber(e.target.value)}
                            style={{ cursor: "pointer" }}
                        >
                            <option value="house">House</option>
                            <option value="senate">Senate</option>
                        </select>
                    </div>

                    <div>
                        <label style={{ display: "block", marginBottom: "0.5rem", fontSize: "0.875rem", color: "var(--text-secondary)" }}>
                            Notes (optional)
                        </label>
                        <input
                            type="text"
                            className="input"
                            placeholder="e.g., Known for tech stocks"
                            value={notes}
                            onChange={(e) => setNotes(e.target.value)}
                        />
                    </div>

                    <div style={{ display: "flex", gap: "0.5rem" }}>
                        <button type="submit" className="btn btn-primary">Add</button>
                        <button type="button" className="btn btn-secondary" onClick={() => setIsAdding(false)}>
                            Cancel
                        </button>
                    </div>
                </div>

                {error && (
                    <p style={{ color: "var(--loss)", marginTop: "0.5rem", fontSize: "0.875rem" }}>{error}</p>
                )}
            </form>
        </div>
    );
}
