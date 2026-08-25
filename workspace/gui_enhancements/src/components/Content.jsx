import React, { useState, useMemo } from 'react';
import { AnimatedCard } from './AnimatedCard';
import { Modal } from './Modal';

export const Content = ({ data }) => {
  const [filter, setFilter] = useState('');
  const [selected, setSelected] = useState(null);

  const filteredData = useMemo(() => 
    data.filter(item => item.title.toLowerCase().includes(filter.toLowerCase())),
    [data, filter]
  );

  const exportData = (format) => {
    const blob = new Blob([JSON.stringify(filteredData)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `data.${format}`;
    a.click();
  };

  return (
    <div className="p-8">
      <input 
        placeholder="Filtern..." 
        className="mb-4 p-2 border rounded"
        onChange={(e) => setFilter(e.target.value)}
      />
      <button onClick={() => exportData('json')} className="ml-2 p-2 bg-secondary-light text-white rounded">Export JSON</button>
      
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {filteredData.map(item => (
          <AnimatedCard key={item.id} {...item} onClick={() => setSelected(item)} />
        ))}
      </div>

      <Modal isOpen={!!selected} onClose={() => setSelected(null)} title={selected?.title}>
        <p>{selected?.description}</p>
      </Modal>
    </div>
  );
};
