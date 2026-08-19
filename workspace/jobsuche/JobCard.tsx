import React, { memo } from 'react';
import { motion } from 'framer-motion';

interface JobCardProps {
  title: string;
  company: string;
  matchScore: number; // 0 - 100
  tags: string[];
  location: string;
}

export const JobCard: React.FC<JobCardProps> = memo(({ title, company, matchScore, tags, location }) => {
  // Farbe basierend auf Match-Score
  const getScoreColor = (score: number) => {
    if (score >= 80) return 'text-emerald-600';
    if (score >= 50) return 'text-amber-600';
    return 'text-rose-600';
  };

  return (
    <motion.div 
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className="p-6 bg-white rounded-xl border border-slate-200 shadow-sm hover:shadow-md transition-shadow duration-200"
    >
      <div className="flex justify-between items-start mb-4">
        <div>
          <h3 className="text-lg font-bold text-slate-900">{title}</h3>
          <p className="text-sm text-slate-500">{company} • {location}</p>
        </div>
        <div className="text-right">
          <span className={`text-2xl font-black ${getScoreColor(matchScore)}`}>
            {matchScore}%
          </span>
          <p className="text-[10px] uppercase tracking-wider font-bold text-slate-400">Match</p>
        </div>
      </div>

      <div className="flex flex-wrap gap-2 mb-6">
        {tags.map((tag) => (
          <span key={tag} className="px-2 py-1 bg-slate-100 text-slate-600 text-xs rounded-md font-medium">
            {tag}
          </span>
        ))}
      </div>

      <button 
        className="w-full py-2 bg-indigo-600 hover:bg-indigo-700 text-white font-semibold rounded-lg transition-colors"
        aria-label={`Bewerben auf ${title} bei ${company}`}
      >
        One-Click Bewerbung
      </button>
    </motion.div>
  );
});

JobCard.displayName = 'JobCard';
