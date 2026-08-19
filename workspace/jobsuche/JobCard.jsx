import React from "react";
import "./JobCard.css";

export const JobCard = ({ job }) => (
  <article className="job-card" role="listitem" aria-labelledby={`title-${job.id}`}>
    <h2 id={`title-${job.id}`} className="job-title">{job.title}</h2>
    <p className="company">{job.company}</p>
    <p className="location">{job.location}</p>
    <a href={job.url} className="apply-btn" target="_blank" rel="noopener noreferrer">
      Jetzt bewerben
    </a>
  </article>
);
