import React from 'react';

interface FeatureToggleProps {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}

export const FeatureToggle: React.FC<FeatureToggleProps> = ({ label, checked, onChange }) => {
  return (
    <div className="flex items-center gap-4">
      <span id="toggle-label" className="text-sm font-medium text-slate-200">
        {label}
      </span>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-labelledby="toggle-label"
        onClick={() => onChange(!checked)}
        className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 focus:ring-offset-slate-900 ${
          checked ? 'bg-blue-600' : 'bg-slate-700'
        }`}
      >
        <span
          className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
            checked ? 'translate-x-6' : 'translate-x-1'
          }`}
        />
      </button>
    </div>
  );
};
