/**
 * Container‑Komponente – übernimmt Daten‑Fetching, Mapping zu Props,
 * und sorgt für Responsiveness via Tailwind Grid.
 */
import React, { useEffect, useState } from "react";
import { JobCard, JobCardProps } from "./JobCard";

export const JobList: React.FC = () => {
  const [jobs, setJobs] = useState<JobCardProps[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch("/api/jobs?size=20")
      .then((res) => res.json())
      .then((data) => {
        // Mapping – keine Logik im UI‑Layer
        const mapped: JobCardProps[] = data.map((j: any) => ({
          id: j.id,
          title: j.title,
          company: j.company,
          location: j.location,
          salary: j.salary,
          logoUrl: `/api/companies/${j.companyId}/logo`,
        }));
        setJobs(mapped);
      })
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <p className="text-center py-8">Lade Stellen …</p>;

  return (
    <section
      className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3"
      aria-label="Stellenangebote"
    >
      {jobs.map((job) => (
        <JobCard key={job.id} {...job} />
      ))}
    </section>
  );
};
