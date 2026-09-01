import React from 'react';

const Dashboard = () => {
  return (
    <div className="p-6 bg-gray-50 min-h-screen">
      <h1 className="text-2xl font-bold mb-6">CloudVault Dashboard</h1>
      
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
        <div className="bg-white p-4 rounded shadow">
          <h2 className="text-gray-500">Speicherverbrauch</h2>
          <p className="text-3xl font-semibold">1.2 GB</p>
        </div>
        <div className="bg-white p-4 rounded shadow">
          <h2 className="text-gray-500">Dateien</h2>
          <p className="text-3xl font-semibold">42</p>
        </div>
        <div className="bg-white p-4 rounded shadow">
          <h2 className="text-gray-500">Aktive Shares</h2>
          <p className="text-3xl font-semibold">5</p>
        </div>
      </div>

      <div className="bg-white p-6 rounded shadow">
        <h2 className="text-xl font-semibold mb-4">Dateien</h2>
        <table className="w-full text-left">
          <thead>
            <tr className="border-b">
              <th className="pb-2">Name</th>
              <th className="pb-2">Erstellt</th>
              <th className="pb-2">Aktionen</th>
            </tr>
          </thead>
          <tbody>
            <tr className="border-b">
              <td className="py-2">Dokument.pdf</td>
              <td className="py-2">2023-10-27</td>
              <td className="py-2 text-blue-600 cursor-pointer">Download</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  );
};

export default Dashboard;
