// frontend/src/JobSearch.tsx
import React, { useState } from "react";
import { Button, TextField, LinearProgress, List, ListItem } from "@mui/material";
import axios from "axios";

interface Match {
  job_id: string;
  score: number;
}

export const JobSearch: React.FC = () => {
  const [file, setFile] = useState<File | null>(null);
  const [matches, setMatches] = useState<Match[]>([]);
  const [loading, setLoading] = useState(false);

  const handleUpload = async () => {
    if (!file) return;
    setLoading(true);
    const jobIds = ["job-1", "job-2", "job-3"]; // demo list
    const results: Match[] = [];

    for (const id of jobIds) {
      const form = new FormData();
      form.append("file", file);
      const resp = await axios.post<Match>(`/api/match/${id}`, form, {
        headers: { Authorization: `Bearer ${localStorage.getItem("token")}` },
      });
      results.push(resp.data);
    }
    setMatches(results);
    setLoading(false);
  };

  return (
    <>
      <input
        type="file"
        accept=".pdf,.docx"
        onChange={(e) => setFile(e.target.files?.[0] ?? null)}
      />
      <Button variant="contained" onClick={handleUpload} disabled={!file || loading}>
        Match Jobs
      </Button>

      {loading && <LinearProgress />}

      <List>
        {matches.map((m) => (
          <ListItem key={m.job_id}>
            {m.job_id} – Match: {m.score} %
          </ListItem>
        ))}
      </List>
    </>
  );
};
